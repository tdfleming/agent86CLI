"""Collapsible tool-call blocks for the transcript.

A tool call used to cost two flat lines in the scrollback — ``[tool] name({...})`` when it
started and ``[tool] name -> summary`` when it finished — with the arguments truncated at 160
characters and the result reduced to its first line. Ten calls in a turn buried the answer.

A :class:`ToolBlockEntry` is one call, collapsed to one dim line::

    ▸ write_file({"path": "out.txt", …}) → wrote 12 bytes

and expanded (``ctrl+o`` / ``ctrl+shift+o``) to the full arguments as pretty JSON and the full
result text, capped at :data:`RESULT_LINE_LIMIT` lines::

    ▾ write_file({"path": "out.txt", …}) → wrote 12 bytes
      args:
        {
          "path": "out.txt",
          "content": "hello"
        }
      result:
        wrote 12 bytes

Why an entry and not a Textual ``Collapsible``: the transcript is a ``RichLog``, which renders
to strips and cannot host interactive children. Migrating it to a ``VerticalScroll`` of widgets
would have broken every surface that queries ``#transcript`` as a ``RichLog`` (and cost the
append-only streaming path), so the block is a *renderable* that changes shape, and the app
re-renders the log when it does. Toggling is therefore keyboard-driven, not click-driven.

Every string here is model- or tool-authored and is rendered through ``rich.text.Text``, which
is never markup-parsed — a result containing ``[/x]`` can neither raise nor disappear.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Group, RenderableType
from rich.text import Text

from agent86.tui.widgets.transcript import TranscriptEntry, cap_lines, ellipsize, pretty_json

#: How many lines of a tool result an expanded block shows before truncating.
RESULT_LINE_LIMIT = 200

#: How much of the argument JSON fits on the collapsed header line.
ARG_PREVIEW_LIMIT = 72

#: How much of the result summary fits on the collapsed header line.
SUMMARY_LIMIT = 100

COLLAPSED_MARKER = "▸"
EXPANDED_MARKER = "▾"

#: Shown while the call is in flight (the block is written when its result lands, so this is
#: only ever seen for a call the turn ended without observing).
PENDING_SUMMARY = "(no result)"


@dataclass
class ToolBlockEntry(TranscriptEntry):
    """One tool call: header always, arguments and result only when expanded."""

    name: str = ""
    args: dict[str, Any] | None = None
    args_preview: str = ""
    summary: str = ""
    result: str = ""
    ok: bool = True
    call_id: str = ""
    expanded: bool = False

    # ---- state ---------------------------------------------------------- #

    def toggle(self) -> bool:
        """Flip expanded/collapsed; returns the new state."""
        self.expanded = not self.expanded
        return self.expanded

    def complete(self, summary: str, result: str = "", ok: bool = True) -> None:
        """Attach the outcome of the call."""
        self.summary = summary
        self.result = result
        self.ok = ok

    # ---- rendering ------------------------------------------------------ #

    @property
    def _style(self) -> str:
        return "dim red" if not self.ok else "dim"

    def header_line(self) -> str:
        marker = EXPANDED_MARKER if self.expanded else COLLAPSED_MARKER
        args = ellipsize(self.args_preview, ARG_PREVIEW_LIMIT)
        summary = ellipsize(self.summary or PENDING_SUMMARY, SUMMARY_LIMIT)
        return f"{marker} {self.name}({args}) → {summary}"

    def body_lines(self) -> list[str]:
        """The expanded detail: full arguments, then the (capped) full result."""
        lines = ["  args:"]
        args_text = pretty_json(self.args, self.args_preview) or "{}"
        lines += [f"    {line}" for line in args_text.splitlines() or [""]]
        body = (self.result or self.summary or "").rstrip()
        lines.append("  result:")
        if body:
            lines += [f"    {line}" for line in cap_lines(body, RESULT_LINE_LIMIT).splitlines()]
        else:
            lines.append("    (no output)")
        return lines

    def render(self) -> RenderableType:
        # no_wrap + ellipsis: the collapsed form is ONE line at any terminal width. The full
        # text is one keypress away, so cropping it here costs nothing and keeps a batch of
        # tool calls from burying the answer under wrapped argument dumps.
        header = Text(
            self.header_line(), style=self._style, no_wrap=True, overflow="ellipsis"
        )
        if not self.expanded:
            return header
        return Group(header, Text("\n".join(self.body_lines()), style="dim"))


__all__ = [
    "ARG_PREVIEW_LIMIT",
    "COLLAPSED_MARKER",
    "EXPANDED_MARKER",
    "PENDING_SUMMARY",
    "RESULT_LINE_LIMIT",
    "SUMMARY_LIMIT",
    "ToolBlockEntry",
]
