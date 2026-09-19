"""The load-bearing worker/app bridge for the TUI (Textual-app-independent).

A background thread drives the harness's synchronous ``run_turn`` generator and crosses back
to the app via Textual ``Message`` posting; tool approval blocks the worker thread on a
``threading.Event`` until the app resolves it. This module imports no Textual widget or
App classes (only ``Message`` subclasses), so it is unit-testable without a running app.

The ``closing`` event is the shutdown seam: the app sets it on quit, and any approval wait
gives up promptly and denies, so a worker parked on an unanswered modal can never keep the
interpreter alive at exit.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from agent86.tui.messages import ApprovalRequest, ToolAnnounce, TurnDelta, TurnDone, TurnError
from agent86.ui.repl import _tool_label

Poster = Callable[[object], object]  # app.post_message (thread-safe); returns bool in Textual

#: How often a blocked approval re-checks the closing flag. Short enough that quitting feels
#: instant, long enough that the wait is effectively free.
APPROVAL_POLL_SECONDS = 0.25


def make_approval_cb(
    post: Poster, closing: threading.Event | None = None
) -> Callable[[str, str], bool]:
    """Build a ``harness.gate.prompt`` callback that blocks the WORKER thread only.

    The wait is polled rather than unbounded: a bare ``event.wait()`` leaves the worker parked
    forever if the app goes away with a modal still open, and a non-daemon thread in that state
    hangs interpreter exit. When ``closing`` is set the answer is DENY — the safe default for
    an approval nobody is there to give.
    """

    def approval_cb(tool_name: str, preview: str) -> bool:
        event = threading.Event()
        box: dict[str, bool] = {}
        post(ApprovalRequest(tool_name, preview, event, box))
        while not event.wait(APPROVAL_POLL_SECONDS):  # blocks the WORKER thread only
            if closing is not None and closing.is_set():
                return False
        return box.get("ok", False)

    return approval_cb


def run_turn_worker(
    harness, line: str, state, post: Poster, closing: threading.Event | None = None
) -> None:
    """Runs on a Textual thread worker. `post` is App.post_message (thread-safe)."""
    harness.gate.prompt = make_approval_cb(post, closing)
    try:
        for delta in harness.run_turn(line, state):
            if closing is not None and closing.is_set():
                # The app is going away; stop pumping messages at a screen that is unmounting
                # and let the harness close out the turn on its own terms.
                cancel = getattr(harness, "cancel", None)
                if cancel is not None:
                    cancel()
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


__all__ = ["run_turn_worker", "make_approval_cb", "APPROVAL_POLL_SECONDS"]
