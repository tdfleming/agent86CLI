"""The execution loop (Tier 2, Pillar 1) — the harness's nervous system.

Phase 3 closes the Reason -> Act -> Observe cycle: the model proposes tool calls, the
harness gates them through the human-in-the-loop approval policy, executes the approved
ones in the sandbox, feeds the results back as observations, and loops until the model
answers without requesting a tool (or a circuit breaker trips).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from agent86.cognitive.base import ModelProvider, provider_for_model
from agent86.cognitive.prompt import build_system_prompt
from agent86.config import Config
from agent86.guardrails.policy import ApprovalGate, ApprovalPrompt
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


class HarnessError(RuntimeError):
    """A turn could not be completed."""


class Harness:
    """Binds a model provider, tool registry, sandbox, and approval gate to session state."""

    def __init__(
        self,
        config: Config,
        provider: ModelProvider | None = None,
        approval_prompt: ApprovalPrompt | None = None,
        workspace: Path | None = None,
        registry: ToolRegistry | None = None,
    ):
        self.config = config
        self.provider = provider or provider_for_model(config.model.default, config)
        self.system_prompt: Message = build_system_prompt(config)
        self.registry = registry or default_registry(config)
        self.policy = default_policy(config, workspace)
        self.context = ToolContext(
            workspace=self.policy.workspace, policy=self.policy, config=config
        )
        self.gate = ApprovalGate(config.guardrails.approval, approval_prompt)

    def new_session(self) -> AgentState:
        state = AgentState()
        state.phase = AgentPhase.EXECUTE
        return state

    def _build_request(self, state: AgentState) -> CompletionRequest:
        return CompletionRequest(
            model=self.provider.model,
            messages=[self.system_prompt, *state.messages],
            tools=self.registry.specs(),
            temperature=0.0,
            stream=True,
        )

    def run_turn(self, user_text: str, state: AgentState) -> Iterator[CompletionDelta]:
        """Run one user turn to completion, streaming text and tool activity."""
        state.add_message(Message(role=Role.USER, content=user_text))
        step_budget = min(_MAX_TURN_STEPS, self.config.limits.max_steps)
        consecutive_errors = 0

        for _ in range(step_budget):
            completion = None
            for delta in self.provider.stream(self._build_request(state)):
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
                return

            # ---- Act: execute each proposed tool call through the gate + sandbox ---- #
            for call in completion.tool_calls:
                yield CompletionDelta(text=f"\n[tool] {call.name}({_preview(call.arguments)})\n")

                tool = self.registry.get(call.name)
                if tool is None:
                    result = self.registry.dispatch(call, self.context)  # -> unknown-tool error
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
                # Observe: feed the result back to the model as a tool message.
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
                        raise HarnessError(
                            f"Aborted after {consecutive_errors} consecutive tool errors."
                        )

            state.record_step(step)
            # loop: the model now observes the tool results and decides the next action

        state.phase = AgentPhase.ERROR
        raise HarnessError(f"Turn exceeded the step budget ({step_budget}).")


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
