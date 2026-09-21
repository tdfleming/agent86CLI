"""Unit tests for the worker/app bridge, exercised without a running Textual app."""

from __future__ import annotations

import threading
import time

from agent86.tui.messages import (
    ApprovalRequest,
    ToolAnnounce,
    ToolOutcome,
    TurnDelta,
    TurnDone,
    TurnError,
    TurnNotice,
)
from agent86.tui.turn_bridge import announce_preview, run_turn_worker, tool_result_parts


def _poll_until(predicate, timeout: float = 5.0, interval: float = 0.01) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition not met within timeout")


def test_streams_deltas_in_order(fake_harness, fake_state):
    posts: list[object] = []
    thread = threading.Thread(
        target=run_turn_worker,
        args=(fake_harness, "go", fake_state, posts.append),
        daemon=True,
    )
    thread.start()

    _poll_until(lambda: any(isinstance(m, ApprovalRequest) for m in posts))
    approval = next(m for m in posts if isinstance(m, ApprovalRequest))
    approval.box["ok"] = True
    approval.event.set()

    thread.join(timeout=5)
    assert not thread.is_alive()

    kinds = [type(m) for m in posts]
    assert kinds == [TurnDelta, ToolAnnounce, ApprovalRequest, ToolOutcome, TurnDone]
    announce = posts[1]
    assert isinstance(announce, ToolAnnounce)
    assert announce.name == "write_file"
    assert announce.args_preview == '{"path": "x"}'
    outcome = posts[3]
    assert isinstance(outcome, ToolOutcome)
    assert (outcome.name, outcome.summary, outcome.ok) == ("write_file", "ok", True)
    assert "write_file -> ok" in outcome.text


def test_approval_blocks_until_resolved(fake_harness, fake_state):
    posts: list[object] = []
    thread = threading.Thread(
        target=run_turn_worker,
        args=(fake_harness, "go", fake_state, posts.append),
        daemon=True,
    )
    thread.start()

    _poll_until(lambda: any(isinstance(m, ApprovalRequest) for m in posts))
    # Give the worker a moment to actually reach event.wait() and confirm it's still blocked.
    time.sleep(0.05)
    assert thread.is_alive()

    approval = next(m for m in posts if isinstance(m, ApprovalRequest))
    approval.box["ok"] = False
    approval.event.set()

    thread.join(timeout=5)
    assert not thread.is_alive()


def test_error_becomes_TurnError(raising_harness, fake_state):
    harness = raising_harness(RuntimeError("boom"))
    posts: list[object] = []
    run_turn_worker(harness, "go", fake_state, posts.append)

    assert isinstance(posts[-1], TurnError)
    assert isinstance(posts[-1].error, RuntimeError)
    assert not any(isinstance(m, TurnDone) for m in posts)


# ---- shutdown: a blocked approval must never outlive the app ---------------- #


def test_closing_flag_resolves_a_pending_approval_as_denied(fake_harness, fake_state):
    """A bare `event.wait()` parked the worker forever when the app quit with a modal open.

    The wait is polled, so setting the shared closing flag releases the thread promptly with
    the safe answer (deny) — no one is left to approve it.
    """
    closing = threading.Event()
    posts: list[object] = []
    thread = threading.Thread(
        target=run_turn_worker,
        args=(fake_harness, "go", fake_state, posts.append, closing),
        daemon=True,
    )
    thread.start()

    _poll_until(lambda: any(isinstance(m, ApprovalRequest) for m in posts))
    time.sleep(0.05)
    assert thread.is_alive()          # genuinely blocked, nothing has resolved it

    closing.set()                     # the app is going away

    thread.join(timeout=5)
    assert not thread.is_alive()
    assert fake_harness.last_ok is False


def test_closing_flag_does_not_deny_an_approval_the_user_answered(fake_harness, fake_state):
    """The poll loop must still honour a real answer — it only changes the timeout shape."""
    closing = threading.Event()
    posts: list[object] = []
    thread = threading.Thread(
        target=run_turn_worker,
        args=(fake_harness, "go", fake_state, posts.append, closing),
        daemon=True,
    )
    thread.start()

    _poll_until(lambda: any(isinstance(m, ApprovalRequest) for m in posts))
    approval = next(m for m in posts if isinstance(m, ApprovalRequest))
    approval.box["ok"] = True
    approval.event.set()

    thread.join(timeout=5)
    assert not thread.is_alive()
    assert fake_harness.last_ok is True


def test_worker_cancels_the_harness_when_closing_mid_turn():
    """Deltas arriving after the app has gone away must stop the harness, not the messages."""

    class _CancellableHarness:
        def __init__(self) -> None:
            from agent86.guardrails.policy import ApprovalGate
            from agent86.types import ApprovalMode

            self.gate = ApprovalGate(ApprovalMode.AUTO)
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

        def run_turn(self, line, state):
            from agent86.types import CompletionDelta

            for i in range(5):
                yield CompletionDelta(text=f"d{i} ")
                if self.cancelled:
                    return

    closing = threading.Event()
    closing.set()
    harness = _CancellableHarness()
    posts: list[object] = []

    run_turn_worker(harness, "go", None, posts.append, closing)

    assert harness.cancelled is True
    assert isinstance(posts[-1], TurnDone)


