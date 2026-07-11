"""Agent state (Tier 2).

The finite-state-machine record the orchestrator threads through the loop: conversation
history, per-step trace, cumulative usage, and the current phase. Phase 2 keeps this in
memory; Phase 4 persists it to SQLite for cross-session continuity.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from agent86.types import AgentPhase, Message, Step, Usage


class AgentState(BaseModel):
    """Mutable state for one agent session."""

    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    phase: AgentPhase = AgentPhase.INIT
    messages: list[Message] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)

    def add_message(self, message: Message) -> None:
        self.messages.append(message)

    def record_step(self, step: Step) -> None:
        self.steps.append(step)
        self.usage = self.usage + step.usage

    @property
    def step_count(self) -> int:
        return len(self.steps)


__all__ = ["AgentState"]
