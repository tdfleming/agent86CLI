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
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from agent86.cognitive.base import ModelProvider
from agent86.cognitive.prompt import build_system_prompt
from agent86.config import Config, MCPServerConfig
from agent86.guardrails.egress import EgressGuardrail
from agent86.guardrails.ingress import IngressGuardrail, wrap_untrusted
from agent86.guardrails.policy import ApprovalGate, ApprovalPrompt
from agent86.memory.system import MemorySystem, build_memory
from agent86.memory.working import (
    MIN_CONVERSATION_TOKENS,
    WorkingMemory,
    conversation_budget,
    count_spec_tokens,
)
from agent86.observability.recorder import Recorder, build_recorder
from agent86.observability.tracing import Tracer, build_tracer
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
        self.memory: MemorySystem | None = (
            build_memory(config) if memory is _AUTO else memory  # type: ignore[assignment]
        )
        # Seeded with the flat cap; `_context_budget` recomputes it from the model's real
        # window (and the live tool catalogue) before every request.
        self.working = WorkingMemory(config.limits.max_context_tokens or MIN_CONVERSATION_TOKENS)
        semantic = self.memory.semantic if self.memory else None

        # Skills (progressive disclosure) and MCP tools join the registry.
        self.skills = discover_skills(config)
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
        self.policy = default_policy(config, workspace)
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
        self.gate = ApprovalGate(config.guardrails.approval, approval_prompt)
        self.ingress = IngressGuardrail(config.guardrails.ingress)
        self.egress = EgressGuardrail(config.guardrails.egress)
        self.recorder: Recorder = build_recorder(config)
        self.tracer: Tracer = build_tracer(config.observability.otel)
        # Set by `cancel()` from ANOTHER thread (the TUI's main thread, while `run_turn` is
        # being driven by a worker). An Event, not a bool, so the flag is published safely
        # across threads; `run_turn` clears it as its first act.
        self._cancel = threading.Event()
        # Usage burned by sub-agents since the last tool call. The `delegate` tool's contract
        # is `str -> str`, so a spawned agent's cost cannot ride back on its return value;
        # it lands here and `run_turn` folds it into the turn after each tool call.
        self._subagent_usage = Usage()
        # Per-turn read-out for the UI, live from the first model call of the turn. Published
        # on `state.last_turn`; see `_begin_turn_summary` / `_close_turn_summary`.
        self._summary: TurnSummary | None = None
        self._turn_started = 0.0
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

    @property
    def memory_note(self) -> str | None:
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
        if self.memory:
            self.memory.store.save_session(state.session_id, state.model_dump_json())

    # ---- request construction ----------------------------------------- #

    def _system_content(self, extra_system: str | None) -> str:
        content = self.system_prompt.content
        if extra_system:
            content = f"{content}\n\n{extra_system}"
        return content

    def _model_ref(self) -> str:
        return f"{self.provider.name}:{self.provider.model}"

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
            reserve_tokens=int(getattr(self.config.limits, "context_reserve_tokens", 0) or 0),
            output_tokens=max_output_tokens_for(ref, self.config),
            hard_cap=int(getattr(self.config.limits, "max_context_tokens", 0) or 0),
        )
        # Published on the shared WorkingMemory so sub-agents trim to the same number.
        self.working.max_tokens = budget
        return budget

    def _build_request(self, state: AgentState, extra_system: str | None) -> CompletionRequest:
        system_content = self._system_content(extra_system)
        specs = self.registry.specs()
        budget = self._context_budget(system_content, specs)
        convo = self.working.fit(state.messages, self.provider.count_tokens, budget)
        kwargs: dict = {
            "model": self.provider.model,
            "messages": [Message(role=Role.SYSTEM, content=system_content), *convo],
            "tools": specs,
            "temperature": 0.0,
            "stream": True,
        }
        # Additive on the provider side: set it only once types.CompletionRequest carries it,
        # so this works both before and after that field lands.
        if "max_tokens" in CompletionRequest.model_fields:
            from agent86.cognitive.capabilities import max_output_tokens_for

            kwargs["max_tokens"] = max_output_tokens_for(self._model_ref(), self.config)
        return CompletionRequest(**kwargs)

    # ---- the loop ------------------------------------------------------ #

    def run_turn(self, user_text: str, state: AgentState) -> Iterator[CompletionDelta]:
        """Run one user turn to completion, streaming text and tool activity."""
        sid = state.session_id
        # A cancel requested while no turn was running must not kill the next one.
        self._cancel.clear()
        summary = self._begin_turn_summary(state)
        self.recorder.event(sid, "turn_start", task=user_text)

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
        state.add_message(Message(role=Role.USER, content=user_text))
        # No private cap here: a hard-coded 12 silently overrode `limits.max_steps` (default
        # 40), so a long legitimate task died at 12 steps and raising the configured limit did
        # nothing. The breaker's own bounds — steps, cost, wall-clock, error streak — are the
        # only budget, and they are the ones the user can see and change.
        breaker = CircuitBreaker(self.config.limits)
        self._subagent_usage = Usage()

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

            completion = None
            # Redact mode cannot stream: text inspected only after it has been shown to the
            # user has already leaked. So the step's text deltas (and the terminal `done`
            # delta, whose order matters to consumers) are withheld here and replayed below
            # from the INSPECTED text. warn/off keep live streaming — they change nothing.
            buffering = self.egress.mode == "redact"
            buffered: list[str] = []
            final_delta: CompletionDelta | None = None
            with self.tracer.span("model_call", step=breaker.steps + 1, model=self.provider.model):
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
                state.record_step(step)
                state.phase = AgentPhase.DONE
                self.recorder.event(sid, "turn_end", status="done", steps=breaker.steps)
                self._finish_turn(state, user_text, text)
                return

            for call in completion.tool_calls:
                # Cancellation point (c): BETWEEN tool calls, never mid-execution — a tool
                # that has started must be allowed to finish and be observed.
                if self._cancel.is_set():
                    state.record_step(step)
                    yield from self._cancelled(state, sid, breaker.steps)
                    return
                yield CompletionDelta(text=f"\n[tool] {call.name}({_preview(call.arguments)})\n")
                with self.tracer.span("tool_call", tool=call.name):
                    result = self._execute_tool(call, sid)

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

            state.record_step(step)

    # ---- helpers ------------------------------------------------------- #

    def _execute_tool(self, call, sid: str) -> ToolResult:
        # Arguments the provider could not parse are answered here, before the registry,
        # the approval gate, or any tool sees them: the model's mistake is its JSON, and
        # only the harness can say so — a tool handed `{}` reports a missing field instead.
        invalid = call.invalid_arguments
        if invalid is not None:
            result = invalid_arguments_result(call, invalid)
        elif (tool := self.registry.get(call.name)) is None:
            result = self.registry.dispatch(call, self.context)
        else:
            decision = self.gate.decide(tool, call)
            if not decision.approved:
                result = ToolResult(
                    call_id=call.id, name=call.name, ok=False,
                    error=f"Not executed: {decision.reason}.",
                )
            else:
                result = self.registry.dispatch(call, self.context)
        self.recorder.event(
            sid, "tool_call", tool=call.name, ok=result.ok,
            arguments=call.arguments, error=result.error,
        )
        return result

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
        if self.mcp:
            self.mcp.close()
        if self.memory:
            self.memory.close()


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


__all__ = ["Harness", "HarnessError"]
