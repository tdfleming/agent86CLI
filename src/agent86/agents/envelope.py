"""The agent message envelope.

The book's answer to the "Babel problem": agents never exchange raw natural language as a
wire protocol. Every inter-agent message is a structured envelope with an explicit sender,
recipient, intent, and correlation id, so the harness can route, match, and audit it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class Intent(StrEnum):
    REQUEST = "request"  # please perform this task
    RESPONSE = "response"  # here is the result
    INFORM = "inform"  # fyi, no reply expected
    ERROR = "error"  # the task failed


@dataclass
class AgentMessage:
    sender: str
    recipient: str
    intent: Intent
    content: str
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def reply(self, content: str, intent: Intent = Intent.RESPONSE) -> AgentMessage:
        """Build a correlated reply from recipient back to sender."""
        return AgentMessage(
            sender=self.recipient,
            recipient=self.sender,
            intent=intent,
            content=content,
            correlation_id=self.correlation_id,
        )


__all__ = ["AgentMessage", "Intent"]
