"""Pilot integration tests for the `/`-triggered command palette (TUI-03) and its arrow-key
picker chaining into `/model`/`/mode` (TUI-04).

Reuses the `_make_repl`/`_wait_until` Pilot pattern from `tests/tui/test_app.py`. Also proves the
palette is strictly ADDITIVE (D-11): typed full commands and plain-text turns keep working
unchanged with the palette present.
"""

from __future__ import annotations

import asyncio

from textual.widgets import Input, OptionList

from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tui.app import Agent86App
from agent86.tui.screens.mode_picker import ModePickerModal
from agent86.tui.screens.model_picker import ModelPickerModal
from agent86.types import ApprovalMode
from agent86.ui.repl import _Repl
from tests.support import make_text_provider


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


async def test_palette_filters_and_selects(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "/mo"
        prompt.focus()
        await pilot.pause()
        palette = app.query_one("#palette", OptionList)
        assert palette.display is True
        names = [str(palette.get_option_at_index(i).id) for i in range(palette.option_count)]
        assert "/mode" in names
        assert "/model" in names


async def test_model_command_chains_to_picker(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "/model"
        prompt.focus()
        await pilot.pause()
        # "/model" prefix-matches both "/models" (COMMANDS order: first) and "/model" (second) —
        # move down once to land on the exact "/model" entry that has needs_choice="model".
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ModelPickerModal)

        await pilot.press("enter")
        await pilot.pause()
        await _wait_until(lambda: not isinstance(app.screen, ModelPickerModal))
        assert repl.harness.provider.name + ":" + repl.harness.provider.model


async def test_mode_command_chains_to_picker(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hello world"), approval=ApprovalMode.ASK)
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "/mode"
        prompt.focus()
        await pilot.pause()
        # "/mode" prefix-matches "/models"/"/model"/"/mode" (COMMANDS order) — move down twice
        # to land on the exact "/mode" entry that has needs_choice="mode".
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ModePickerModal)

        app.screen.query_one("#mode-options").focus()
        await pilot.pause()
        await pilot.press("down")  # ask -> auto
        await pilot.press("enter")
        await pilot.pause()
        await _wait_until(lambda: repl.harness.gate.mode is ApprovalMode.AUTO)
        assert repl.harness.gate.mode is ApprovalMode.AUTO


async def test_typed_command_still_works_with_palette(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hello world"), approval=ApprovalMode.ASK)
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "/mode auto"
        prompt.focus()
        await pilot.pause()
        palette = app.query_one("#palette", OptionList)
        assert palette.display is False  # space -> D-11 typed path, not palette territory

        await pilot.press("enter")
        await pilot.pause()
        assert repl.harness.gate.mode is ApprovalMode.AUTO
        assert palette.display is False


async def test_plain_turn_still_submits_with_palette(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "hello there"
        prompt.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        await _wait_until(lambda: repl.status.working is False)
        await pilot.pause()

        from textual.widgets import RichLog

        transcript = app.query_one("#transcript", RichLog)
        lines = "\n".join(str(line) for line in transcript.lines)
        assert "hello world" in lines


async def test_escape_dismisses_palette(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "/"
        prompt.focus()
        await pilot.pause()
        palette = app.query_one("#palette", OptionList)
        assert palette.display is True

        await pilot.press("escape")
        await pilot.pause()
        assert palette.display is False
        assert repl.status.working is False
