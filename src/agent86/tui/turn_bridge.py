"""The load-bearing worker/app bridge for the TUI (Textual-app-independent).

Mirrors the proven pattern in ``agent86.ui.repl._run_turn_rich`` — a background thread
drives the harness's synchronous ``run_turn`` generator and crosses back to the app via
Textual ``Message`` posting; tool approval blocks the worker thread on a
``threading.Event`` until the app resolves it. This module imports no Textual widget or
App classes (only ``Message`` subclasses), so it is unit-testable without a running app.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from agent86.tui.messages import ApprovalRequest, ToolAnnounce, TurnDelta, TurnDone, TurnError
from agent86.ui.repl import _tool_label

Poster = Callable[[object], object]  # app.post_message (thread-safe); returns bool in Textual


def make_approval_cb(post: Poster) -> Callable[[str, str], bool]:
    """Build a ``harness.gate.prompt`` callback that blocks the WORKER thread only."""

    def approval_cb(tool_name: str, preview: str) -> bool:
        event = threading.Event()
        box: dict[str, bool] = {}
        post(ApprovalRequest(tool_name, preview, event, box))
        event.wait()  # blocks the WORKER thread only
        return box.get("ok", False)

    return approval_cb


def run_turn_worker(harness, line: str, state, post: Poster) -> None:
    """Runs on a Textual thread worker. `post` is App.post_message (thread-safe)."""
    harness.gate.prompt = make_approval_cb(post)
    try:
        for delta in harness.run_turn(line, state):
            text = getattr(delta, "text", None)
            if not text:
                continue
            label = _tool_label(text)
            if label:
                post(ToolAnnounce(label, text))
            else:
                post(TurnDelta(text))
        post(TurnDone())
    except BaseException as exc:  # deliver any error to the main thread
        post(TurnError(exc))


__all__ = ["run_turn_worker", "make_approval_cb"]
