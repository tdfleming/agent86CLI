"""The execution loop (Tier 2, Pillar 1) — the harness's nervous system.

Drives the full Reason -> Act -> Observe cycle and integrates memory (Pillar 2):

- **working memory** trims the sent context to a token budget each request
- **episodic memory** recalls similar past turns and injects them as context
- **semantic memory** is exposed via the remember/recall tools
- session state is persisted after every turn for cross-session continuity
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from agent86.cognitive.base import ModelProvider, provider_for_model
from agent86.cognitive.prompt import build_system_prompt
from agent86.config import Config
from agent86.guardrails.policy import ApprovalGate, ApprovalPrompt
from agent86.memory.system import MemorySystem, build_memory
from agent86.memory.working import WorkingMemory
from agent86.orchestration.state import AgentState
from agent86.tools.base import ToolContext
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

# Upper bound on model calls per user turn (circuit breaker; cost/wall-clock join in Phase 5).
_MAX_TURN_STEPS = 12

# Sentinel so an explicitly-passed memory=None means "no memory" rather than "auto-build".
_AUTO = object()


class HarnessError(RuntimeError):
    """A turn could not be completed."""


class Harness:
    """Binds provider, tools, sandbox, approval gate, and memory to session state."""

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
        self.provider = provider or provider_for_model(config.model.default, config)
        self.system_prompt: Message = build_system_prompt(config)
        self.memory: MemorySystem | None = (
            build_memory(config) if memory is _AUTO else memory  # type: ignore[assignment]
        )
        self.working = WorkingMemory(config.limits.max_context_tokens)
        semantic = self.memory.semantic if self.memory else None
        self.registry = registry or default_registry(config, memory=semantic)
        self.policy = default_policy(config, workspace)
        self.context = ToolContext(
            workspace=self.policy.workspace,
            policy=self.policy,
            config=config,
            memory=semantic,
        )
        self.gate = ApprovalGate(config.guardrails.approval, approval_prompt)

    @property
    def memory_note(self) -> str | None:
        return self.memory.note if self.memory else None

    # ---- sessions ------------------------------------------------------ #

    def new_session(self) -> AgentState:
        state = AgentState()
        state.phase = AgentPhase.EXECUTE
        self._persist(state)
        return state

    def resume(self, session_id: str) -> AgentState | None:
        """Load a prior session by id, or None if unknown / memory disabled."""
        if not self.memory:
            return None
        raw = self.memory.store.load_session(session_id)
        if raw is None:
            return None
        return AgentState.model_validate_json(raw)

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
        recall_note = self.memory.episodic.recall_note(user_text) if self.memory else None

        state.add_message(Message(role=Role.USER, content=user_text))
        step_budget = min(_MAX_TURN_STEPS, self.config.limits.max_steps)
        consecutive_errors = 0

        for _ in range(step_budget):
            completion = None
            for delta in self.provider.stream(self._build_request(state, recall_note)):
                if delta.done and delta.completion is not None:
                    completion = delta.completion
                yield delta

            if completion is None:  # pragma: no cover - provider contract violation
                raise HarnessError("Provider stream ended without a final completion.")

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
                self._finish_turn(state, user_text, completion.text)
                return

            for call in completion.tool_calls:
                yield CompletionDelta(text=f"\n[tool] {call.name}({_preview(call.arguments)})\n")

                tool = self.registry.get(call.name)
                if tool is None:
                    result = self.registry.dispatch(call, self.context)
                else:
                    decision = self.gate.decide(tool, call)
                    if not decision.approved:
                        result = ToolResult(
                            call_id=call.id,
                            name=call.name,
                            ok=False,
                            error=f"Not executed: {decision.reason}.",
                        )
                    else:
                        result = self.registry.dispatch(call, self.context)

                step.results.append(result)
                state.add_message(
                    Message(
                        role=Role.TOOL,
                        content=result.content if result.ok else (result.error or "error"),
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )
                yield CompletionDelta(text=f"[tool] {call.name} -> {_summarize(result)}\n")

                if result.ok:
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
                    if consecutive_errors > self.config.limits.max_consecutive_errors:
                        state.record_step(step)
                        state.phase = AgentPhase.ERROR
                        self._persist(state)
                        raise HarnessError(
                            f"Aborted after {consecutive_errors} consecutive tool errors."
                        )

            state.record_step(step)

        state.phase = AgentPhase.ERROR
        self._persist(state)
        raise HarnessError(f"Turn exceeded the step budget ({step_budget}).")

    def _finish_turn(self, state: AgentState, task: str, outcome: str) -> None:
        if self.memory:
            self.memory.episodic.record_turn(state.session_id, task, outcome)
        self._persist(state)

    def close(self) -> None:
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
