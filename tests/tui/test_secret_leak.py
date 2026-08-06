"""Regression tests for UAT gaps 1 and 4 (03-10-PLAN.md).

Gap 1 (blocker, SEC-01/D-10): a raw key typed into `KeyEntryModal` (or free text typed into
`CatalogPickerModal`'s filter) must never be echoed into the transcript and must never be
dispatched to the model as a turn — both modals now call `event.stop()` in
`on_input_submitted`, and `Agent86App.on_input_submitted` now ignores any `Input` except
`#prompt`.

Gap 4 (blocker, MODEL-01): a key already stored in the OS keyring must resolve on the second
and subsequent connection tests — `_on_catalog_picked` must pass the `UNRESOLVED` sentinel
(not the stale `None` left by the previous test's `finally` block) whenever no key was typed
this pass.

Follows `tests/tui/test_provider_manager.py`'s established style: real `_Repl`/`Harness` with a
fake provider, `Agent86App(repl).run_test()`, network-safe monkeypatches — no real network
access, no `keyring`/`tomlkit` imports.
"""

from __future__ import annotations

from textual.widgets import Input, RichLog

from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tui.app import Agent86App
from agent86.tui.screens.key_entry import KeyEntryModal
from agent86.tui.screens.provider_manager import CatalogPickerModal
from agent86.types import ApprovalMode
from agent86.ui.repl import _Repl
from tests.support import make_text_provider


def _make_repl(tmp_path, provider, approval=ApprovalMode.AUTO):
    cfg = load_config()
    cfg.guardrails.approval = approval
    harness = Harness(cfg, provider=provider, memory=None, workspace=tmp_path)
    return _Repl(cfg, resume=None, harness=harness)


def _transcript_text(app: Agent86App) -> str:
    transcript = app.query_one("#transcript", RichLog)
    return "\n".join(str(line) for line in transcript.lines)


# ---- Gap 1: leak into transcript / dispatch --------------------------------------- #


async def test_key_entry_submit_does_not_echo_to_transcript(tmp_path, monkeypatch):
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(KeyEntryModal("anthropic", True))
        await pilot.pause()
        await pilot.click("#key-input")
        await pilot.press(*"sk-ant-TESTKEY-0001")
        await pilot.press("enter")
        await pilot.pause()
        assert "sk-ant-TESTKEY-0001" not in _transcript_text(app)


async def test_key_entry_submit_does_not_start_a_turn(tmp_path, monkeypatch):
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    calls: list[str] = []
    monkeypatch.setattr(Agent86App, "_dispatch_line", lambda self, line: calls.append(line))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(KeyEntryModal("anthropic", True))
        await pilot.pause()
        await pilot.click("#key-input")
        await pilot.press(*"sk-ant-TESTKEY-0001")
        await pilot.press("enter")
        await pilot.pause()
        assert calls == []


async def test_catalog_filter_submit_does_not_dispatch(tmp_path, monkeypatch):
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    calls: list[str] = []
    monkeypatch.setattr(Agent86App, "_dispatch_line", lambda self, line: calls.append(line))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(CatalogPickerModal("anthropic", []))
        await pilot.pause()
        filter_input = app.screen.query_one("#catalog-filter", Input)
        filter_input.focus()
        await pilot.pause()
        for ch in "sk-ant-TESTKEY-0001":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert calls == []


async def test_prompt_submit_still_dispatches(tmp_path, monkeypatch):
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    calls: list[str] = []
    monkeypatch.setattr(Agent86App, "_dispatch_line", lambda self, line: calls.append(line))
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        await pilot.pause()
        for ch in "hello":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert calls == ["hello"]


# ---- Gap 4: UNRESOLVED pass-through so a keyring-stored key resolves --------------- #


async def test_second_connection_test_uses_unresolved(tmp_path, monkeypatch):
    import agent86.tui.screens.connection_test as connection_test
    from agent86.cognitive.base import UNRESOLVED
    from agent86.types import Completion

    captured: list[object] = []

    def _recorder(ref, config, api_key=UNRESOLVED):
        captured.append(api_key)

        class _P:
            def complete(self, request):
                return Completion(text="ok", model="anthropic:claude-opus-5")

        return _P()

    monkeypatch.setattr(connection_test, "provider_for_ref", _recorder)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        # State after any completed test: no key held in memory this pass.
        app._pending_row = None
        app._pending_key = None
        app._on_catalog_picked("anthropic:claude-opus-5")
        await pilot.pause()
        assert captured
        assert captured[0] is UNRESOLVED


async def test_typed_key_is_passed_through_not_unresolved(tmp_path, monkeypatch):
    import agent86.tui.screens.connection_test as connection_test
    from agent86.cognitive.base import UNRESOLVED
    from agent86.types import Completion

    captured: list[object] = []

    def _recorder(ref, config, api_key=UNRESOLVED):
        captured.append(api_key)

        class _P:
            def complete(self, request):
                return Completion(text="ok", model="anthropic:claude-opus-5")

        return _P()

    monkeypatch.setattr(connection_test, "provider_for_ref", _recorder)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._pending_row = None
        app._pending_key = "sk-ant-TESTKEY-0001"
        app._on_catalog_picked("anthropic:claude-opus-5")
        await pilot.pause()
        assert captured
        assert captured[0] == "sk-ant-TESTKEY-0001"
