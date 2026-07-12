"""In-process message broker (the harness as communication broker).

A simple synchronous pub/sub bus: agents post :class:`AgentMessage` envelopes addressed to a
recipient, and a recipient drains its inbox. This is the local-topology substrate the
supervisor orchestrator runs on; a networked broker (Redis/NATS) would slot in behind the
same interface for distributed MAS (a Phase-9+ concern).
"""

from __future__ import annotations

from collections import defaultdict, deque

from agent86.agents.envelope import AgentMessage


class MessageBus:
    def __init__(self) -> None:
        self._inboxes: dict[str, deque[AgentMessage]] = defaultdict(deque)
        self._log: list[AgentMessage] = []

    def send(self, message: AgentMessage) -> None:
        self._inboxes[message.recipient].append(message)
        self._log.append(message)

    def receive(self, recipient: str) -> AgentMessage | None:
        inbox = self._inboxes.get(recipient)
        return inbox.popleft() if inbox else None

    def drain(self, recipient: str) -> list[AgentMessage]:
        inbox = self._inboxes.get(recipient)
        if not inbox:
            return []
        out = list(inbox)
        inbox.clear()
        return out

    def pending(self, recipient: str) -> int:
        return len(self._inboxes.get(recipient, ()))

    @property
    def history(self) -> list[AgentMessage]:
        return list(self._log)


__all__ = ["MessageBus"]
