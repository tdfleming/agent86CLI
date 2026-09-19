"""Wave 0 scaffold for MODEL-01: `ConnectionTestModal` Pilot tests.

Implemented by plan 03-06. Follows the `_PickerHost` shape from `tests/tui/test_pickers.py`.
All imports of the not-yet-implemented module are deferred inside test bodies so collection
succeeds and the xfail marker (not a collection error) is what records the pending status.
"""

from __future__ import annotations

import threading

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
        # `None` means "bare host": the test pushes its own screen when it wants to.
        if self._screen is not None:
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
    import agent86.tui.screens.connection_test as connection_test
    from agent86.tui.screens.connection_test import ConnectionTestModal, TestOutcome
    from agent86.types import ModelRef

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
    import agent86.tui.screens.connection_test as connection_test
    from agent86.cognitive.base import ProviderError
    from agent86.tui.screens.connection_test import ConnectionTestModal
    from agent86.types import ModelRef

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
    import agent86.tui.screens.connection_test as connection_test
    from agent86.cognitive.base import ProviderError
    from agent86.tui.screens.connection_test import ConnectionTestModal
    from agent86.types import ModelRef

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
    import agent86.tui.screens.connection_test as connection_test
    from agent86.tui.screens.connection_test import ConnectionTestModal
    from agent86.types import ModelRef

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
    import agent86.tui.screens.connection_test as connection_test
    from agent86.tui.screens.connection_test import ConnectionTestModal
    from agent86.types import ModelRef

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


# ---- shutdown-window guards (regression for the 67a79ca mount race) ----


async def test_key_entry_pushed_during_shutdown_does_not_raise():
    """`KeyEntryModal.on_mount` must survive being mounted with no children.

    Same race as the `#catalog-filter` flake fixed in 67a79ca: once `App._running` is False,
    `App._register` returns no widgets, so `mount_all` stops awaiting the composed children and
    `Mount` arrives with the dialog empty. This modal is reached from the provider flow, which
    is driven off catalog/connection workers, so a push can land in that window. Pushing with no
    `pilot.pause()` puts `on_mount` there deterministically; `run_test.__aexit__` re-raises
    `app._exception`, so an unguarded `query_one` fails this test.
    """
    from agent86.tui.screens.key_entry import KeyEntryModal

    host = _PickerHost(None)
    async with host.run_test() as pilot:
        await pilot.pause()
        host.push_screen(KeyEntryModal("openai", True))
        # Deliberately no pause: shutdown starts while the modal is still composing.


async def test_connection_test_pushed_during_shutdown_fires_no_probe(monkeypatch):
    """Mounted into the shutdown window, the modal must not raise — and must not dial out.

    The probe is a real network call. Starting one for a screen that will never be seen leaves a
    worker thread running past the app's lifetime with a `call_from_thread` that has nowhere to
    land, so `on_mount` bails when its children are missing.
    """
    import agent86.tui.screens.connection_test as connection_test
    from agent86.tui.screens.connection_test import ConnectionTestModal
    from agent86.types import ModelRef

    def _never(*args, **kwargs):
        raise AssertionError("no provider may be built for a screen mounted during shutdown")

    monkeypatch.setattr(connection_test, "provider_for_ref", _never)

    host = _PickerHost(None)
    async with host.run_test() as pilot:
        await pilot.pause()
        host.push_screen(
            ConnectionTestModal(load_config(), ModelRef.parse("openai:gpt-4o"), "sk-x")
        )
        # Deliberately no pause.


async def test_finish_after_dismiss_is_a_no_op(monkeypatch):
    """A worker result landing after the screen is gone must not raise.

    `_finish`/`_timeout` are handed to `call_from_thread`, so they run at a moment the worker
    picked. If the user pressed Escape (or the app quit) first, `dismiss` raises `ScreenError`
    and every widget lookup misses. Calling them directly on a dismissed screen is the same
    situation without the timing dependency.
    """
    import agent86.tui.screens.connection_test as connection_test
    from agent86.tui.screens.connection_test import ConnectionTestModal
    from agent86.types import ModelRef

    block = threading.Event()
    fake = _FakeProvider(block_event=block)
    monkeypatch.setattr(connection_test, "provider_for_ref", lambda ref, cfg, api_key: fake)

    modal = ConnectionTestModal(load_config(), ModelRef.parse("openai:gpt-4o"), "sk-x")
    host = _PickerHost(modal)
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")  # user gives up while the probe is in flight
        await pilot.pause()
        assert host.result.ok is False
        # The late worker callbacks, exactly as `call_from_thread` would deliver them.
        modal._finish(True, None)
        modal._finish(False, "boom")
        modal._timeout("Timed out after 15s — no response.")
        block.set()
