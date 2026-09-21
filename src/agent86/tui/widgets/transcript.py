"""Transcript entries: what the TUI scrollback is made of, and how each piece renders.

The transcript widget itself is still a ``RichLog`` (append-only, cheap to stream into, and
the thing every existing test queries). What changed in v0.9 is that the app also keeps the
*model* of the scrollback — an ordered list of :class:`TranscriptEntry` — beside it, so an
entry can change its mind about how it renders after it was first written:

* an assistant reply streams in as plain escaped text and is re-rendered as
  ``rich.markdown.Markdown`` once it is complete (headings, lists, tables, fenced code);
* a tool block renders as one dim line collapsed and as a full argument/result dump expanded.

Whenever an entry's rendering changes, the app clears the ``RichLog`` and writes every entry
again (``Agent86App._rerender``). That is O(entries) — deliberately paid only on a reply that
actually contains Markdown and on an explicit expand/collapse, never per streamed delta.

Nothing here imports Textual: these are Rich renderables, unit-testable without an app.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.text import Text

#: Leads every assistant reply in the transcript (harness-owned styling, never model text).
AGENT_LABEL = "agent86"

#: Pygments themes handed to ``Markdown(code_theme=...)``. Picked from the app's own theme so
#: a fenced code block doesn't render light-on-light (or dark-on-dark).
DARK_CODE_THEME = "monokai"
LIGHT_CODE_THEME = "default"

# Markdown structure worth re-rendering for. Plain prose renders the same either way, so a
# reply with none of these markers keeps the lines already streamed into the log and skips the
# re-render entirely — the common case for short answers.
_MD_BLOCK = re.compile(r"^\s{0,3}(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>\s|```|~~~|\||-{3,}\s*$)", re.M)
_MD_INLINE = re.compile(r"`[^`\n]+`|\*\*\S|\[[^\]\n]+\]\([^)\n]*\)")


def looks_like_markdown(text: str) -> bool:
    """Does ``text`` contain Markdown structure that would render differently?"""
    if not text.strip():
        return False
    return bool(_MD_BLOCK.search(text) or _MD_INLINE.search(text))


def label() -> Text:
    """The ``agent86`` reply label, as a renderable (never markup-parsed)."""
    return Text(AGENT_LABEL, style="bold cyan")


def render_reply(
    text: str,
    *,
    markdown: bool = True,
    code_theme: str = DARK_CODE_THEME,
    labelled: bool = True,
) -> RenderableType:
    """Render one assistant reply.

    ``Markdown`` does NOT parse console markup, so model text like ``[/weird]`` can neither
    raise ``MarkupError`` nor vanish into a style tag. The plain branch escapes by construction
    (``Text`` is never markup-parsed either), so both branches are safe for untrusted text.
    """
    if markdown and text.strip():
        body: RenderableType = Markdown(text, code_theme=code_theme, hyperlinks=False)
        return Group(label(), body) if labelled else body
    plain = Text(text.rstrip("\n"))
    if not labelled:
        return plain
    return Text.assemble((f"{AGENT_LABEL} ", "bold cyan"), plain)


def pretty_json(value: Any, fallback: str = "") -> str:
    """Pretty-print tool arguments; fall back to whatever preview text we were given."""
    if value is None:
        return fallback
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - default=str swallows almost all
        return fallback or str(value)


def compact_json(value: Any) -> str:
    """One-line JSON, for the collapsed header of a rebuilt tool block."""
    if not value:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - default=str swallows almost all
        return str(value)


def cap_lines(text: str, limit: int) -> str:
    """First ``limit`` lines of ``text``, with a ``… truncated`` tail when there are more."""
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    kept = lines[:limit]
    kept.append(f"… truncated ({len(lines) - limit} more lines)")
    return "\n".join(kept)


def ellipsize(text: str, limit: int) -> str:
    """One-line preview of ``text``, collapsed to a single line and capped at ``limit``."""
    single = " ".join(text.split())
    return single if len(single) <= limit else single[: limit - 1] + "…"


class TranscriptEntry:
    """One addressable thing in the scrollback. Subclasses decide how they render."""

    def render(self) -> RenderableType:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass
class RawEntry(TranscriptEntry):
    """A harness-owned renderable (a command result, a notice, an error) — rendered as given."""

    renderable: Any

    def render(self) -> RenderableType:
        return self.renderable


@dataclass
class ReplyEntry(TranscriptEntry):
    """One assistant reply, from the first delta until the turn (or a tool call) ends.

    ``text`` accumulates the EXACT stream, independent of how it was chunked into the live
    ``#stream`` widget, so the finished reply can be re-rendered as one Markdown document.
    """

    text: str = ""
    markdown: bool = True
    code_theme: str = DARK_CODE_THEME
    final: bool = False

    def render(self) -> RenderableType:
        # Mid-stream the reply is deliberately plain: an unterminated fence or half a table
        # would render as garbage, and re-parsing the document per delta is the cost this
        # design exists to avoid.
        return render_reply(
            self.text, markdown=self.markdown and self.final, code_theme=self.code_theme
        )


@dataclass
class UserEntry(TranscriptEntry):
    """The user's own prompt echo — always plain and escaped, never Markdown."""

    text: str = ""

    def render(self) -> RenderableType:
        return Text.assemble(("> ", "bold"), (self.text, "bold"))


@dataclass
class NoticeEntry(TranscriptEntry):
    """A harness notice (``[compacted …]`` / ``[continuing …]``) — dim, escaped, never speech."""

    text: str = ""

    def render(self) -> RenderableType:
        return Text(self.text, style="dim")


@dataclass
class ErrorEntry(TranscriptEntry):
    """A failed turn: exception type, message, and where to go looking."""

    exc_type: str = "Error"
    message: str = ""
    hint: str = ""

    def render(self) -> RenderableType:
        head = Text.assemble(
            ("error: ", "bold red"), (self.exc_type, "bold red"), (f": {self.message}", "red")
        )
        if not self.hint:
            return head
        return Group(head, Text(self.hint, style="dim"))


__all__ = [
    "AGENT_LABEL",
    "DARK_CODE_THEME",
    "LIGHT_CODE_THEME",
    "ErrorEntry",
    "NoticeEntry",
    "RawEntry",
    "ReplyEntry",
    "TranscriptEntry",
    "UserEntry",
    "cap_lines",
    "compact_json",
    "ellipsize",
    "label",
    "looks_like_markdown",
    "pretty_json",
    "render_reply",
]
