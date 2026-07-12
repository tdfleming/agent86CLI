"""Human-in-the-loop approval gate (Tier 5, Pillar 4).

Before any side-effecting tool runs, the gate decides based on the configured approval
mode. Read-only tools always pass. Side-effecting tools pass automatically under ``auto``,
are blocked under ``deny``, and prompt the user under ``ask`` (via an injected callback so
this module stays UI-agnostic). Non-interactive callers that leave no callback get a safe
default of *decline*.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from agent86.tools.base import Tool
from agent86.types import ApprovalMode, ToolCall

# (tool_name, argument_preview) -> approved?
ApprovalPrompt = Callable[[str, str], bool]


@dataclass
class ApprovalDecision:
    approved: bool
    reason: str


class ApprovalGate:
    def __init__(self, mode: ApprovalMode, prompt: ApprovalPrompt | None = None):
        self.mode = mode
        self.prompt = prompt

    def decide(self, tool: Tool, call: ToolCall) -> ApprovalDecision:
        if not tool.side_effecting:
            return ApprovalDecision(True, "read-only")
        if self.mode == ApprovalMode.AUTO:
            return ApprovalDecision(True, "auto-approved")
        if self.mode == ApprovalMode.DENY:
            return ApprovalDecision(False, "blocked by approval policy (deny)")
        # ASK
        if self.prompt is None:
            return ApprovalDecision(False, "approval required but no prompt available")
        approved = self.prompt(tool.name, _preview(call.arguments))
        return ApprovalDecision(approved, "approved by user" if approved else "declined by user")


def _preview(arguments: dict) -> str:
    try:
        text = json.dumps(arguments, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(arguments)
    return text if len(text) <= 300 else text[:300] + " ..."


# Order the approval-mode hotkey cycles through.
_CYCLE = (ApprovalMode.ASK, ApprovalMode.AUTO, ApprovalMode.DENY)


def cycle_mode(mode: ApprovalMode) -> ApprovalMode:
    """Return the next approval mode in the cycle (ask -> auto -> deny -> ask)."""
    try:
        idx = _CYCLE.index(mode)
    except ValueError:
        return ApprovalMode.ASK
    return _CYCLE[(idx + 1) % len(_CYCLE)]


def parse_mode(text: str) -> ApprovalMode | None:
    """Parse a mode name from a ``/mode`` command, or None if unrecognized."""
    try:
        return ApprovalMode(text.strip().lower())
    except ValueError:
        return None


__all__ = ["ApprovalGate", "ApprovalDecision", "ApprovalPrompt", "cycle_mode", "parse_mode"]
