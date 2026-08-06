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
    """A `[tool] name(...)` delta line, pre-labeled for the status footer."""

    def __init__(self, label: str, text: str) -> None:
        self.label = label  # e.g. "running write_file" (from _tool_label)
        self.text = text  # the raw "[tool] ..." line for the transcript
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

    `purpose` says who asked: "manager" (the /config model chain) or "model_picker" (the /model
    quick switch, enriched per Phase 2 D-12). `entries` is empty when `error` is set — the caller
    falls back to free-text entry (D-01), never a dead end.
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
    "ToolAnnounce",
    "ApprovalRequest",
    "TurnDone",
    "TurnError",
    "CatalogReady",
]
