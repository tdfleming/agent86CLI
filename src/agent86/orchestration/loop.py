"""The execution loop (Tier 2, Pillar 1) — the harness's nervous system.

Phase 2 wires the Reason -> Act -> Observe skeleton with a live model but no tools yet:
each turn compiles the prompt, streams a completion, and records a :class:`Step`. The
tool-execution branch (marked ``# PHASE 3``) and circuit breakers are structured in so
the later phases slot in without reshaping the loop.
"""

from __future__ import annotations

from collections.abc import Iterator

from agent86.cognitive.base import ModelProvider, provider_for_model
from agent86.cognitive.prompt import build_system_prompt
from agent86.config import Config
from agent86.orchestration.state import AgentState
from agent86.types import (
    AgentPhase,
    CompletionDelta,
    CompletionRequest,
    Message,
    Role,
    Step,
)

# The loop will not exceed this many model calls in a single turn (circuit breaker;
# fully enforced with cost/wall-clock in Phase 5). With no tools yet it is always 1.
_MAX_TURN_STEPS = 8


class HarnessError(RuntimeError):
    """A turn could not be completed."""


class Harness:
    """Binds a model provider to session state and drives the loop."""

    def __init__(self, config: Config, provider: ModelProvider | None = None):
        self.config = config
        self.provider = provider or provider_for_model(config.model.default, config)
        self.system_prompt: Message = build_system_prompt(config)

    def new_session(self) -> AgentState:
        state = AgentState()
        state.phase = AgentPhase.EXECUTE
        return state

    def _build_request(self, state: AgentState) -> CompletionRequest:
        return CompletionRequest(
            model=self.provider.model,
            messages=[self.system_prompt, *state.messages],
            tools=[],  # PHASE 3: inject the tool registry's specs here
            temperature=0.0,
            stream=True,
        )

    def run_turn(self, user_text: str, state: AgentState) -> Iterator[CompletionDelta]:
        """Run one user turn, streaming text deltas as they arrive.

        Appends the user message, streams the assistant response, records the step, and
        (from Phase 3) loops to execute any tool calls the model proposes.
        """
        state.add_message(Message(role=Role.USER, content=user_text))
        step_budget = min(_MAX_TURN_STEPS, self.config.limits.max_steps)

        for _ in range(step_budget):
            request = self._build_request(state)
            completion = None
            for delta in self.provider.stream(request):
                if delta.done and delta.completion is not None:
                    completion = delta.completion
                yield delta

            if completion is None:  # pragma: no cover - provider contract violation
                raise HarnessError("Provider stream ended without a final completion.")

            state.add_message(
                Message(
                    role=Role.ASSISTANT,
                    content=completion.text,
                    tool_calls=completion.tool_calls,
                )
            )
            state.record_step(
                Step(
                    index=state.step_count,
                    phase=AgentPhase.EXECUTE,
                    thought=completion.text,
                    tool_calls=completion.tool_calls,
                    usage=completion.usage,
                )
            )

            if not completion.tool_calls:
                state.phase = AgentPhase.DONE
                return

            # PHASE 3: execute completion.tool_calls through the tool registry + sandbox,
            # append ToolResult messages (role=TOOL), then continue the loop so the model
            # can observe the results. Until then, surface the unfulfilled intent.
            names = ", ".join(tc.name for tc in completion.tool_calls)
            yield CompletionDelta(
                text=(
                    f"\n[tool execution arrives in Phase 3 - "
                    f"model requested: {names}]\n"
                )
            )
            state.phase = AgentPhase.DONE
            return

        # Step budget exhausted (only reachable once tools drive multi-step turns).
        state.phase = AgentPhase.ERROR
        raise HarnessError(f"Turn exceeded the step budget ({step_budget}).")


__all__ = ["Harness", "HarnessError"]
