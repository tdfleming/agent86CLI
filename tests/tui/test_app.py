"""Pilot integration tests for `Agent86App` (TUI-01 shell, TUI-02 live footer, TUI-05 approval).

Builds a real `_Repl` around a real `Harness` with a fake provider (mirrors
`tests/integration/test_repl.py`), drives the app headlessly via `App.run_test()`, and asserts
the shell renders, streams turns on the worker thread with a live footer, and the approval modal
resolves the worker's blocked `threading.Event` on both the approve and deny/escape paths.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator

from textual.widgets import Input, RichLog

from agent86.cognitive.base import ModelProvider
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tui.app import Agent86App
from agent86.tui.screens.approval import ApprovalModal
from agent86.tui.widgets.status_footer import StatusFooter
from agent86.types import ApprovalMode, Completion, CompletionDelta, CompletionRequest, ToolCall, Usage
from agent86.ui.repl import _Repl
from tests.support import ToolThenTextProvider, make_text_provider


class _SlowTextProvider(ModelProvider):
    """Like `make_text_provider`, but sleeps briefly before the final delta.

    Gives the main thread a reliable window to observe `status.working is True` before the
    worker thread posts `TurnDone` — the plain fake provider can complete faster than
    `pilot.press` returns control, making the "live" assertion racy.
    """

    name = "slowtext"

    def __init__(self, reply: str, delay: float = 0.15) -> None:
        self.model = "fake:slowtext"
        self._reply = reply
        self._delay = delay

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        time.sleep(self._delay)
        yield CompletionDelta(text=self._reply)
        yield CompletionDelta(
            done=True,
            completion=Completion(
                text=self._reply,
                usage=Usage(input_tokens=3, output_tokens=2),
                model=self.model,
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


async def test_shell_has_transcript_input_footer(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#transcript", RichLog) is not None
        assert app.query_one("#prompt", Input) is not None
        footer = app.query_one("#status", StatusFooter)
        assert footer is not None
        assert repl.harness.provider.model in str(footer.render())


async def test_turn_streams_and_footer_goes_live_then_idle(tmp_path):
    repl = _make_repl(tmp_path, _SlowTextProvider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "hi there"
        await pilot.press("enter")

        # `_start_turn` sets `status.working = True` synchronously on the main thread before
        # the worker starts; the slow provider keeps it there long enough to observe.
        footer = app.query_one("#status", StatusFooter)
        assert repl.status.working is True
        working_text = str(footer.render())
        assert "…" in working_text or "thinking" in working_text

        await _wait_until(lambda: repl.status.working is False)
        await pilot.pause()

        transcript = app.query_one("#transcript", RichLog)
        lines = "\n".join(str(line) for line in transcript.lines)
        assert "hello world" in lines
        idle_text = str(footer.render())
        assert "ctx" in idle_text


async def _run_approval_case(tmp_path, approve: bool):
    call = ToolCall(id="c1", name="write_file", arguments={"path": "out.txt", "content": "hi"})
    provider = ToolThenTextProvider(call, reply="done")
    repl = _make_repl(tmp_path, provider, approval=ApprovalMode.ASK)
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "write a file"
        await pilot.press("enter")
        await pilot.pause()

        await _wait_until(lambda: isinstance(app.screen, ApprovalModal))
        assert isinstance(app.screen, ApprovalModal)

        if approve:
            await pilot.click("#approve")
        else:
            await pilot.press("escape")

        await _wait_until(lambda: repl.status.working is False, timeout=5.0)
        await pilot.pause()

        transcript = app.query_one("#transcript", RichLog)
        lines = "\n".join(str(line) for line in transcript.lines)
        return lines, tmp_path


async def test_approval_modal_resolves_worker_on_approve(tmp_path):
    lines, path = await _run_approval_case(tmp_path, approve=True)
    assert "done" in lines
    assert (path / "out.txt").read_text() == "hi"


async def test_approval_modal_resolves_worker_on_deny(tmp_path):
    lines, path = await _run_approval_case(tmp_path, approve=False)
    assert "done" in lines
    assert not (path / "out.txt").exists()
