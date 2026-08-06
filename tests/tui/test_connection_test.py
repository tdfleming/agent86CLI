"""Wave 0 scaffold for MODEL-01: `ConnectionTestModal` Pilot tests.

Implemented by plan 03-06. Follows the `_PickerHost` shape from `tests/tui/test_pickers.py`.
All imports of the not-yet-implemented module are deferred inside test bodies so collection
succeeds and the xfail marker (not a collection error) is what records the pending status.
"""

from __future__ import annotations

import threading

import pytest
from textual.app import App, ComposeResult

from agent86.config import load_config
from agent86.types import Completion, CompletionRequest, Usage


class _PickerHost(App):
    """Minimal host app: pushes a given modal screen on mount, records the dismissed value."""

    def __init__(self, screen) -> None:
        super().__init__()
        self._screen = screen
        self.result: object = "__unset__"

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(self._screen, self._store)

    def _store(self, value) -> None:
        self.result = value


class _FakeProvider:
    def __init__(self, *, reply_text="hi", model="m", error=None, block_event=None):
        self._error = error
        self._reply_text = reply_text
        self._model = model
        self._block_event = block_event
        self.last_request: CompletionRequest | None = None

    def complete(self, request: CompletionRequest) -> Completion:
        self.last_request = request
        if self._block_event is not None:
            self._block_event.wait(5)
        if self._error is not None:
            raise self._error
        return Completion(
            text=self._reply_text, usage=Usage(input_tokens=1, output_tokens=1), model=self._model
        )


# ---- KeyEntryModal ----


async def test_key_entry_returns_typed_value():
    from agent86.tui.screens.key_entry import KeyEntryModal

    host = _PickerHost(KeyEntryModal("groq", True))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#key-input")
        await pilot.press(*"sk-abc123")
        await pilot.press("enter")
        await pilot.pause()
        assert host.result == "sk-abc123"


async def test_key_entry_escape_returns_none():
    from agent86.tui.screens.key_entry import KeyEntryModal

    host = _PickerHost(KeyEntryModal("groq", True))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert host.result is None


async def test_key_entry_empty_submit_returns_none():
    from agent86.tui.screens.key_entry import KeyEntryModal

    host = _PickerHost(KeyEntryModal("groq", True))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#key-input")
        await pilot.press("enter")
        await pilot.pause()
        assert host.result is None


async def test_key_entry_input_is_masked():
    from textual.widgets import Input

    from agent86.tui.screens.key_entry import KeyEntryModal

    host = _PickerHost(KeyEntryModal("groq", True))
    async with host.run_test() as pilot:
        await pilot.pause()
        assert host.screen.query_one("#key-input", Input).password is True


async def test_key_entry_reports_keyring_unavailable():
    from textual.widgets import Label

    from agent86.tui.screens.key_entry import KeyEntryModal

    host = _PickerHost(KeyEntryModal("groq", False))
    async with host.run_test() as pilot:
        await pilot.pause()
        status = host.screen.query_one("#key-store-status", Label)
        assert "unavailable" in str(status.content)


async def test_success_dismisses_ok(monkeypatch):
    from agent86.types import ModelRef
    from agent86.tui.screens.connection_test import ConnectionTestModal, TestOutcome
    import agent86.tui.screens.connection_test as connection_test

    fake = _FakeProvider()
    monkeypatch.setattr(connection_test, "provider_for_ref", lambda ref, cfg, api_key: fake)

    host = _PickerHost(ConnectionTestModal(load_config(), ModelRef.parse("openai:gpt-4o"), "sk-x"))
    async with host.run_test() as pilot:
        await pilot.pause()
        for _ in range(20):
            if host.result != "__unset__":
                break
            await pilot.pause(0.1)
        assert host.result == TestOutcome(ok=True, error=None, override=False)


async def test_failure_dismisses_with_verbatim_error(monkeypatch):
    from agent86.cognitive.base import ProviderError
    from agent86.types import ModelRef
    from agent86.tui.screens.connection_test import ConnectionTestModal
    import agent86.tui.screens.connection_test as connection_test

    fake = _FakeProvider(error=ProviderError("401 unauthorized: bad key"))
    monkeypatch.setattr(connection_test, "provider_for_ref", lambda ref, cfg, api_key: fake)

    host = _PickerHost(ConnectionTestModal(load_config(), ModelRef.parse("openai:gpt-4o"), "sk-x"))
    async with host.run_test() as pilot:
        await pilot.pause()
        for _ in range(20):
            try:
                host.screen.query_one("#test-cancel")
                break
            except Exception:
                pass
            await pilot.pause(0.1)
        await pilot.click("#test-cancel")
        await pilot.pause()
        assert host.result.ok is False
        assert host.result.override is False
        assert "401 unauthorized: bad key" in host.result.error


async def test_save_anyway_sets_override(monkeypatch):
    from agent86.cognitive.base import ProviderError
    from agent86.types import ModelRef
    from agent86.tui.screens.connection_test import ConnectionTestModal
    import agent86.tui.screens.connection_test as connection_test

    fake = _FakeProvider(error=ProviderError("401 unauthorized: bad key"))
    monkeypatch.setattr(connection_test, "provider_for_ref", lambda ref, cfg, api_key: fake)

    host = _PickerHost(ConnectionTestModal(load_config(), ModelRef.parse("openai:gpt-4o"), "sk-x"))
    async with host.run_test() as pilot:
        await pilot.pause()
        for _ in range(20):
            try:
                host.screen.query_one("#save-anyway")
                break
            except Exception:
                pass
            await pilot.pause(0.1)
        await pilot.click("#save-anyway")
        await pilot.pause()
        assert host.result.ok is False and host.result.override is True


async def test_timeout_dismisses_with_timeout_message(monkeypatch):
    from agent86.types import ModelRef
    from agent86.tui.screens.connection_test import ConnectionTestModal
    import agent86.tui.screens.connection_test as connection_test

    monkeypatch.setattr(ConnectionTestModal, "TIMEOUT_S", 0.05)
    block_event = threading.Event()
    fake = _FakeProvider(block_event=block_event)
    monkeypatch.setattr(connection_test, "provider_for_ref", lambda ref, cfg, api_key: fake)

    host = _PickerHost(ConnectionTestModal(load_config(), ModelRef.parse("openai:gpt-4o"), "sk-x"))
    async with host.run_test() as pilot:
        await pilot.pause()
        for _ in range(30):
            if host.result != "__unset__":
                break
            await pilot.pause(0.1)
        assert host.result.ok is False
        assert "Timed out" in host.result.error


async def test_max_tokens_one_and_single_message(monkeypatch):
    from agent86.types import ModelRef
    from agent86.tui.screens.connection_test import ConnectionTestModal
    import agent86.tui.screens.connection_test as connection_test

    fake = _FakeProvider()
    monkeypatch.setattr(connection_test, "provider_for_ref", lambda ref, cfg, api_key: fake)

    host = _PickerHost(ConnectionTestModal(load_config(), ModelRef.parse("openai:gpt-4o"), "sk-x"))
    async with host.run_test() as pilot:
        await pilot.pause()
        for _ in range(20):
            if host.result != "__unset__":
                break
            await pilot.pause(0.1)
        req = fake.last_request
        assert req.max_tokens == 1
        assert len(req.messages) == 1
