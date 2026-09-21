"""The execution loop (Tier 2, Pillar 1) — the harness's nervous system.

Drives the full Reason -> Act -> Observe cycle and integrates every tier:

- **Tier 3** streams the model's proposal
- **Tier 5** ingress-scans input and tool observations, egress-scans output, and a
  circuit breaker bounds steps / cost / wall-clock / consecutive errors
- **Tier 4** executes approved tool calls in the sandbox (via the registry + gate)
- **Pillar 2** trims context, injects episodic recall, and persists the session
- observability records every event to the flight recorder and OTel spans

Every arrow crosses the deterministic harness; the model only ever occupies the model call.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from agent86.cognitive.base import ModelProvider
from agent86.cognitive.prompt import build_system_prompt
from agent86.config import CompactionMode, Config, MCPServerConfig
from agent86.guardrails.egress import EgressGuardrail
from agent86.guardrails.ingress import IngressGuardrail, wrap_untrusted
from agent86.guardrails.policy import ApprovalGate, ApprovalPrompt
from agent86.memory.store import MemoryStoreError
from agent86.memory.system import MemorySystem, build_memory
from agent86.memory.working import (
    MIN_CONVERSATION_TOKENS,
    SUMMARY_MAX_TOKENS,
    SUMMARY_SYSTEM_PROMPT,
    WorkingMemory,
    apply_summary,
    conversation_budget,
    count_spec_tokens,
    render_transcript,
)
from agent86.observability.recorder import Recorder, build_recorder
from agent86.observability.tracing import Tracer, build_tracer, set_attributes
from agent86.orchestration.circuit import CircuitBreaker, CircuitTripped
from agent86.orchestration.router import ModelRouter
from agent86.orchestration.state import AgentState, TurnSummary
from agent86.skills.loader import discover_skills
from agent86.tools.base import ToolContext
from agent86.tools.mcp_client import MCPManager, build_mcp
from agent86.tools.registry import ToolRegistry, default_registry
from agent86.tools.sandbox.executor import build_executor
from agent86.tools.sandbox.policy import default_policy
from agent86.types import (
    AgentPhase,
    CompletionDelta,
    CompletionRequest,
    Message,
    Role,
    Step,
    ToolResult,
    Usage,
    invalid_arguments_result,
)

# Sentinel so an explicitly-passed memory=None means "no memory", not "auto-build".
_AUTO = object()

#: What the harness says to a model that ran out of output tokens mid-answer. Terse on
#: purpose: anything longer invites the model to restate its plan instead of resuming.
CONTINUE_PROMPT = "Continue exactly where you left off; do not repeat."

#: How many times one turn may ask for more. A model that hits the output cap four times in
#: a row is not writing a long answer, it is looping — and each continuation is a full-price
#: request carrying the whole conversation.
MAX_CONTINUATIONS = 3


def compacted_notice(count: int) -> str:
    """The user-visible line for a successful compaction.

    Compaction and continuation used to be invisible: the recorder knew, the user did not, so
    a conversation that silently lost its oldest turns — or an answer stitched from four
    requests — looked like the model behaving oddly. These are the harness talking about the
    conversation, so they are yielded as ordinary text deltas with a prefix both surfaces
    recognise (``agent86.ui.repl.NOTICE_PREFIXES``) and render dim, on their own line.
    """
    return f"\n[compacted {count} messages into a summary]\n"


def compaction_failed_notice(count: int) -> str:
    """The user-visible line when summarizing failed and the oldest messages were dropped."""
    return f"\n[compaction failed; dropped {count} messages]\n"


def continuation_notice(index: int, total: int = MAX_CONTINUATIONS) -> str:
    """The user-visible line announcing continuation ``index`` of ``total``."""
    return f"\n[continuation {index}/{total}]\n"


#: Longest a derived session title may be, including the ellipsis.
SESSION_TITLE_MAX = 60

#: The header line an ``@file`` mention block opens with, exactly as ``tui.mentions`` writes
#: it: ``--- @notes.md (3 lines) ---`` / ``--- @missing (not attached) ---``.
_MENTION_BLOCK_RE = re.compile(r"^--- @.*---[ \t]*$", re.MULTILINE)


def typed_prefix(text: str) -> str:
    """What the user actually *typed*, with any ``@file`` attachment blocks stripped off.

    ``expand_mentions`` sends ``typed text + "\\n\\n" + blocks``, so a prompt that opened with
    a mention used to name its session after the attached file's first 60 bytes. Cutting at
    the first block header (and then at the blank line that separates it from the typed text)
    gives back the sentence the user wrote. Text with no mention block is returned unchanged.
    """
    match = _MENTION_BLOCK_RE.search(text)
    if match is None:
        return text
    head = text[: match.start()]
    return head.split("\n\n", 1)[0]


def session_title(state: AgentState) -> str | None:
    """A display name for this session: its first user message, collapsed and truncated.

    Derived from the *typed* text only: a session opened with ``fix @notes.md`` is named
    after the ask, not after the file that got inlined behind it.

    None until there is one — a session that has been opened but never spoken to has nothing
    to be named after, and must NOT be given a placeholder name that would then stick (the
    store's title is write-once).
    """
    for message in state.messages:
        if message.role is not Role.USER:
            continue
        content = message.content or ""
        # Fallback to the whole message when the typed part is empty — a pasted block with
        # nothing in front of it still deserves a name over being skipped entirely.
        text = " ".join(typed_prefix(content).split()) or " ".join(content.split())
        if not text:
            continue
        if len(text) <= SESSION_TITLE_MAX:
            return text
        return text[: SESSION_TITLE_MAX - 3] + "..."
    return None


class HarnessError(RuntimeError):
    """A turn could not be completed."""


class Harness:
    """Binds provider, tools, sandbox, gate, memory, guardrails, and tracing to a session."""

    def __init__(
        self,
        config: Config,
        provider: ModelProvider | None = None,
        approval_prompt: ApprovalPrompt | None = None,
        workspace: Path | None = None,
        registry: ToolRegistry | None = None,
        memory: MemorySystem | None | object = _AUTO,
    ):
        self.config = config
        self.router = ModelRouter(config, forced_provider=provider)
        self.provider = self.router.default_provider()
        self._memory_error: str | None = None
        if memory is _AUTO:
            self.memory, self._memory_error = self._auto_memory(config)
        else:
            self.memory = memory  # type: ignore[assignment]
        # Seeded with the flat cap; `_context_budget` recomputes it from the model's real
        # window (and the live tool catalogue) before every request.
        self.working = WorkingMemory(config.limits.max_context_tokens or MIN_CONVERSATION_TOKENS)
        semantic = self.memory.semantic if self.memory else None

        # Built first because skill discovery needs the RESOLVED workspace: the project skill
        # roots (`<workspace>/.agent86/skills`, `<workspace>/.claude/skills`) hang off it, and
        # discovering them against the process CWD instead meant `--workspace` (and every test
        # using `tmp_path`) silently loaded the wrong project's skills — or none.
        self.policy = default_policy(config, workspace)

        # Skills (progressive disclosure) and MCP tools join the registry.
        self.skills = discover_skills(config, self.policy.workspace)
        self.system_prompt: Message = build_system_prompt(config, self.skills)
        self.mcp = build_mcp(config)
        mcp_tools = self.mcp.tools() if self.mcp else []

        self.registry = registry or default_registry(
            config,
            memory=semantic,
            skills=self.skills,
            mcp_tools=mcp_tools,
            enable_delegate=config.agents.enabled,
        )
        self.executor, self.sandbox_note = build_executor(config)
        self.context = ToolContext(
            workspace=self.policy.workspace,
            policy=self.policy,
            config=config,
            memory=semantic,
            skills=self.skills,
            spawn=(self.spawn_subagent if config.agents.enabled else None),
            executor=self.executor,
        )
        # `context=`: `Tool.preview` resolves paths through the sandbox policy when it has a
        # context, so the diff an approval prompt shows is the diff of the file that would
        # actually be written — not of a same-named file under the process CWD.
        self.gate = ApprovalGate(config.guardrails.approval, approval_prompt, self.context)
        self.ingress = IngressGuardrail(config.guardrails.ingress)
        self.egress = EgressGuardrail(config.guardrails.egress)
        self.recorder: Recorder = build_recorder(config)
        self.tracer: Tracer = build_tracer(
            config.observability.otel,
            exporter=str(config.observability.otel_exporter),
            endpoint=config.observability.otel_endpoint,
        )
        # Set by `cancel()` from ANOTHER thread (the TUI's main thread, while `run_turn` is
        # being driven by a worker). An Event, not a bool, so the flag is published safely
        # across threads; `run_turn` clears it as its first act.
        self._cancel = threading.Event()
        # Usage burned by sub-agents since the last tool call. The `delegate` tool's contract
        # is `str -> str`, so a spawned agent's cost cannot ride back on its return value;
        # it lands here and `run_turn` folds it into the turn after each tool call.
        self._subagent_usage = Usage()
        # `spawn_subagent` can now be reached from a tool worker thread, and
        # `acc = acc + usage` is a read-modify-write: without this, two delegations landing
        # together would lose one of them from the turn's cost.
        self._subagent_usage_lock = threading.Lock()
        # Per-turn read-out for the UI, live from the first model call of the turn. Published
        # on `state.last_turn`; see `_begin_turn_summary` / `_close_turn_summary`.
        self._summary: TurnSummary | None = None
        self._turn_started = 0.0
        # Re-entrancy guard: the summarizer's own model call must not trigger a compaction.
        self._compacting = False
        self._enforce_retention()

    def cancel(self) -> None:
        """Ask the in-flight turn to stop at its next safe point.

        Safe points are: before each model call, per streamed delta, and between tool calls —
        never mid-tool, so a half-written file or a half-sent request is impossible. Calling
        this when no turn is running is harmless: `run_turn` clears the flag on entry.
        """
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _enforce_retention(self) -> None:
        """Auto-prune the flight-recorder log to its configured caps at startup."""
        if not self.memory:
            return
        mem_cfg = self.config.memory
        removed = self.memory.store.enforce_retention(
            max_episodes=mem_cfg.retention_max_episodes,
            max_sessions=mem_cfg.retention_max_sessions,
            max_age_days=mem_cfg.retention_max_age_days,
        )
        if removed:
            self.recorder.event("memory", "retention_prune", **removed)

    @staticmethod
    def _auto_memory(config: Config) -> tuple[MemorySystem | None, str | None]:
        """Build memory, degrading to none (with a reason) rather than failing the session.

        A locked or unwritable database is a reason to run without recall, not a reason the
        user cannot talk to a model at all — and the note says what would fix it, so the
        degradation is visible rather than silent.
        """
        try:
            return build_memory(config), None
        except Exception as exc:  # noqa: BLE001 - any store failure degrades, none crashes
            detail = (
                str(exc) if isinstance(exc, MemoryStoreError) else f"{type(exc).__name__}: {exc}"
            )
            return None, f"unavailable, running without recall or session history. {detail}"

    @property
    def memory_note(self) -> str | None:
        if self._memory_error:
            return self._memory_error
        return self.memory.note if self.memory else None

    def set_model(self, model_str: str) -> ModelProvider:
        """Switch the active model for subsequent turns.

        Builds the provider for ``model_str`` (e.g. ``openrouter:anthropic/claude-3.7-sonnet``)
        and pins it — this overrides triage routing for the rest of the session. Raises
        ``ProviderError``/``ValueError`` if the ref is unknown or its API key is missing, in
        which case the current model is left unchanged.
        """
        from agent86.cognitive.base import provider_for_model

        provider = provider_for_model(model_str, self.config)  # may raise; caught by caller
        # Switching models often follows a config edit (a new key, a new base_url), and the
        # router caches a provider per model string — so drop the cache before pinning, or a
        # later switch back to a previous model would resurrect the pre-edit provider.
        self.router.invalidate()
        self.router.set_forced(provider)
        self.provider = provider
        return provider

    @property
    def mcp_note(self) -> str | None:
        return self.mcp.note if self.mcp else None

    def ensure_mcp(self) -> MCPManager:
        """Return the live MCP manager, creating an empty one if this session started with none.

        ``build_mcp`` returns None when nothing is configured (or everything is disabled), so
        adding the *first* MCP server mid-session has no manager to attach to. This creates one
        with no servers; its background loop starts lazily on the first connection attempt, so
        calling this costs nothing until a server is actually connected.
        """
        if self.mcp is None:
            self.mcp = MCPManager({})
        return self.mcp

    def add_mcp_server(self, name: str, cfg: MCPServerConfig) -> tuple[list[str], list[str]]:
        """Mount an already-connected server's tools into the live registry (D-13).

        Called AFTER the connection test has already connected this server via the manager's own
        connect method — this method never opens a transport, it only wires the resulting tools
        in. Returns ``(mounted, collisions)``: a tool whose name is already taken is reported
        rather than silently dropped (D-24), because in an explicit, watched add the user can act
        on the collision — unlike bulk startup, whose registration path stays lenient.

        D-15: nothing is injected into the conversation; ``_build_request`` reads
        ``self.registry.specs()`` fresh on the next turn, so the change is picked up there.
        """
        manager = self.ensure_mcp()
        mounted: list[str] = []
        collisions: list[str] = []
        for tool in manager.tools_for(name):
            try:
                self.registry.register(tool)
                mounted.append(tool.name)
            except ValueError:
                collisions.append(tool.name)
        manager.servers[name] = cfg
        return mounted, collisions

    def remove_mcp_server(self, name: str) -> None:
        """Unmount a server's tools and close its session immediately (D-14).

        Symmetric with ``add_mcp_server``: leaving a removed server's tools callable would let
        the model invoke something the user just deleted. Safe to call for a name that was never
        mounted.
        """
        if self.mcp is None:
            return
        for tool in self.mcp.tools_for(name):
            self.registry.unregister(tool.name)
        self.mcp.stop_server(name)
        self.mcp.servers.pop(name, None)

    # ---- sessions ------------------------------------------------------ #

    def new_session(self) -> AgentState:
        state = AgentState()
        state.phase = AgentPhase.EXECUTE
        self._persist(state)
        return state

    def resume(self, session_id: str) -> AgentState | None:
        if not self.memory:
            return None
        raw = self.memory.store.load_session(session_id)
        return AgentState.model_validate_json(raw) if raw is not None else None

    def _persist(self, state: AgentState) -> None:
        if not self.memory:
            return
        store = self.memory.store
        # Named once, on the first persist that HAS a user message to name it after:
        # `new_session` saves an empty state (title None, so no placeholder name sticks) and
        # `_finish_turn` supplies the real one. Re-deriving it every save would let a
        # compaction that drops the opening message silently rename the session, so the
        # store is asked first — a primary-key lookup, and only until the name exists.
        title = session_title(state) if store.session_title(state.session_id) is None else None
        store.save_session(state.session_id, state.model_dump_json(), title=title)

    # ---- request construction ----------------------------------------- #

    def _system_content(self, extra_system: str | None) -> str:
        content = self.system_prompt.content
        if extra_system:
            content = f"{content}\n\n{extra_system}"
        return content

    def _model_ref(self) -> str:
        """The ``provider:model`` ref every per-model config lookup keys on.

        ``config_name``, never ``name``: the adapter behind ``openrouter:`` calls itself
        "openai", so building this from ``name`` looked up ``[providers.openai]`` and threw
        away the ``max_tokens`` (and the window override) the user set on the section they
        actually wrote.
        """
        return self.provider.config_ref

    def _context_budget(self, system_content: str, specs: list) -> int:
        """Conversation tokens available for THIS request, from the model's real window.

        The window minus what the request already spends before a single turn of history is
        added — the compiled system prompt and the tool catalogue, both of which change at
        runtime (skills, MCP servers, the episodic recall note) — minus the room the response
        needs. ``limits.max_context_tokens`` survives as an optional hard cap for anyone who
        wants to spend less than the window allows.
        """
        from agent86.cognitive.capabilities import context_window_for, max_output_tokens_for

        ref = self._model_ref()
        window = context_window_for(ref, self.config)
        overhead = self.provider.count_tokens(
            [Message(role=Role.SYSTEM, content=system_content)]
        ) + count_spec_tokens(specs)
        budget = conversation_budget(
            window,
            overhead_tokens=overhead,
            reserve_tokens=self.config.limits.context_reserve_tokens,
            output_tokens=max_output_tokens_for(ref, self.config),
            hard_cap=self.config.limits.max_context_tokens,
        )
        # Published on the shared WorkingMemory so sub-agents trim to the same number.
        self.working.max_tokens = budget
        return budget

    def _build_request(self, state: AgentState, extra_system: str | None) -> CompletionRequest:
        from agent86.cognitive.capabilities import max_output_tokens_for

        system_content = self._system_content(extra_system)
        specs = self.registry.specs()
        budget = self._context_budget(system_content, specs)
        convo = self.working.fit(state.messages, self.provider.count_tokens, budget)
        return CompletionRequest(
            model=self.provider.model,
            messages=[Message(role=Role.SYSTEM, content=system_content), *convo],
            tools=specs,
            temperature=0.0,
            stream=True,
            max_tokens=max_output_tokens_for(self._model_ref(), self.config),
        )

    # ---- compaction ----------------------------------------------------- #

    def _summary_provider(self) -> ModelProvider:
        """The model that writes compaction summaries: the cheap route, else the current one.

        Summarizing is exactly the bulk, low-judgement work triage routing exists for, and it
        happens at the moment the turn is already expensive. When routing is off (or the cheap
        model cannot be built) the current provider does it rather than the turn failing.
        """
        if self.router.enabled:
            try:
                return self.router.provider_for(self.config.model.route.cheap)
            except Exception:  # unbuildable cheap model: not worth failing a turn over
                pass
        return self.provider

    def _write_summary(self, prefix: list[Message]) -> tuple[str, Usage]:
        """Ask the summarizer for a structured digest of ``prefix``. May raise."""
        provider = self._summary_provider()
        completion = provider.complete(
            CompletionRequest(
                model=provider.model,
                messages=[
                    Message(role=Role.SYSTEM, content=SUMMARY_SYSTEM_PROMPT),
                    Message(role=Role.USER, content=render_transcript(prefix)),
                ],
                temperature=0.0,
                stream=False,
                # A summary is a bounded artefact; there is no reason to let it run to the
                # provider's default ceiling and cost more than the span it replaces.
                max_tokens=SUMMARY_MAX_TOKENS * 2,
            )
        )
        return completion.text.strip(), completion.usage

    def _compact_if_needed(
        self,
        state: AgentState,
        sid: str,
        extra_system: str | None,
        summary: TurnSummary,
        breaker: CircuitBreaker,
        protect_from: int,
    ) -> str | None:
        """Replace the oldest over-budget span with a summary, in place, before a model call.

        Dropping the oldest turns (the pre-v0.8 behaviour, still available as
        ``[limits] compaction = "drop"``) makes a long session forget its own goal: the first
        thing to fall off the window is the user's original ask. Summarizing keeps the goal,
        the decisions and the paths discovered at a fraction of the tokens.

        This is called at most once per step (once per model call), and never re-entrantly,
        so a summarizer that is itself expensive cannot start a compaction cascade. It must
        never raise: any failure falls back to the drop behaviour ``fit`` already implements,
        and says so in the trace.

        Returns the user-visible notice ``run_turn`` should yield (``None`` when nothing
        happened). Returned rather than yielded because this is a plain method called from
        the loop body — the loop owns the stream.
        """
        if self.config.limits.compaction != CompactionMode.SUMMARIZE:
            return None
        if self._compacting:
            return None

        system_content = self._system_content(extra_system)
        budget = self._context_budget(system_content, self.registry.specs())
        counter = self.provider.count_tokens
        if self.working.fits(state.messages, counter, budget):
            return None
        cut = self.working.compaction_cut(
            state.messages, counter, budget, protect_from=protect_from
        )
        if cut <= 0:
            # Everything left is the current turn or its tool blocks: there is nothing old
            # enough to compact, so `fit` trims and the provider's own limits take over.
            return None

        prefix = state.messages[:cut]
        dropped_tokens = counter(prefix)
        self._compacting = True
        try:
            text, usage = self._write_summary(prefix)
        except Exception as exc:  # a failed summary must never cost the user their turn
            self.recorder.event(
                sid, "compaction", status="failed", fallback="drop",
                dropped=len(prefix), error=f"{type(exc).__name__}: {exc}",
            )
            return compaction_failed_notice(len(prefix))
        finally:
            self._compacting = False

        if not text:
            self.recorder.event(
                sid, "compaction", status="empty", fallback="drop", dropped=len(prefix)
            )
            return compaction_failed_notice(len(prefix))

        # The originals are archived before they leave the live conversation.
        if self.memory:
            try:
                self.memory.episodic.record_compaction(sid, text, prefix)
            except Exception:  # pragma: no cover - archival must not fail the turn
                pass

        state.messages = apply_summary(text, state.messages[cut:])
        summary.compactions += 1
        summary.add_usage(usage)
        breaker.cost_usd += usage.cost_usd
        summary_tokens = counter([Message(role=Role.USER, content=text)])
        self.recorder.event(
            sid, "compaction", status="ok", dropped=len(prefix),
            dropped_tokens=dropped_tokens, summary_tokens=summary_tokens,
            kept=len(state.messages), model=self._summary_provider().model,
        )
        # Persist immediately: a resume must see the compacted history, not a stale copy that
        # would silently re-inflate the context on the next turn.
        self._persist(state)
        return compacted_notice(len(prefix))

    # ---- the loop ------------------------------------------------------ #

    def run_turn(
        self, user_text: str, state: AgentState, *, display_text: str | None = None
    ) -> Iterator[CompletionDelta]:
        """Run one user turn to completion, streaming text and tool activity.

        ``user_text`` is what the model sees — for a prompt with ``@file`` mentions that is
        the expanded text, file blocks and all. ``display_text`` is what the user *typed*,
        and is what the trace records as the turn's task: a 200KB inlined file in the
        recorder's ``task`` field is noise, and it is not what the user asked. Defaults to
        ``user_text`` for every caller that has no separate typed line.

        A skill activated with ``use_skill`` is **turn-scoped**: its ``allowed-tools`` list
        restricts what the model may call for the rest of *this* turn only. The restriction
        is lifted on entry and again on every exit — done, cancelled, circuit-tripped,
        provider failure, or a consumer that simply abandons the generator (the `finally`
        runs on ``close()`` too). Without the exit clear, a skill activated once would keep
        refusing tools for the whole session, with nothing in the conversation explaining
        why.
        """
        self.context.clear_skill()
        # One `turn` span per user turn, parent of this turn's `model_call` and `tool_call`
        # spans. Its closing attributes come from `state.last_turn`, which every exit path
        # (done, cancelled, tripped, failed) stamps — so a backend sees the cost of an
        # aborted turn too, not just a clean one.
        with self.tracer.span(
            "turn", **{"session.id": state.session_id, "gen_ai.request.model": self.provider.model}
        ) as span:
            try:
                yield from self._run_turn(user_text, state, display_text=display_text)
            finally:
                self.context.clear_skill()
                set_attributes(span, _turn_attributes(state, self.provider.model))

    def _run_turn(
        self, user_text: str, state: AgentState, *, display_text: str | None = None
    ) -> Iterator[CompletionDelta]:
        sid = state.session_id
        # A cancel requested while no turn was running must not kill the next one.
        self._cancel.clear()
        summary = self._begin_turn_summary(state)
        self.recorder.event(sid, "turn_start", task=display_text or user_text)

        # Ingress guardrail on the user's input.
        in_report = self.ingress.inspect(user_text)
        if in_report.flagged:
            self.recorder.event(
                sid, "guardrail", stage="ingress_input", findings=in_report.summary()
            )
            if self.ingress.should_block(in_report):
                msg = f"Refused: input tripped the ingress guardrail ({in_report.summary()})."
                state.add_message(Message(role=Role.USER, content=user_text))
                state.add_message(Message(role=Role.ASSISTANT, content=msg))
                state.phase = AgentPhase.ERROR
                self._close_turn_summary(state)
                self.recorder.event(sid, "turn_end", status="blocked")
                self._persist(state)
                yield CompletionDelta(text=msg)
                return
            yield CompletionDelta(text=f"[guardrail] input flagged: {in_report.summary()}\n")

        # Dynamic routing: pick the model for this turn (triage cheap vs frontier).
        self.provider = self.router.provider_for(self.router.select_model(user_text))
        if self.router.enabled:
            self.recorder.event(sid, "route", model=self.provider.model)

        recall_note = self.memory.episodic.recall_note(user_text) if self.memory else None
        # Where this turn begins in the history: compaction never reaches past it, so the ask
        # the agent is answering right now can never be the thing that gets summarized away.
        turn_start = len(state.messages)
        state.add_message(Message(role=Role.USER, content=user_text))
        # No private cap here: a hard-coded 12 silently overrode `limits.max_steps` (default
        # 40), so a long legitimate task died at 12 steps and raising the configured limit did
        # nothing. The breaker's own bounds — steps, cost, wall-clock, error streak — are the
        # only budget, and they are the ones the user can see and change.
        breaker = CircuitBreaker(self.config.limits)
        self._subagent_usage = Usage()
        # Continuation state: where in `state.messages` the first partial answer went, and
        # the pieces collected so far. Both reset the moment a step turns out to want tools.
        cont_start: int | None = None
        cont_parts: list[str] = []
        continuations = 0

        while True:
            # Cancellation point (a): never start another model call once cancelled — that is
            # the expensive, long-latency step the user is actually trying to escape.
            if self._cancel.is_set():
                yield from self._cancelled(state, sid, breaker.steps)
                return

            try:
                breaker.before_step()
            except CircuitTripped as exc:
                self._abort(state, sid, f"circuit tripped: {exc}")
                raise HarnessError(f"Circuit tripped: {exc}") from None

            # Compact BEFORE the request is built, so the model call sees the compacted
            # history and the summary is what gets persisted. Once per step, never nested.
            notice = self._compact_if_needed(
                state, sid, recall_note, summary, breaker, turn_start
            )
            if notice:
                # Said out loud, not just recorded: a conversation that quietly lost its
                # oldest turns is indistinguishable, from the user's seat, from a model that
                # forgot what it was doing.
                yield CompletionDelta(text=notice)

            completion = None
            # Redact mode cannot stream: text inspected only after it has been shown to the
            # user has already leaked. So the step's text deltas (and the terminal `done`
            # delta, whose order matters to consumers) are withheld here and replayed below
            # from the INSPECTED text. warn/off keep live streaming — they change nothing.
            buffering = self.egress.mode == "redact"
            buffered: list[str] = []
            final_delta: CompletionDelta | None = None
            # GenAI semantic conventions where a name exists (`gen_ai.*`); `agent86.*` for the
            # things the conventions have no word for, so a backend can group them anyway.
            with self.tracer.span(
                "model_call",
                **{
                    "gen_ai.system": self.provider.name,
                    "gen_ai.request.model": self.provider.model,
                    "agent86.step": breaker.steps + 1,
                },
            ) as model_span:
                stream = self.provider.stream(self._build_request(state, recall_note))
                try:
                    for delta in stream:
                        # Cancellation point (b): a long response should stop mid-flight, not
                        # after the provider has finished streaming it.
                        if self._cancel.is_set():
                            break
                        if delta.done and delta.completion is not None:
                            completion = delta.completion
                        if buffering:
                            if delta.text:
                                buffered.append(delta.text)
                            if delta.done:
                                final_delta = delta
                            continue
                        yield delta
                except Exception as exc:
                    # A provider failure mid-stream (dropped connection, malformed SSE,
                    # HTTP error) used to escape here with the USER message already appended
                    # and nothing persisted: no ERROR phase, no turn_end, an unresumable
                    # session. Close the turn out properly, THEN surface the failure.
                    raise self._stream_failed(state, sid, exc) from exc
                finally:
                    # Breaking out of a generator leaves it suspended; close it so the
                    # provider's own `finally` runs and the HTTP response is released.
                    close = getattr(stream, "close", None)
                    if close is not None:
                        close()
                    set_attributes(model_span, _model_call_attributes(completion))

            if self._cancel.is_set():
                # Whatever was buffered still belongs to the user — redacted, then shown.
                if buffered:
                    partial = self.egress.inspect("".join(buffered))
                    if partial.text:
                        yield CompletionDelta(text=partial.text)
                yield from self._cancelled(state, sid, breaker.steps)
                return

            if completion is None:
                self._abort(state, sid, "provider stream ended without a final completion")
                raise HarnessError(
                    f"The '{self.provider.name}' provider ended its stream for model "
                    f"{self.provider.model!r} without a final completion. The response was "
                    "truncated; retry, or check the endpoint's streaming implementation."
                )

            breaker.record_step(completion.usage)
            summary.steps = breaker.steps
            summary.add_usage(completion.usage)
            self.recorder.event(
                sid,
                "model_call",
                step=breaker.steps,
                model=self.provider.model,
                input_tokens=completion.usage.input_tokens,
                output_tokens=completion.usage.output_tokens,
                cost_usd=completion.usage.cost_usd,
                stop_reason=completion.stop_reason,
                tool_calls=[tc.name for tc in completion.tool_calls],
            )

            # Egress guardrail on the model's text. In redact mode `eg.text` is the redacted
            # copy and it is what everything downstream sees: the stream, the ASSISTANT
            # message, the step trace, and the episodic outcome. Persisting the raw text
            # while showing a redacted one would just move the leak into the session store.
            eg = self.egress.inspect(completion.text)
            text = eg.text if buffering else completion.text
            if eg.report.flagged:
                self.recorder.event(sid, "guardrail", stage="egress", findings=eg.report.summary())
            if buffering:
                if text:
                    yield CompletionDelta(text=text)
                if final_delta is not None:
                    yield final_delta
            if eg.report.flagged:
                yield CompletionDelta(text=f"\n[guardrail] output flagged: {eg.report.summary()}\n")

            self._scan_tool_arguments(completion.tool_calls, sid)

            step = Step(
                index=state.step_count + 1,
                phase=AgentPhase.EXECUTE,
                thought=text,
                tool_calls=completion.tool_calls,
                usage=completion.usage,
            )
            state.add_message(
                Message(
                    role=Role.ASSISTANT,
                    content=text,
                    tool_calls=completion.tool_calls,
                )
            )

            if not completion.tool_calls:
                # The model ran out of OUTPUT tokens, not out of things to say. Treating that
                # as a finished answer is how a long answer silently ends mid-sentence; ask
                # for the rest instead, bounded, and stitch the pieces back together.
                if (
                    completion.stop_reason == "max_tokens"
                    and continuations < MAX_CONTINUATIONS
                    and not self._cancel.is_set()
                ):
                    continuations += 1
                    summary.continuations = continuations
                    if cont_start is None:
                        cont_start = len(state.messages) - 1  # the first partial answer
                    cont_parts.append(text)
                    state.add_message(Message(role=Role.USER, content=CONTINUE_PROMPT))
                    state.record_step(step)
                    self.recorder.event(
                        sid, "continuation", index=continuations, step=breaker.steps,
                        model=self.provider.model, chars=len(text),
                    )
                    # Announced BEFORE the continuation request goes out, so the pause the
                    # user is about to sit through has a visible reason.
                    yield CompletionDelta(text=continuation_notice(continuations))
                    continue

                if cont_start is not None:
                    # Collapse [partial, "continue", partial, ...] into the one answer the
                    # model meant to give. Keeping the harness's own prompts in the history
                    # would teach the next turn to imitate them.
                    cont_parts.append(text)
                    text = "".join(cont_parts)
                    state.messages[cont_start:] = [Message(role=Role.ASSISTANT, content=text)]
                    step.thought = text

                state.record_step(step)
                state.phase = AgentPhase.DONE
                self.recorder.event(
                    sid, "turn_end", status="done", steps=breaker.steps,
                    continuations=continuations,
                )
                self._finish_turn(state, user_text, text)
                return

            # A step that wants tools ends any continuation in progress: the partial answers
            # and the prompts that joined them stay in the history exactly as they happened,
            # because the tool results have to attach to the right assistant message.
            cont_start, cont_parts = None, []

            # Cancellation point (c): BEFORE the batch, never mid-execution — a tool that has
            # started must be allowed to finish and be observed.
            if self._cancel.is_set():
                state.record_step(step)
                yield from self._cancelled(state, sid, breaker.steps)
                return

            # The whole batch is announced up front: with reads running concurrently, a start
            # line printed next to its own result would claim an ordering that isn't real.
            for call in completion.tool_calls:
                yield CompletionDelta(text=f"\n[tool] {call.name}({_preview(call.arguments)})\n")

            results = self._execute_batch(completion.tool_calls, sid)

            # Observed strictly in call order, whatever order they finished in: the TOOL
            # messages must line up with the assistant's tool_calls for every provider.
            for call, result in zip(completion.tool_calls, results, strict=True):
                content = self._observe(result, call.name, sid)
                summary.tool_calls += 1
                sub_usage = self._take_subagent_usage(breaker)
                summary.add_usage(sub_usage)
                step.usage = step.usage + sub_usage
                step.results.append(result)
                state.add_message(
                    Message(role=Role.TOOL, content=content, tool_call_id=call.id, name=call.name)
                )
                yield CompletionDelta(text=f"[tool] {call.name} -> {_summarize(result)}\n")

                try:
                    breaker.record_tool_result(result.ok)
                except CircuitTripped as exc:
                    state.record_step(step)
                    self._abort(state, sid, f"circuit tripped: {exc}")
                    raise HarnessError(f"Circuit tripped: {exc}") from None

            # Every call in the batch has an observation by now — including any that was
            # skipped because the cancel landed mid-batch — so the history is never left with
            # a tool_use that no tool_result answers.
            if self._cancel.is_set():
                state.record_step(step)
                yield from self._cancelled(state, sid, breaker.steps)
                return

            state.record_step(step)

    # ---- helpers ------------------------------------------------------- #

    def _execute_tool(self, call, sid: str) -> ToolResult:
        """Resolve and run one call. Kept as the single-call path used by tests and callers."""
        decided, _parallel = self._resolve_call(call)
        return decided if decided is not None else self._dispatch_call(call, sid)

    def _resolve_call(self, call) -> tuple[ToolResult | None, bool]:
        """Decide one call WITHOUT running it: ``(settled_result, may_run_in_parallel)``.

        A non-None result means the call is already answered and must not be dispatched.
        This is the half that may block on a human — the approval gate prompts here — so the
        orchestrator runs it sequentially for every call in a step before anything executes.

        Arguments the provider could not parse are answered here, before the registry, the
        approval gate, or any tool sees them: the model's mistake is its JSON, and only the
        harness can say so — a tool handed ``{}`` reports a missing field instead.
        """
        invalid = call.invalid_arguments
        if invalid is not None:
            return invalid_arguments_result(call, invalid), False
        tool = self.registry.get(call.name)
        if tool is None:
            # The registry's own "Unknown tool" answer; nothing runs, nothing to parallelise.
            return self.registry.dispatch(call, self.context), False
        decision = self.gate.decide(tool, call)
        if not decision.approved:
            return (
                ToolResult(
                    call_id=call.id, name=call.name, ok=False,
                    error=f"Not executed: {decision.reason}.",
                ),
                False,
            )
        return None, (not tool.side_effecting and getattr(tool, "parallel_safe", True))

    def _dispatch_call(self, call, sid: str) -> ToolResult:
        """Run one approved call. Never raises — called from worker threads."""
        # The span wraps the error path too: a dispatch that blew up is exactly the tool call
        # someone tracing this turn wants to find, so it must still close with `tool.ok`.
        with self.tracer.span(
            "tool_call", **{"tool.name": call.name, "gen_ai.tool.name": call.name}
        ) as tool_span:
            try:
                result = self.registry.dispatch(call, self.context)
            except Exception as exc:  # pragma: no cover - Tool.run already traps tool errors
                result = ToolResult(
                    call_id=call.id, name=call.name, ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            set_attributes(tool_span, {"tool.ok": result.ok})
        self.recorder.event(
            sid, "tool_call", tool=call.name, ok=result.ok,
            arguments=call.arguments, error=result.error,
        )
        return result

    def _not_executed(self, call, reason: str) -> ToolResult:
        return ToolResult(
            call_id=call.id, name=call.name, ok=False, error=f"Not executed: {reason}."
        )

    def _parallel_eligible(self, call) -> bool:
        """Could this call share a worker pool? Decided from the TOOL alone — never the gate,
        which may prompt and must be consulted exactly once, on the orchestrator's thread."""
        if call.invalid_arguments is not None:
            return False
        tool = self.registry.get(call.name)
        return (
            tool is not None
            and not tool.side_effecting
            and bool(getattr(tool, "parallel_safe", True))
        )

    def _execute_batch(self, calls: list, sid: str) -> list[ToolResult]:
        """Run a step's tool calls and return their results **in call order**.

        The rule, deliberately the simplest one that is safe: read-only calls may run
        concurrently with each other; side-effecting calls run sequentially, in the order the
        model asked for them, *after* the reads. Two writes racing could interleave edits to
        the same file, and a write racing a read could hand the model a half-written file —
        ordering them costs a little latency and buys determinism. Approvals are all resolved
        first, on this thread, because the gate may prompt a human.

        Thread-safety of what a concurrent read touches: ``ToolContext`` is read-only for
        every built-in, the sandbox executor holds no per-call state, and ``MCPManager``
        marshals onto its own background loop with ``run_coroutine_threadsafe``.
        """
        candidates = [i for i, call in enumerate(calls) if self._parallel_eligible(call)]
        enabled = self.config.limits.parallel_tools
        if not enabled or len(candidates) < 2:
            # Strictly sequential, resolving and running one call at a time — the pre-v0.8
            # path, unchanged, and the one a single-call step always takes.
            return [
                self._not_executed(call, "cancelled")
                if self._cancel.is_set()
                else self._execute_tool(call, sid)
                for call in calls
            ]

        settled: list[ToolResult | None] = []
        parallel_ok: list[bool] = []
        for call in calls:
            result, may_parallel = self._resolve_call(call)
            settled.append(result)
            parallel_ok.append(may_parallel)

        pending = [i for i, r in enumerate(settled) if r is None]
        reads = [i for i in pending if parallel_ok[i]]
        writes = [i for i in pending if not parallel_ok[i]]

        if len(reads) > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(
                max_workers=min(4, len(reads)), thread_name_prefix="agent86-tool"
            ) as pool:
                futures = {i: pool.submit(self._dispatch_call, calls[i], sid) for i in reads}
                collected = {i: f.result() for i, f in futures.items()}
            for i, result in collected.items():
                settled[i] = result
        else:
            for i in reads:
                settled[i] = (
                    self._not_executed(calls[i], "cancelled")
                    if self._cancel.is_set()
                    else self._dispatch_call(calls[i], sid)
                )

        for i in writes:
            # Between calls, never mid-execution: a tool that has started is always allowed
            # to finish and be observed.
            settled[i] = (
                self._not_executed(calls[i], "cancelled")
                if self._cancel.is_set()
                else self._dispatch_call(calls[i], sid)
            )

        return [
            r if r is not None else self._not_executed(calls[i], "skipped")
            for i, r in enumerate(settled)
        ]

    def _scan_tool_arguments(self, calls: list, sid: str) -> None:
        """Egress-scan tool-call arguments — the other way a secret leaves the harness.

        A model that reads a key out of a file and then posts it to a URL never puts it in
        its text, so scanning only the prose misses it entirely. The call is NOT blocked (the
        approval gate is what stops side effects, and silently rewriting arguments would hand
        the tool something the model did not ask for) — the finding is recorded so the leak is
        visible in the trace. Skipped in ``off`` mode, like every other egress check.
        """
        if not calls or self.egress.mode == "off":
            return
        for call in calls:
            try:
                payload = json.dumps(call.arguments, ensure_ascii=False, default=str)
            except (TypeError, ValueError):  # pragma: no cover - defensive
                payload = str(call.arguments)
            report = self.egress.inspect(payload).report
            if report.flagged:
                self.recorder.event(
                    sid, "guardrail", stage="egress_tool_args",
                    tool=call.name, findings=report.summary(),
                )

    def _observe(self, result: ToolResult, tool_name: str, sid: str) -> str:
        """Return the observation text, wrapping suspicious tool output as untrusted."""
        content = result.content
        if not result.ok:
            # A failed result may carry its detail in `content` rather than `error`:
            # python_exec / run_command report a non-zero exit with ok=False, error=None
            # and the full "exit code / stdout / stderr" payload (the traceback) in content.
            # Returning a bare "error" here blinded the model to its own bugs. Keep BOTH
            # when both exist so an approval denial keeps its reason alongside any output.
            error = (result.error or "").strip()
            body = (content or "").strip()
            if error and body:
                content = f"{error}\n{body}"
            else:
                content = error or body or "error"
        if self.config.guardrails.scan_observations:
            report = self.ingress.inspect(content)
            if any(f.category == "injection" for f in report.findings):
                self.recorder.event(
                    sid, "guardrail", stage="observation", tool=tool_name,
                    findings=report.summary(),
                )
                return wrap_untrusted(content)
        return content

    def spawn_subagent(self, role: str, task: str, depth: int = 1) -> str:
        """Run a delegated task on a role-scoped sub-agent; returns its final result."""
        from agent86.agents.subagent import SubAgent

        max_depth = self.config.agents.max_depth
        if depth > max_depth:
            return f"[delegation refused: max agent depth {max_depth} reached]"
        self.recorder.event("sub", "spawn", role=role, depth=depth, task=task[:200])
        text, usage = SubAgent(self, role, depth).run(task)
        # Accumulated rather than returned: `ToolContext.spawn` is `(role, task) -> str` and
        # the delegate tool's output must stay exactly the sub-agent's answer.
        with self._subagent_usage_lock:
            self._subagent_usage = self._subagent_usage + usage
        return text

    def _take_subagent_usage(self, breaker: CircuitBreaker) -> Usage:
        """Drain the sub-agent accumulator into the turn's budget; return it for the step.

        Tokens a sub-agent burned are tokens this turn burned, so they belong in the cost cap
        and in `state.usage` — otherwise delegation is a blind spot the breaker cannot see and
        `/cost` under-reports every delegated turn. The cost is added to the breaker directly
        rather than via `record_step`, which would also count the sub-agent as one of the
        PARENT's model calls and quietly shrink the step budget the user configured.
        """
        with self._subagent_usage_lock:
            usage, self._subagent_usage = self._subagent_usage, Usage()
        breaker.cost_usd += usage.cost_usd
        return usage

    # ---- per-turn summary ---------------------------------------------- #

    def _begin_turn_summary(self, state: AgentState) -> TurnSummary:
        """Start (and publish) the turn's read-out, so a UI can watch it fill."""
        summary = TurnSummary()
        self._summary = summary
        self._turn_started = time.monotonic()
        state.last_turn = summary
        return summary

    def _close_turn_summary(self, state: AgentState) -> None:
        """Stamp the duration and leave the summary on ``state.last_turn``.

        Called from every exit from a turn — done, cancelled, aborted — so the UI never shows
        a stale turn or a turn that never ends. Idempotent: closing twice is harmless.
        """
        summary = self._summary
        if summary is None:
            return
        summary.duration_s = round(time.monotonic() - self._turn_started, 3)
        state.last_turn = summary
        self._summary = None

    def _finish_turn(self, state: AgentState, task: str, outcome: str) -> None:
        self._close_turn_summary(state)
        if self.memory:
            self.memory.episodic.record_turn(state.session_id, task, outcome)
        self._persist(state)

    def _cancelled(self, state: AgentState, sid: str, steps: int) -> Iterator[CompletionDelta]:
        """Close out a user-cancelled turn: record it, persist it, and say so.

        The conversation so far is deliberately KEPT — the user stopped the agent, they did not
        undo it, and the partial exchange is what the next turn has to reason from. `AgentPhase`
        has no CANCELLED member and is a cross-tier contract, so the phase stays ERROR and
        "cancelled" is carried by the recorder's `status`/`reason` (greppable in the trace).
        """
        state.phase = AgentPhase.ERROR
        self._close_turn_summary(state)
        self.recorder.event(sid, "turn_end", status="cancelled", reason="cancelled", steps=steps)
        self._persist(state)
        yield CompletionDelta(text="\n[cancelled]\n")

    def _stream_failed(self, state: AgentState, sid: str, exc: BaseException) -> Exception:
        """Close out a turn whose model call blew up, and return the error to raise.

        The turn is aborted (ERROR phase, ``turn_end status="error"``, persisted) BEFORE the
        exception leaves ``run_turn``, so a provider failure can never leave a session with a
        dangling user message and no record of what happened. A ``ProviderError`` already
        carries an actionable message and is surfaced unchanged; anything else (a raw httpx
        or JSON error a provider failed to convert) is wrapped so callers only ever have to
        handle the harness's own error types.
        """
        from agent86.cognitive.base import ProviderError

        detail = f"{type(exc).__name__}: {exc}"
        self._abort(state, sid, f"provider stream failed: {detail}")
        if isinstance(exc, ProviderError):
            return exc
        return ProviderError(
            f"The '{self.provider.name}' provider failed while streaming model "
            f"{self.provider.model!r} — {detail}. The turn was halted and the session saved; "
            "retry the request, or check the endpoint and network."
        )

    def _abort(self, state: AgentState, sid: str, reason: str) -> None:
        state.phase = AgentPhase.ERROR
        self._close_turn_summary(state)
        self.recorder.event(sid, "turn_end", status="error", reason=reason)
        self._persist(state)

    def close(self) -> None:
        self.recorder.close()
        # Flushes the BatchSpanProcessor: a short-lived `agent86 run` would otherwise exit
        # with the turn's spans still sitting in the batch queue.
        self.tracer.close()
        if self.mcp:
            self.mcp.close()
        if self.memory:
            self.memory.close()


def _model_call_attributes(completion) -> dict[str, object]:
    """Closing attributes for a ``model_call`` span.

    Tolerant by construction: a stream that died before its final completion, or a provider
    whose ``Usage`` lacks a field, must still close its span rather than raise inside the
    ``finally`` that is already unwinding a failure.
    """
    if completion is None:
        return {"agent86.completed": False}
    usage = getattr(completion, "usage", None)
    return {
        "agent86.completed": True,
        "gen_ai.usage.input_tokens": getattr(usage, "input_tokens", None),
        "gen_ai.usage.output_tokens": getattr(usage, "output_tokens", None),
        "gen_ai.response.finish_reasons": [completion.stop_reason]
        if getattr(completion, "stop_reason", None)
        else None,
        "agent86.cost_usd": getattr(usage, "cost_usd", None),
        "agent86.tool_calls": len(getattr(completion, "tool_calls", ()) or ()),
    }


def _turn_attributes(state: AgentState, model: str) -> dict[str, object]:
    """Closing attributes for the ``turn`` span, read off ``state.last_turn``."""
    summary = getattr(state, "last_turn", None)
    if summary is None:
        return {"gen_ai.request.model": model}
    return {
        "gen_ai.request.model": model,
        "gen_ai.usage.input_tokens": getattr(summary, "input_tokens", None),
        "gen_ai.usage.output_tokens": getattr(summary, "output_tokens", None),
        "agent86.cost_usd": getattr(summary, "cost_usd", None),
        "agent86.steps": getattr(summary, "steps", None),
        "agent86.tool_calls": getattr(summary, "tool_calls", None),
        "agent86.duration_s": getattr(summary, "duration_s", None),
        "agent86.phase": str(getattr(state, "phase", "")) or None,
    }


def _preview(arguments: dict) -> str:
    try:
        text = json.dumps(arguments, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(arguments)
    return text if len(text) <= 160 else text[:160] + " ..."


def _summarize(result: ToolResult) -> str:
    if not result.ok:
        # A failed result may carry no error string (only content, or nothing) — fall back
        # so the first-line lookup can't IndexError on an empty splitlines().
        detail = (result.error or "").strip() or (result.content or "").strip() or "(failed)"
        return f"error: {detail.splitlines()[0][:160]}"
    first = (result.content or "").strip().splitlines()
    head = first[0] if first else "(no output)"
    return head[:160]


__all__ = [
    "Harness",
    "HarnessError",
    "compacted_notice",
    "compaction_failed_notice",
    "continuation_notice",
    "session_title",
    "typed_prefix",
]
