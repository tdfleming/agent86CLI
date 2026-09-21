"""Message subclasses that cross the worker-thread -> Textual-app boundary.

These are deliberately independent of any concrete `App`/`Widget` — `turn_bridge.py`
posts them from a background thread, and `Agent86App` (a later plan) handles them on
the main thread.
"""

from __future__ import annotations

import threading

from textual.message import Message


class TurnDelta(Message):
    """A streamed text delta from the model (not a tool-announce line)."""

    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class ToolAnnounce(Message):
    """A `[tool] name(...)` delta line, pre-labeled for the status footer.

    `name`/`args`/`args_preview` are the structured half the transcript's collapsible tool
    block needs: `args` is the FULL argument dict recovered from the session state (the delta
    line only carries a 160-char preview), `args_preview` the preview text as a fallback. Both
    default to the zero value so older callers — and tests — can still post `(label, text)`.
    """

    def __init__(
        self,
        label: str,
        text: str,
        name: str = "",
        args: dict | None = None,
        args_preview: str = "",
        call_id: str = "",
    ) -> None:
        self.label = label  # e.g. "running write_file" (from _tool_label)
        self.text = text  # the raw "[tool] ..." line for the transcript
        self.name = name
        self.args = args
        self.args_preview = args_preview
        self.call_id = call_id
        super().__init__()


class ToolOutcome(Message):
    """A `[tool] name -> summary` delta line, with the full result text when it can be found.

    Named `ToolOutcome`, not `ToolResult`, so it can never be confused with
    `agent86.types.ToolResult` — this is a UI message, not the harness's own result type.
    """

    def __init__(
        self,
        name: str,
        summary: str,
        result: str = "",
        ok: bool = True,
        text: str = "",
    ) -> None:
        self.name = name
        self.summary = summary  # the one-line summary the loop already computed
        self.result = result  # full observed content, when the state had it
        self.ok = ok
        self.text = text  # the raw delta line
        super().__init__()


class TurnNotice(Message):
    """A harness notice delta — context compaction, continuation — not model speech."""

    def __init__(self, text: str) -> None:
        self.text = text  # already stripped; the app renders it dim and escaped
        super().__init__()


class ApprovalRequest(Message):
    """A tool-approval prompt; the worker blocks on `event` until the app resolves it."""

    def __init__(self, tool_name: str, preview: str, event: threading.Event, box: dict) -> None:
        self.tool_name = tool_name
        self.preview = preview
        self.event = event  # worker blocks on this until the modal resolves
        self.box = box  # {"ok": bool} set by the app before event.set()
        super().__init__()


class TurnDone(Message):
    """The turn completed successfully."""


class TurnError(Message):
    """The turn raised an exception."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        super().__init__()


class CatalogReady(Message):
    """A provider's live model catalog finished loading (or failed).

    `purpose` says who asked: "manager" (the /config model chain), "model_picker" (the /model
    quick switch, enriched per Phase 2 D-12), or "model_fallback" (resolving a typed bare /model
    ref). `entries` is empty when `error` is set — the caller falls back to free-text entry
    (D-01), never a dead end.
    """

    def __init__(
        self,
        provider: str,
        entries: list[tuple[str, str]],
        error: str | None,
        purpose: str,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.entries = entries
        self.error = error
        self.purpose = purpose


__all__ = [
    "TurnDelta",
    "TurnNotice",
    "ToolAnnounce",
    "ToolOutcome",
    "ApprovalRequest",
    "TurnDone",
    "TurnError",
    "CatalogReady",
]
