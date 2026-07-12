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
from collections.abc import Iterator
from pathlib import Path

from agent86.cognitive.base import ModelProvider
from agent86.cognitive.prompt import build_system_prompt
from agent86.config import Config
from agent86.guardrails.egress import EgressGuardrail
from agent86.guardrails.ingress import IngressGuardrail, wrap_untrusted
from agent86.guardrails.policy import ApprovalGate, ApprovalPrompt
from agent86.memory.system import MemorySystem, build_memory
from agent86.memory.working import WorkingMemory
from agent86.observability.recorder import Recorder, build_recorder
from agent86.observability.tracing import Tracer, build_tracer
from agent86.orchestration.circuit import CircuitBreaker, CircuitTripped
from agent86.orchestration.router import ModelRouter
from agent86.orchestration.state import AgentState
from agent86.skills.loader import discover_skills
from agent86.tools.base import ToolContext
from agent86.tools.mcp_client import build_mcp
from agent86.tools.registry import ToolRegistry, default_registry
from agent86.tools.sandbox.policy import default_policy
from agent86.types import (
    AgentPhase,
    CompletionDelta,
    CompletionRequest,
    Message,
    Role,
    Step,
    ToolResult,
)

# Per-turn model-call cap (the circuit breaker also enforces cost/wall-clock).
_MAX_TURN_STEPS = 12

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
        self.working = WorkingMemory(config.limits.max_context_tokens)
        semantic = self.memory.semantic if self.memory else None

        # Skills (progressive disclosure) and MCP tools join the registry.
        self.skills = discover_skills(config)
        self.system_prompt: Message = build_system_prompt(config, self.skills)
        self.mcp = build_mcp(config)
        mcp_tools = self.mcp.tools() if self.mcp else []

        self.registry = registry or default_registry(
            config, memory=semantic, skills=self.skills, mcp_tools=mcp_tools
        )
        self.policy = default_policy(config, workspace)
        self.context = ToolContext(
            workspace=self.policy.workspace,
            policy=self.policy,
            config=config,
            memory=semantic,
            skills=self.skills,
        )
        self.gate = ApprovalGate(config.guardrails.approval, approval_prompt)
        self.ingress = IngressGuardrail(config.guardrails.ingress)
        self.egress = EgressGuardrail(config.guardrails.egress)
        self.recorder: Recorder = build_recorder(config)
        self.tracer: Tracer = build_tracer(config.observability.otel)

    @property
    def memory_note(self) -> str | None:
        return self.memory.note if self.memory else None

    @property
    def mcp_note(self) -> str | None:
        return self.mcp.note if self.mcp else None

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

    def _build_request(self, state: AgentState, extra_system: str | None) -> CompletionRequest:
        system_content = self.system_prompt.content
        if extra_system:
            system_content = f"{system_content}\n\n{extra_system}"
        convo = self.working.fit(state.messages, self.provider.count_tokens)
        return CompletionRequest(
            model=self.provider.model,
            messages=[Message(role=Role.SYSTEM, content=system_content), *convo],
            tools=self.registry.specs(),
            temperature=0.0,
            stream=True,
        )

    # ---- the loop ------------------------------------------------------ #

    def run_turn(self, user_text: str, state: AgentState) -> Iterator[CompletionDelta]:
        """Run one user turn to completion, streaming text and tool activity."""
        sid = state.session_id
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
        breaker = CircuitBreaker(self.config.limits, max_steps=_MAX_TURN_STEPS)

        while True:
            try:
                breaker.before_step()
            except CircuitTripped as exc:
                self._abort(state, sid, f"circuit tripped: {exc}")
                raise HarnessError(f"Circuit tripped: {exc}") from None

            completion = None
            with self.tracer.span("model_call", step=breaker.steps + 1, model=self.provider.model):
                for delta in self.provider.stream(self._build_request(state, recall_note)):
                    if delta.done and delta.completion is not None:
                        completion = delta.completion
                    yield delta

            if completion is None:  # pragma: no cover
                raise HarnessError("Provider stream ended without a final completion.")

            breaker.record_step(completion.usage)
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

            # Egress guardrail on the model's text.
            eg = self.egress.inspect(completion.text)
            if eg.report.flagged:
                self.recorder.event(sid, "guardrail", stage="egress", findings=eg.report.summary())
                yield CompletionDelta(text=f"\n[guardrail] output flagged: {eg.report.summary()}\n")

            step = Step(
                index=state.step_count + 1,
                phase=AgentPhase.EXECUTE,
                thought=completion.text,
                tool_calls=completion.tool_calls,
                usage=completion.usage,
            )
            state.add_message(
                Message(
                    role=Role.ASSISTANT,
                    content=completion.text,
                    tool_calls=completion.tool_calls,
                )
            )

            if not completion.tool_calls:
                state.record_step(step)
                state.phase = AgentPhase.DONE
                self.recorder.event(sid, "turn_end", status="done", steps=breaker.steps)
                self._finish_turn(state, user_text, completion.text)
                return

            for call in completion.tool_calls:
                yield CompletionDelta(text=f"\n[tool] {call.name}({_preview(call.arguments)})\n")
                with self.tracer.span("tool_call", tool=call.name):
                    result = self._execute_tool(call, sid)

                content = self._observe(result, call.name, sid)
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
        tool = self.registry.get(call.name)
        if tool is None:
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

    def _observe(self, result: ToolResult, tool_name: str, sid: str) -> str:
        """Return the observation text, wrapping suspicious tool output as untrusted."""
        if not result.ok:
            return result.error or "error"
        content = result.content
        if self.config.guardrails.scan_observations:
            report = self.ingress.inspect(content)
            if any(f.category == "injection" for f in report.findings):
                self.recorder.event(
                    sid, "guardrail", stage="observation", tool=tool_name,
                    findings=report.summary(),
                )
                return wrap_untrusted(content)
        return content

    def _finish_turn(self, state: AgentState, task: str, outcome: str) -> None:
        if self.memory:
            self.memory.episodic.record_turn(state.session_id, task, outcome)
        self._persist(state)

    def _abort(self, state: AgentState, sid: str, reason: str) -> None:
        state.phase = AgentPhase.ERROR
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
        return f"error: {(result.error or '').splitlines()[0][:160]}"
    first = (result.content or "").strip().splitlines()
    head = first[0] if first else "(no output)"
    return head[:160]


__all__ = ["Harness", "HarnessError"]
