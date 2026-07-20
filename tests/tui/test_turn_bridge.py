"""Unit tests for the worker/app bridge, exercised without a running Textual app."""

from __future__ import annotations

import threading
import time

from agent86.tui.messages import ApprovalRequest, ToolAnnounce, TurnDelta, TurnDone, TurnError
from agent86.tui.turn_bridge import run_turn_worker


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
    assert kinds == [TurnDelta, ToolAnnounce, ApprovalRequest, TurnDelta, TurnDone]
    final_delta = posts[3]
    assert isinstance(final_delta, TurnDelta)
    assert "write_file -> ok" in final_delta.text


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
