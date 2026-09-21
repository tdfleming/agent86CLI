"""v0.9: a tool call is one collapsible block, not two flat `[tool] …` lines.

Collapsed it is a single dim line (`▸ name(args) → summary`); `ctrl+o` expands the last block
and `ctrl+shift+o` every block, revealing the FULL arguments as pretty JSON and the full result
text (capped at `RESULT_LINE_LIMIT` lines). Everything in a block is tool- or model-authored,
so every string renders through `rich.text.Text` and is never markup-parsed.
"""

from __future__ import annotations

import asyncio

from textual.widgets import RichLog

from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tui.app import Agent86App
from agent86.tui.messages import ToolAnnounce, ToolOutcome
from agent86.tui.widgets.prompt_input import PromptInput
from agent86.tui.widgets.tool_block import (
    COLLAPSED_MARKER,
    EXPANDED_MARKER,
    RESULT_LINE_LIMIT,
    ToolBlockEntry,
)
from agent86.types import ApprovalMode, ToolCall
from agent86.ui.repl import _Repl
from tests.support import ToolThenTextProvider


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
    return "\n".join(line.text for line in app.query_one("#transcript", RichLog).lines)


def _styles(app) -> str:
    return "\n".join(str(line) for line in app.query_one("#transcript", RichLog).lines)


# ---- the entry, without an app ---------------------------------------------- #


def test_collapsed_block_is_one_line_with_name_args_and_summary():
    block = ToolBlockEntry(
        name="write_file",
        args={"path": "out[1].txt", "content": "hi"},
        args_preview='{"path": "out[1].txt", "content": "hi"}',
        summary="wrote 2 bytes",
    )
    header = block.header_line()
    assert header.startswith(COLLAPSED_MARKER)
    assert "write_file(" in header
    assert "out[1].txt" in header
    assert "→ wrote 2 bytes" in header
    assert "\n" not in header


def test_expanded_block_shows_pretty_arguments_and_the_full_result():
    block = ToolBlockEntry(
        name="read_file",
        args={"path": "x.py"},
        summary="line one",
        result="line one\nline two\nline three",
    )
    assert block.toggle() is True
    assert block.header_line().startswith(EXPANDED_MARKER)
    body = "\n".join(block.body_lines())
    assert '"path": "x.py"' in body  # pretty JSON, not the truncated preview
    assert "line three" in body  # the full result, not just its first line
    assert body.index("args:") < body.index("result:")


def test_expanded_result_is_capped_with_a_truncated_tail():
    block = ToolBlockEntry(
        name="grep",
        summary="300 matches",
        result="\n".join(f"match {i}" for i in range(300)),
        expanded=True,
    )
    body = block.body_lines()
    assert any("… truncated (100 more lines)" in line for line in body)
    assert not any("match 250" in line for line in body)
    # the cap is on the RESULT, not on the whole block
    assert len(body) <= RESULT_LINE_LIMIT + 12


def test_block_text_is_never_markup():
    """A result full of markup lookalikes renders literally and cannot raise."""
    from rich.console import Console

    block = ToolBlockEntry(
        name="read_file",
        args={"path": "[/etc/hosts]"},
        summary="see [/x] and list[int]",
        result="[tool] not a real tool line\n[/close]",
        expanded=True,
    )
    console = Console(width=200, record=True)
    console.print(block.render())
    text = console.export_text()
    assert "[/etc/hosts]" in text
    assert "[/close]" in text
    assert "list[int]" in text


def test_collapsed_header_is_dim():
    block = ToolBlockEntry(name="x", summary="ok")
    assert block.render().style == "dim"
    failed = ToolBlockEntry(name="x", summary="error: nope", ok=False)
    assert "red" in failed.render().style


# ---- through the running app ------------------------------------------------ #


async def _run_tool_turn(app, pilot, repl, line: str = "write it") -> None:
    app.query_one("#prompt", PromptInput).value = line
    await pilot.press("enter")
    await _wait_until(lambda: repl.status.working is False)
    await pilot.pause()


