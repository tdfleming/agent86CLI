"""Supervisor orchestrator (multi-agent topology).

The programmatic counterpart to the model-driven ``delegate`` tool: fan a set of role-scoped
tasks out to sub-agents and collect their results as correlated :class:`AgentMessage`
envelopes on the bus. Sub-agents run sequentially in-process (the sync harness); the envelope
protocol keeps the topology explicit and auditable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent86.agents.broker import MessageBus
from agent86.agents.envelope import AgentMessage, Intent
from agent86.agents.subagent import SubAgent

if TYPE_CHECKING:
    from agent86.orchestration.loop import Harness


class SupervisorOrchestrator:
    def __init__(self, harness: Harness, bus: MessageBus | None = None):
        self.h = harness
        self.bus = bus or MessageBus()

    def fan_out(
        self, tasks: list[tuple[str, str]], supervisor: str = "supervisor"
    ) -> list[AgentMessage]:
        """Run each (role, task) on a sub-agent; return their reply envelopes in order."""
        replies: list[AgentMessage] = []
        for role, task in tasks:
            request = AgentMessage(
                sender=supervisor, recipient=role, intent=Intent.REQUEST, content=task
            )
            self.bus.send(request)
            try:
                result = SubAgent(self.h, role, depth=1).run(task)
                reply = request.reply(result, intent=Intent.RESPONSE)
            except Exception as exc:  # a failing sub-agent must not sink the whole fan-out
                reply = request.reply(f"{type(exc).__name__}: {exc}", intent=Intent.ERROR)
            self.bus.send(reply)
            replies.append(reply)
        return replies


__all__ = ["SupervisorOrchestrator"]
