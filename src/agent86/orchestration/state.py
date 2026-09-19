"""Agent state (Tier 2).

The finite-state-machine record the orchestrator threads through the loop: conversation
history, per-step trace, cumulative usage, and the current phase. Phase 2 keeps this in
memory; Phase 4 persists it to SQLite for cross-session continuity.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from agent86.types import AgentPhase, Message, Step, Usage


class TurnSummary(BaseModel):
    """What one user turn cost and did — the UI's per-turn read-out.

    Recorded on ``AgentState.last_turn`` at every exit from ``run_turn`` (done, cancelled,
    circuit-tripped, or failed), so a surface can always show the turn that just ended rather
    than re-deriving it from ``state.usage`` (which is cumulative across the session).

    It lives here and not in ``types.py`` deliberately: it is an *orchestration* record, not
    part of the provider-agnostic lingua franca the Cognitive and Tool tiers speak.

    ``cache_read_tokens`` / ``cache_creation_tokens`` stay 0 on providers whose ``Usage``
    carries no cache fields — they are read with ``getattr`` so this works before and after
    prompt-cache accounting lands in ``types.Usage``.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    steps: int = 0
    tool_calls: int = 0
    duration_s: float = 0.0
    compactions: int = 0
    continuations: int = 0

    def add_usage(self, usage: Usage) -> None:
        """Fold one model call's usage in, tolerating a ``Usage`` without cache fields."""
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cost_usd += usage.cost_usd
        self.cache_read_tokens += int(getattr(usage, "cache_read_tokens", 0) or 0)
        self.cache_creation_tokens += int(getattr(usage, "cache_creation_tokens", 0) or 0)


class AgentState(BaseModel):
    """Mutable state for one agent session."""

    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    phase: AgentPhase = AgentPhase.INIT
    messages: list[Message] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    #: The turn that just finished. None before the first turn of a session.
    last_turn: TurnSummary | None = None

    def add_message(self, message: Message) -> None:
        self.messages.append(message)

    def record_step(self, step: Step) -> None:
        self.steps.append(step)
        self.usage = self.usage + step.usage

    @property
    def step_count(self) -> int:
        return len(self.steps)


__all__ = ["AgentState", "TurnSummary"]