def _tool_provider(content: str = "hi"):
    call = ToolCall(id="c1", name="write_file", arguments={"path": "out.txt", "content": content})
    return ToolThenTextProvider(call, reply="done")


async def test_tool_block_is_collapsed_by_default(tmp_path):
    repl = _make_repl(tmp_path, _tool_provider())
    app = Agent86App(repl)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await _run_tool_turn(app, pilot, repl)

        blocks = app._tool_blocks()
        assert len(blocks) == 1
        assert blocks[0].expanded is False
        lines = _transcript(app)
        assert COLLAPSED_MARKER in lines
        assert "write_file(" in lines
        assert "args:" not in lines  # the pretty-printed detail is hidden
        assert "result:" not in lines
        # one line for the whole call, where there used to be two
        assert sum(1 for line in lines.splitlines() if "write_file" in line) == 1
        assert "dim=True" in _styles(app)


async def test_ctrl_o_expands_the_last_tool_block(tmp_path):
    repl = _make_repl(tmp_path, _tool_provider(content="hello world"))
    app = Agent86App(repl)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await _run_tool_turn(app, pilot, repl)
        assert "args:" not in _transcript(app)

        await pilot.press("ctrl+o")
        await pilot.pause()

        assert app._tool_blocks()[0].expanded is True
        lines = _transcript(app)
        assert EXPANDED_MARKER in lines
        # the full arguments, pretty-printed (indented), not just the header preview
        assert '      "content": "hello world"' in lines
        assert "result:" in lines
        assert "Wrote" in lines  # the tool's own output

        await pilot.press("ctrl+o")  # and back
        await pilot.pause()
        assert app._tool_blocks()[0].expanded is False
        assert "args:" not in _transcript(app)


async def test_ctrl_shift_o_toggles_every_block(tmp_path):
    repl = _make_repl(tmp_path, _tool_provider())
    app = Agent86App(repl)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        # two calls, from two turns
        await _run_tool_turn(app, pilot, repl)
        repl.harness.provider.calls = 0
        await _run_tool_turn(app, pilot, repl, "again")
        assert len(app._tool_blocks()) == 2

        await pilot.press("ctrl+shift+o")
        await pilot.pause()
        assert all(block.expanded for block in app._tool_blocks())

        await pilot.press("ctrl+shift+o")
        await pilot.pause()
        assert not any(block.expanded for block in app._tool_blocks())


async def test_toggling_keeps_the_rest_of_the_transcript(tmp_path):
    """A re-render replays every entry — the prompt echo and the answer must survive it."""
    repl = _make_repl(tmp_path, _tool_provider())
    app = Agent86App(repl)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await _run_tool_turn(app, pilot, repl)
        await pilot.press("ctrl+o")
        await pilot.pause()

        lines = _transcript(app)
        assert "> write it" in lines
        assert "done" in lines
        assert "session " in lines  # the startup notes are entries too


async def test_a_result_without_an_announce_still_gets_a_block(tmp_path):
    repl = _make_repl(tmp_path, _tool_provider())
    app = Agent86App(repl)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        app.on_tool_outcome(ToolOutcome("orphan", "done anyway", result="body"))
        await pilot.pause()

        assert [b.name for b in app._tool_blocks()] == ["orphan"]
        assert "orphan(" in _transcript(app)


async def test_an_announce_without_a_result_is_flushed_at_turn_end(tmp_path):
    from agent86.tui.messages import TurnDone

    repl = _make_repl(tmp_path, _tool_provider())
    app = Agent86App(repl)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        app.on_tool_announce(ToolAnnounce("running slow_tool", "", name="slow_tool"))
        await pilot.pause()
        assert "slow_tool" not in _transcript(app)  # nothing to show yet

        app.on_turn_done(TurnDone())
        await pilot.pause()
        assert "slow_tool" in _transcript(app)
        assert app._pending_tools == []
