"""Interrupting a running turn from the TUI (Escape / Ctrl+C) and quitting cleanly.

Before this, a turn owned the app: the prompt was disabled for its whole duration, the
harness generator had no stop flag, and quitting while the approval modal was open left the
worker thread parked on an unbounded `event.wait()`.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator

from textual.widgets import Input, RichLog

from agent86.cognitive.base import ModelProvider
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tui.app import Agent86App
from agent86.tui.screens.approval import ApprovalModal
from agent86.types import (
    ApprovalMode,
    Completion,
    CompletionDelta,
    CompletionRequest,
    ToolCall,
    Usage,
)
from agent86.ui.repl import _Repl
from tests.support import ToolThenTextProvider, make_text_provider


class _EndlessProvider(ModelProvider):
    """Streams slowly and forever — only a cancel ends the turn."""

    name = "endless"

    def __init__(self, chunk_delay: float = 0.02) -> None:
        self.model = "fake:endless"
        self._delay = chunk_delay
        self.emitted = 0

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        for i in range(2000):
            self.emitted += 1
            time.sleep(self._delay)
            yield CompletionDelta(text=f"chunk{i} ")
        yield CompletionDelta(  # pragma: no cover - a cancel always lands first
            done=True,
            completion=Completion(
                text="", usage=Usage(input_tokens=1, output_tokens=1), model=self.model
            ),
        )


def _make_repl(tmp_path, provider, approval=ApprovalMode.AUTO):
    cfg = load_config()
    cfg.guardrails.approval = approval
    harness = Harness(cfg, provider=provider, memory=None, workspace=tmp_path)
    return _Repl(cfg, resume=None, harness=harness)


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met within timeout")


def _transcript(app) -> str:
    return "\n".join(str(line) for line in app.query_one("#transcript", RichLog).lines)


async def _start_endless_turn(app, pilot, repl):
    app.query_one("#prompt", Input).value = "run forever"
    await pilot.press("enter")
    await _wait_until(lambda: repl.harness.provider.emitted > 2)
    assert app._turn_running is True


async def test_escape_cancels_a_running_turn(tmp_path):
    provider = _EndlessProvider()
    repl = _make_repl(tmp_path, provider)
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _start_endless_turn(app, pilot, repl)

        await pilot.press("escape")
        await pilot.pause()
        assert repl.harness.cancelled is True
        assert "cancelling" in _transcript(app)

        # The turn actually ends, the input comes back, and the app is still alive.
        await _wait_until(lambda: app._turn_running is False)
        await pilot.pause()
        assert app.query_one("#prompt", Input).disabled is False
        assert "[cancelled]" in _transcript(app)
        assert app.is_running


async def test_escape_at_idle_does_not_cancel(tmp_path):
    """With no turn running Escape keeps its old meaning (fall through, nothing cancelled)."""
    repl = _make_repl(tmp_path, make_text_provider("hi"))
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert repl.harness.cancelled is False
        assert app.is_running


async def test_ctrl_c_cancels_then_quits(tmp_path):
    provider = _EndlessProvider()
    repl = _make_repl(tmp_path, provider)
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _start_endless_turn(app, pilot, repl)

        await pilot.press("ctrl+c")            # first press: cancel
        await pilot.pause()
        assert repl.harness.cancelled is True
        assert app.is_running

        await _wait_until(lambda: app._turn_running is False)
        await pilot.pause()

        await pilot.press("ctrl+c")            # second press, now idle: quit
        await _wait_until(lambda: not app.is_running)
    assert not app.is_running


async def test_ctrl_c_at_idle_quits(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hi"))
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+c")
        await _wait_until(lambda: not app.is_running)
    assert not app.is_running


async def test_quitting_with_an_approval_open_releases_the_worker(tmp_path):
    """The hang this fixes: a worker blocked on `event.wait()` kept the interpreter alive."""
    call = ToolCall(id="c1", name="write_file", arguments={"path": "out.txt", "content": "hi"})
    repl = _make_repl(tmp_path, ToolThenTextProvider(call, reply="done"), ApprovalMode.ASK)
    app = Agent86App(repl)
    before = set(threading.enumerate())
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        app.query_one("#prompt", Input).value = "write it"
        await pilot.press("enter")
        await _wait_until(lambda: isinstance(app.screen, ApprovalModal))
        assert app._pending_approvals            # the worker is parked on this
        event, box = app._pending_approvals[0]
        assert not event.is_set()

        app.exit()                               # quit with the modal still up

    # Unmount resolved the pending approval as denied; the worker thread finishes on its own.
    assert app._pending_approvals == []
    assert app._shutdown_event.is_set()
    assert event.is_set()                        # the worker was actually released
    assert box["ok"] is False                    # with the safe answer
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        leftover = set(threading.enumerate()) - before
        if not any(t.is_alive() and "TurnWorker" in t.name for t in leftover):
            break
        await asyncio.sleep(0.05)
    leftover = [t for t in set(threading.enumerate()) - before if t.is_alive()]
    assert not any("TurnWorker" in t.name for t in leftover), leftover
    assert (tmp_path / "out.txt").exists() is False   # denied, so nothing was written


async def test_cancel_state_resets_for_the_next_turn(tmp_path):
    provider = _EndlessProvider()
    repl = _make_repl(tmp_path, provider)
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _start_endless_turn(app, pilot, repl)
        await pilot.press("escape")
        await _wait_until(lambda: app._turn_running is False)
        await pilot.pause()

        assert app._cancel_requested is False
        # A fresh turn with a normal provider runs to completion.
        repl.harness.provider = make_text_provider("all good")
        repl.harness.router.set_forced(repl.harness.provider)
        app.query_one("#prompt", Input).value = "again"
        await pilot.press("enter")
        await _wait_until(lambda: repl.status.working is False)
        await pilot.pause()
        assert "all good" in _transcript(app)
