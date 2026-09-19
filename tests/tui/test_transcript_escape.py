"""Untrusted text must never be interpreted as Rich console markup (P0 crash).

`RichLog(markup=True)` and `Static`/`Label` both run `Text.from_markup` on plain strings, so
model output, tool argument previews and the user's own echoed line could raise
`rich.markup.MarkupError` on the MAIN thread — which tears the whole app down — or silently
swallow content that merely looked like a tag. These tests drive the real app headlessly with
text that trips both failure modes and assert the literal characters survive.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

from textual.widgets import Input, RichLog, Static

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
from tests.support import ToolThenTextProvider

# Three shapes that each break a different way when rendered as markup:
#  - `[/path/to/file]` -> MarkupError ("closing tag ... doesn't match any open tag")
#  - `list[int]`       -> not an error, but `[int]` is eaten as an unknown style
#  - `[tool] foo`      -> `[tool]` is eaten as a style tag, losing the label
TRICKY = "see [/path/to/file] and list[int] plus [tool] foo"


class _TrickyProvider(ModelProvider):
    """Streams one delta of markup-hostile text, then completes."""

    name = "tricky"

    def __init__(self, reply: str = TRICKY) -> None:
        self.model = "fake:tricky"
        self._reply = reply

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
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


def _transcript(app) -> str:
    return "\n".join(str(line) for line in app.query_one("#transcript", RichLog).lines)


async def test_markup_hostile_model_text_neither_crashes_nor_vanishes(tmp_path):
    repl = _make_repl(tmp_path, _TrickyProvider())
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        app.query_one("#prompt", Input).value = "go"
        await pilot.press("enter")

        await _wait_until(lambda: repl.status.working is False)
        await pilot.pause()

        # The app survived the turn: no MarkupError escaped onto the main thread.
        assert app.is_running
        lines = _transcript(app)
        assert "[/path/to/file]" in lines
        assert "list[int]" in lines
        assert "[tool] foo" in lines
        assert "error:" not in lines


async def test_stream_widget_holds_literal_text_mid_turn(tmp_path):
    """The live `#stream` Static is updated per delta — it must not interpret markup either."""
    repl = _make_repl(tmp_path, _TrickyProvider())
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        # Drive the handler directly: the buffer is cleared again the moment the turn ends,
        # so racing a real turn to observe it would be flaky.
        from agent86.tui.messages import TurnDelta

        app.on_turn_delta(TurnDelta(TRICKY))
        await pilot.pause()

        rendered = str(app.query_one("#stream", Static).render())
        assert "[/path/to/file]" in rendered
        assert "[tool] foo" in rendered


async def test_echoed_user_line_is_escaped(tmp_path):
    repl = _make_repl(tmp_path, _TrickyProvider(reply="ok"))
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        app.query_one("#prompt", Input).value = "check [/etc/hosts] now"
        await pilot.press("enter")
        await pilot.pause()

        assert app.is_running
        assert "check [/etc/hosts] now" in _transcript(app)


async def test_unknown_command_with_markup_does_not_crash(tmp_path):
    """`handle_command` echoes the typed line back; `_write`'s guard must absorb bad markup."""
    repl = _make_repl(tmp_path, _TrickyProvider(reply="ok"))
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        app.query_one("#prompt", Input).value = "/nope [/oops]"
        await pilot.press("enter")
        await pilot.pause()

        assert app.is_running
        assert "/nope [/oops]" in _transcript(app)


async def test_tool_announce_line_keeps_its_label_and_brackets(tmp_path):
    call = ToolCall(id="c1", name="write_file", arguments={"path": "out[1].txt", "content": "hi"})
    repl = _make_repl(tmp_path, ToolThenTextProvider(call, reply="done"))
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        app.query_one("#prompt", Input).value = "write it"
        await pilot.press("enter")

        await _wait_until(lambda: repl.status.working is False)
        await pilot.pause()

        lines = _transcript(app)
        assert "[tool] write_file" in lines      # the label survived markup rendering
        assert "out[1].txt" in lines             # so did the bracketed argument


async def test_approval_preview_with_brackets_renders(tmp_path):
    call = ToolCall(id="c1", name="write_file", arguments={"path": "out[1].txt", "content": "hi"})
    repl = _make_repl(tmp_path, ToolThenTextProvider(call, reply="done"), ApprovalMode.ASK)
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        app.query_one("#prompt", Input).value = "write it"
        await pilot.press("enter")

        await _wait_until(lambda: isinstance(app.screen, ApprovalModal))
        preview = str(app.screen.query_one("#approval-preview", Static).render())
        assert "out[1].txt" in preview

        await pilot.press("escape")
        await _wait_until(lambda: repl.status.working is False)
        assert app.is_running