# ---- harness notices (v0.8) --------------------------------------------- #


class _NoticeHarness:
    """A harness that emits the loop's mid-turn notices around ordinary text."""

    def __init__(self) -> None:
        from agent86.guardrails.policy import ApprovalGate
        from agent86.types import ApprovalMode

        self.gate = ApprovalGate(ApprovalMode.AUTO)

    def run_turn(self, line, state):  # noqa: ANN001
        from agent86.types import CompletionDelta

        yield CompletionDelta(text="\n[compacted 12 messages]\n")
        yield CompletionDelta(text="hello ")
        yield CompletionDelta(text="\n[continuing after 40 steps]\n")


def _drain(harness) -> list[object]:  # noqa: ANN001
    posts: list[object] = []
    thread = threading.Thread(
        target=run_turn_worker, args=(harness, "go", None, posts.append), daemon=True
    )
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    return posts


def test_notice_deltas_become_turn_notices():
    posts = _drain(_NoticeHarness())

    assert [type(m) for m in posts] == [TurnNotice, TurnDelta, TurnNotice, TurnDone]
    assert posts[0].text == "[compacted 12 messages]"  # stripped, ready to render
    assert posts[2].text == "[continuing after 40 steps]"


def test_tool_lines_are_still_tool_announces_not_notices(fake_harness, fake_state):
    """The `[tool]` prefix must keep winning: it carries a status-footer label."""
    posts: list[object] = []
    thread = threading.Thread(
        target=run_turn_worker,
        args=(fake_harness, "go", fake_state, posts.append),
        daemon=True,
    )
    thread.start()
    _poll_until(lambda: any(isinstance(m, ApprovalRequest) for m in posts))
    approval = next(m for m in posts if isinstance(m, ApprovalRequest))
    approval.box["ok"] = True
    approval.event.set()
    thread.join(timeout=5)

    assert not any(isinstance(m, TurnNotice) for m in posts)


# ---- v0.9: structured tool start/result for the collapsible transcript block ---- #


def test_tool_result_parts_only_matches_harness_result_lines():
    assert tool_result_parts("[tool] write_file -> wrote 12 bytes\n") == (
        "write_file",
        "wrote 12 bytes",
    )
    assert tool_result_parts("[tool] read_file -> error: no such file") == (
        "read_file",
        "error: no such file",
    )
    # the START line is not a result line (it has no arrow)
    assert tool_result_parts('\n[tool] write_file({"path": "x"})\n') is None
    # model prose that merely uses an arrow is not harness output
    assert tool_result_parts("first this -> then that") is None
    assert tool_result_parts("[tool] two words -> nope") is None


def test_announce_preview_extracts_the_argument_json():
    assert announce_preview('\n[tool] write_file({"path": "x"})\n') == '{"path": "x"}'
    assert announce_preview("[tool] list_dir()") == ""
    assert announce_preview("not a tool line") == ""


class _StatefulHarness:
    """A harness whose `state` carries the full arguments and the full tool output.

    Mirrors the real loop: the ASSISTANT message (with `tool_calls`) is appended before the
    announce delta, and the TOOL message before the `-> summary` delta.
    """

    def __init__(self) -> None:
        from agent86.guardrails.policy import ApprovalGate
        from agent86.types import ApprovalMode

        self.gate = ApprovalGate(ApprovalMode.AUTO)

    def run_turn(self, line, state):  # noqa: ANN001
        from agent86.types import CompletionDelta, Message, Role, ToolCall

        call = ToolCall(
            id="c1", name="read_file", arguments={"path": "x.py", "note": "y" * 400}
        )
        state.messages.append(Message(role=Role.ASSISTANT, content="", tool_calls=[call]))
        yield CompletionDelta(text='\n[tool] read_file({"path": "x.py", "note": "yyy ...\n')
        state.messages.append(
            Message(
                role=Role.TOOL,
                content="line one\nline two\nline three",
                tool_call_id="c1",
                name="read_file",
            )
        )
        yield CompletionDelta(text="[tool] read_file -> line one\n")


def test_tool_messages_carry_the_full_arguments_and_result():
    from agent86.orchestration.state import AgentState

    state = AgentState(session_id="s1")
    posts = []
    run_turn_worker(_StatefulHarness(), "go", state, posts.append)

    announce = next(m for m in posts if isinstance(m, ToolAnnounce))
    assert announce.name == "read_file"
    assert announce.call_id == "c1"
    # the full dict, not the 160-char preview the delta line carries
    assert announce.args == {"path": "x.py", "note": "y" * 400}

    outcome = next(m for m in posts if isinstance(m, ToolOutcome))
    assert outcome.summary == "line one"
    assert outcome.result == "line one\nline two\nline three"
    assert outcome.ok is True


def test_notice_text_only_matches_harness_notices():
    from agent86.ui.repl import notice_text

    assert notice_text("\n[compacted 12 messages]\n") == "[compacted 12 messages]"
    assert notice_text("[continuing after 40 steps]") == "[continuing after 40 steps]"
    assert notice_text("[continuation 2 of 3]") == "[continuation 2 of 3]"
    # model prose that merely opens with a bracket is NOT a notice
    assert notice_text("[see docs/ARCHITECTURE.md]") is None
    assert notice_text("hello") is None
