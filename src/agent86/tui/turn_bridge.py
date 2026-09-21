"""The load-bearing worker/app bridge for the TUI (Textual-app-independent).

A background thread drives the harness's synchronous ``run_turn`` generator and crosses back
to the app via Textual ``Message`` posting; tool approval blocks the worker thread on a
``threading.Event`` until the app resolves it. This module imports no Textual widget or
App classes (only ``Message`` subclasses), so it is unit-testable without a running app.

The ``closing`` event is the shutdown seam: the app sets it on quit, and any approval wait
gives up promptly and denies, so a worker parked on an unanswered modal can never keep the
interpreter alive at exit.

Tool deltas are *classified and enriched* here rather than in the app: the loop yields tool
activity as plain text (``[tool] name({...})`` / ``[tool] name -> summary``) with the arguments
truncated to 160 characters and the result reduced to its first line. The full argument dict
and the full observed content are both already in ``state`` by the time those lines are
yielded, so the bridge looks them up and posts them alongside — that is what lets the
transcript's collapsible tool block expand to something worth reading.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable

from textual.message import Message

from agent86.tui.messages import (
    ApprovalRequest,
    ToolAnnounce,
    ToolOutcome,
    TurnDelta,
    TurnDone,
    TurnError,
    TurnNotice,
)
from agent86.ui.repl import _tool_label, notice_text

#: ``App.post_message`` (thread-safe). Accepts a Textual ``Message``; the return value is
#: ignored here, so it is typed ``object`` — Textual's own ``bool`` return satisfies that,
#: and a test double may return anything.
Poster = Callable[[Message], object]

#: How often a blocked approval re-checks the closing flag. Short enough that quitting feels
#: instant, long enough that the wait is effectively free.
APPROVAL_POLL_SECONDS = 0.25

_TOOL_PREFIX = "[tool] "
_RESULT_SEP = " -> "


def tool_result_parts(text: str) -> tuple[str, str] | None:
    """``(name, summary)`` for a ``[tool] name -> summary`` line, else None.

    Deliberately strict about the shape — a tool NAME never contains whitespace — so model
    prose that happens to mention an arrow can't be mistaken for harness output.
    """
    stripped = text.strip()
    if not stripped.startswith(_TOOL_PREFIX) or _RESULT_SEP not in stripped:
        return None
    body = stripped[len(_TOOL_PREFIX) :]
    name, _, summary = body.partition(_RESULT_SEP)
    if not name or name.split() != [name]:
        return None
    return name, summary.strip()


def announce_preview(text: str) -> str:
    """The ``{...}`` argument preview out of a ``[tool] name({...})`` line (may be truncated)."""
    stripped = text.strip()
    if not stripped.startswith(_TOOL_PREFIX) or "(" not in stripped:
        return ""
    inner = stripped[len(_TOOL_PREFIX) :].partition("(")[2]
    return inner[:-1] if inner.endswith(")") else inner


def _role_of(message: object) -> str:
    role = getattr(message, "role", None)
    return str(getattr(role, "value", role) or "")


def _latest_tool_calls(state: object) -> list:
    """The tool_calls of the most recent assistant message, or []."""
    messages = getattr(state, "messages", None) or []
    for message in reversed(messages):
        calls = getattr(message, "tool_calls", None)
        if calls:
            return list(calls)
        if _role_of(message) == "assistant":
            return []
    return []


def _last_tool_content(state: object, name: str) -> str:
    """The content of the most recent TOOL message for ``name`` — the full, un-summarised text.

    The loop appends the TOOL message *before* it yields the ``-> summary`` delta, so the
    most recent match is always this call's own observation.
    """
    messages = getattr(state, "messages", None) or []
    for message in reversed(messages):
        if _role_of(message) == "tool" and getattr(message, "name", None) == name:
            return str(getattr(message, "content", "") or "")
    return ""


def _fallback_args(preview: str) -> dict | None:
    """Parse the delta line's own preview as a last resort (it may be truncated)."""
    try:
        parsed = json.loads(preview)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


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


def _announce(post: Poster, state: object, text: str, label: str, batch_index: int) -> None:
    """Post one enriched ToolAnnounce for a ``[tool] name({...})`` line."""
    name = text.split(_TOOL_PREFIX, 1)[1].split("(", 1)[0].strip()
    preview = announce_preview(text)
    calls = _latest_tool_calls(state)
    call = None
    # A batch is announced in call order, so the nth announce is the nth call — verified by
    # name, with a by-name search as the fallback if anything ever reorders.
    if batch_index < len(calls) and getattr(calls[batch_index], "name", None) == name:
        call = calls[batch_index]
    else:
        call = next((c for c in calls if getattr(c, "name", None) == name), None)
    args = getattr(call, "arguments", None) if call is not None else None
    if not isinstance(args, dict):
        args = _fallback_args(preview)
    post(
        ToolAnnounce(
            label,
            text,
            name=name,
            args=args,
            args_preview=preview,
            call_id=str(getattr(call, "id", "") or ""),
        )
    )


def run_turn_worker(
    harness, line: str, state, post: Poster, closing: threading.Event | None = None
) -> None:
    """Runs on a Textual thread worker. `post` is App.post_message (thread-safe)."""
    harness.gate.prompt = make_approval_cb(post, closing)
    batch_index = 0
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
            outcome = None if label else tool_result_parts(text)
            notice = None if (label or outcome) else notice_text(text)
            if label:
                _announce(post, state, text, label, batch_index)
                batch_index += 1
                continue
            batch_index = 0
            if outcome is not None:
                name, summary = outcome
                post(
                    ToolOutcome(
                        name,
                        summary,
                        result=_last_tool_content(state, name),
                        ok=not summary.startswith("error:"),
                        text=text.strip(),
                    )
                )
            elif notice is not None:
                post(TurnNotice(notice))
            else:
                post(TurnDelta(text))
        post(TurnDone())
    except BaseException as exc:  # deliver any error to the main thread
        post(TurnError(exc))


__all__ = [
    "APPROVAL_POLL_SECONDS",
    "announce_preview",
    "make_approval_cb",
    "run_turn_worker",
    "tool_result_parts",
]
