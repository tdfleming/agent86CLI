"""Human-in-the-loop approval gate (Tier 5, Pillar 4).

Before any side-effecting tool runs, the gate decides based on the configured approval
mode. Read-only tools always pass. Side-effecting tools pass automatically under ``auto``,
are blocked under ``deny``, and prompt the user under ``ask`` (via an injected callback so
this module stays UI-agnostic). Non-interactive callers that leave no callback get a safe
default of *decline*.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent86.tools.base import Tool
from agent86.types import ApprovalMode, ToolCall

if TYPE_CHECKING:
    from agent86.tools.base import ToolContext

logger = logging.getLogger(__name__)

# (tool_name, argument_preview) -> approved?
ApprovalPrompt = Callable[[str, str], bool]

#: The one-line summary is capped here; ``ApprovalPreview.detail`` carries the full story.
SUMMARY_LIMIT = 300


class ApprovalPreview(str):
    """The one-line summary a prompt shows, carrying the full ``detail`` alongside it.

    A ``str`` subclass on purpose: ``ApprovalPrompt`` is ``(tool_name, preview) -> bool`` and
    is implemented by the TUI bridge, the plain loop, and every test double. Making the second
    argument *richer* rather than *different* means each of those keeps working untouched —
    a caller that only knows about strings still prints the summary; one that knows about the
    detail (``getattr(preview, "detail", None)``) renders the diff.
    """

    detail: str | None
    lexer: str | None
    tool: str

    def __new__(
        cls,
        summary: str,
        detail: str | None = None,
        lexer: str | None = None,
        tool: str = "",
    ) -> ApprovalPreview:
        obj = super().__new__(cls, summary)
        obj.detail = detail or None
        obj.lexer = lexer
        obj.tool = tool
        return obj


@dataclass
class ApprovalDecision:
    approved: bool
    reason: str


class ApprovalGate:
    """Decides whether a side-effecting call may run, asking a human when the mode says so.

    ``context`` is optional and purely for previews: ``Tool.preview`` resolves paths through
    the sandbox policy when a context is available, and falls back to the CWD when it is not,
    so the gate stays constructible long before a ``ToolContext`` exists.
    """

    def __init__(
        self,
        mode: ApprovalMode,
        prompt: ApprovalPrompt | None = None,
        context: ToolContext | None = None,
    ):
        self.mode = mode
        self.prompt = prompt
        self.context = context

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
        approved = self.prompt(tool.name, self.preview(tool, call))
        return ApprovalDecision(approved, "approved by user" if approved else "declined by user")

    def preview(self, tool: Tool, call: ToolCall) -> ApprovalPreview:
        """Summary + detail for ``call`` — what the user is being asked to approve."""
        return build_preview(tool, call, self.context)


def build_preview(
    tool: Tool, call: ToolCall, context: ToolContext | None = None
) -> ApprovalPreview:
    """Build the approval payload: a one-line argument summary plus the tool's own detail."""
    detail: str | None = None
    try:
        detail = tool.preview(call.arguments, context)
    except Exception:  # a broken preview must never block the prompt
        logger.debug("preview failed for tool %r", tool.name, exc_info=True)
    return ApprovalPreview(
        _summary(call.arguments), detail, getattr(tool, "preview_lexer", None), tool.name
    )


def _summary(arguments: dict) -> str:
    try:
        text = json.dumps(arguments, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(arguments)
    return text if len(text) <= SUMMARY_LIMIT else text[:SUMMARY_LIMIT] + " ..."


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


__all__ = [
    "ApprovalGate",
    "ApprovalDecision",
    "ApprovalPrompt",
    "ApprovalPreview",
    "build_preview",
    "cycle_mode",
    "parse_mode",
]
