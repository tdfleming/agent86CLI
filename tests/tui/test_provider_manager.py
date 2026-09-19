"""Wave 0 scaffold for MODEL-01: `ProviderManagerModal` / `CatalogPickerModal` Pilot tests,
and the full-app chained flows that hook `/config model` -> key entry -> connection test ->
save diff together.

Implemented by plans 03-08 / 03-09. Follows the `_PickerHost` shape from
`tests/tui/test_pickers.py` and the full-app fake-provider harness in `tests/tui/test_app.py`.
"""

from __future__ import annotations

import asyncio
import sys
import types

from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList

from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tui.app import Agent86App
from agent86.types import ApprovalMode
from agent86.ui.repl import _Repl
from tests.support import make_text_provider


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met within timeout")


class _PickerHost(App):
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


def _fake_keyring(monkeypatch, *, store=None):
    store = store if store is not None else {}
    mod = types.ModuleType("keyring")
    errors = types.ModuleType("keyring.errors")

    class KeyringError(Exception):
        pass

    class NoKeyringError(KeyringError):
        pass

    errors.KeyringError = KeyringError
    errors.NoKeyringError = NoKeyringError

    def get_password(service, account):
        return store.get((service, account))

    def set_password(service, account, password):
        store[(service, account)] = password

    mod.get_password = get_password
    mod.set_password = set_password
    mod.errors = errors
    monkeypatch.setitem(sys.modules, "keyring", mod)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors)
    return store


def _make_repl(tmp_path, provider, approval=ApprovalMode.AUTO):
    cfg = load_config()
    cfg.guardrails.approval = approval
    harness = Harness(cfg, provider=provider, memory=None, workspace=tmp_path)
    return _Repl(cfg, resume=None, harness=harness)


async def test_provider_rows_mark_missing_keys(monkeypatch):
    from agent86.tui.screens.provider_manager import provider_rows

    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    _fake_keyring(monkeypatch)

    cfg = load_config()
    rows = {row.name: row for row in provider_rows(cfg)}
    for name in ("anthropic", "openai", "openrouter", "groq"):
        assert rows[name].has_key is False
        assert rows[name].keyless is False
    for name in ("ollama", "llamacpp"):
        assert rows[name].keyless is True


async def test_manager_dismisses_with_selected_row():
    from agent86.tui.screens.provider_manager import ProviderManagerModal, provider_rows

    cfg = load_config()
    host = _PickerHost(ProviderManagerModal(provider_rows(cfg)))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert host.result.name == "anthropic"


async def test_manager_cancel_returns_none():
    from agent86.tui.screens.provider_manager import ProviderManagerModal, provider_rows

    cfg = load_config()
    host = _PickerHost(ProviderManagerModal(provider_rows(cfg)))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert host.result is None


async def test_catalog_filter_narrows():
    from textual.widgets import OptionList

    from agent86.tui.screens.provider_manager import CatalogPickerModal

    entries = [("gpt-4o", "gpt-4o"), ("gpt-4o-mini", "gpt-4o-mini"), ("o3", "o3")]
    host = _PickerHost(CatalogPickerModal("openai", entries))
    async with host.run_test() as pilot:
        await pilot.pause()
        filter_input = host.screen.query_one("#catalog-filter", Input)
        filter_input.focus()
        await pilot.pause()
        for ch in "mini":
            await pilot.press(ch)
        await pilot.pause()
        option_list = host.screen.query_one("#catalog-list", OptionList)
        assert option_list.option_count == 1
        await pilot.press("enter")
        await pilot.pause()
    assert host.result == "openai:gpt-4o-mini"


async def test_catalog_empty_falls_back_to_free_text():
    from agent86.tui.screens.provider_manager import CatalogPickerModal

    host = _PickerHost(CatalogPickerModal("llamacpp", []))
    async with host.run_test() as pilot:
        await pilot.pause()
        filter_input = host.screen.query_one("#catalog-filter", Input)
        filter_input.focus()
        await pilot.pause()
        for ch in "my-local-model":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
    assert host.result == "llamacpp:my-local-model"


async def test_catalog_filter_is_case_insensitive():
    from textual.widgets import OptionList

    from agent86.tui.screens.provider_manager import CatalogPickerModal

    entries = [("gpt-4o", "gpt-4o"), ("gpt-4o-mini", "gpt-4o-mini"), ("o3", "o3")]
    host = _PickerHost(CatalogPickerModal("openai", entries))
    async with host.run_test() as pilot:
        await pilot.pause()
        filter_input = host.screen.query_one("#catalog-filter", Input)
        filter_input.focus()
        await pilot.pause()
        for ch in "MINI":
            await pilot.press(ch)
        await pilot.pause()
        option_list = host.screen.query_one("#catalog-list", OptionList)
        assert option_list.option_count == 1


async def test_catalog_filter_no_match_submits_as_free_text():
    from agent86.tui.screens.provider_manager import CatalogPickerModal

    entries = [("gpt-4o", "gpt-4o"), ("gpt-4o-mini", "gpt-4o-mini"), ("o3", "o3")]
    host = _PickerHost(CatalogPickerModal("openai", entries))
    async with host.run_test() as pilot:
        await pilot.pause()
        filter_input = host.screen.query_one("#catalog-filter", Input)
        filter_input.focus()
        await pilot.pause()
        for ch in "zzz":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
    assert host.result == "openai:zzz"


async def test_catalog_picker_pushed_during_shutdown_does_not_raise():
    """A picker pushed as the app tears down must not raise `NoMatches` from `on_mount`.

    Regression for the order-dependent `#catalog-filter` flake. `CatalogPickerModal` is pushed
    from `on_catalog_ready`, so a catalog-fetch worker result can land in the shutdown window.
    Once `App._running` is False, `App._register` returns no widgets, `mount_all` stops awaiting
    them and `Mount` arrives with the dialog still empty — an unguarded `query_one` in `on_mount`
    then blows up, and Textual re-raises it from `run_test()`'s teardown.

    Pushing with no `pilot.pause()` puts the screen's first `_pre_process` in exactly that window;
    `run_test.__aexit__` re-raises `app._exception`, so this test fails if `on_mount` raises.
    """
    from agent86.tui.screens.provider_manager import CatalogPickerModal

    host = _PickerHost(None)
    async with host.run_test() as pilot:
        await pilot.pause()
        host.push_screen(CatalogPickerModal("openai", [("gpt-4o", "gpt-4o")]))
        # Deliberately no pause: shutdown starts while the modal is still composing.


async def test_catalog_escape_returns_none():
    from agent86.tui.screens.provider_manager import CatalogPickerModal

    entries = [("gpt-4o", "gpt-4o")]
    host = _PickerHost(CatalogPickerModal("openai", entries))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert host.result is None


async def test_ollama_model_with_colon_is_prefixed():
    from textual.widgets import OptionList

    from agent86.tui.screens.provider_manager import CatalogPickerModal
    from agent86.types import ModelRef

    entries = [("llama3.1:8b", "llama3.1:8b")]
    host = _PickerHost(CatalogPickerModal("ollama", entries))
    async with host.run_test() as pilot:
        await pilot.pause()
        option_list = host.screen.query_one("#catalog-list", OptionList)
        option_list.highlighted = 0
        option_list.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert host.result == "ollama:llama3.1:8b"
    assert ModelRef.parse(host.result).model == "llama3.1:8b"


async def test_no_key_provider_chains_to_key_entry(monkeypatch, tmp_path):
    from agent86.tui.screens.key_entry import KeyEntryModal

    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    _fake_keyring(monkeypatch)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "/config model"
        await pilot.press("enter")
        await pilot.pause()
        # select a keyless-env provider row with no key (row selection mechanics owned by 03-08)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, KeyEntryModal)


async def test_save_anyway_override(monkeypatch, tmp_path):
    import agent86.cognitive.catalog as catalog
    import agent86.tui.screens.connection_test as connection_test
    from agent86.tui.screens.connection_test import ConnectionTestModal
    from agent86.tui.screens.provider_manager import CatalogPickerModal
    from agent86.tui.screens.save_diff import SaveDiffModal

    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    _fake_keyring(monkeypatch)

    # No real network calls: fake the catalog fetch and make the connection test fail fast.
    monkeypatch.setattr(
        catalog, "fetch_catalog", lambda provider, pconf, api_key: [("claude-3-opus", "opus")]
    )

    def _boom(ref, cfg, api_key=None):
        raise RuntimeError("simulated connection failure")

    monkeypatch.setattr(connection_test, "provider_for_ref", _boom)

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "/config model"
        await pilot.press("enter")
        await pilot.pause()
        # pick the highlighted (first, no-key) provider row -> KeyEntryModal
        await pilot.press("enter")
        await pilot.pause()

        # type a throwaway key and submit -> catalog fetch (faked) -> CatalogPickerModal
        for ch in "sk-test":
            await pilot.press(ch)
        await pilot.press("enter")
        await _wait_until(lambda: isinstance(app.screen, CatalogPickerModal))

        # pick the (faked) catalog entry -> ConnectionTestModal
        option_list = app.screen.query_one("#catalog-list", OptionList)
        option_list.highlighted = 0
        option_list.focus()
        await pilot.pause()
        await pilot.press("enter")
        await _wait_until(lambda: isinstance(app.screen, ConnectionTestModal))

        # the (faked) connection fails; "Save anyway" is focused — press it
        await _wait_until(lambda: app.screen.query_one("#test-buttons").display, timeout=5.0)
        await pilot.pause()
        await pilot.press("enter")
        await _wait_until(lambda: isinstance(app.screen, SaveDiffModal))
        assert isinstance(app.screen, SaveDiffModal)


async def test_switch_is_immediate_persist_is_separate(monkeypatch, tmp_path):
    import shutil
    from pathlib import Path

    import agent86.cognitive.catalog as catalog
    import agent86.config_writer as config_writer

    # Selecting a provider row that already has a key kicks off a catalog fetch on a worker
    # thread. Left real, that is a live network call whose result lands at an unpredictable
    # moment — including inside the app's shutdown window, where it pushes a CatalogPickerModal
    # into a dying app. That is what made the `#catalog-filter` flake wander between tests and
    # depend on the machine's environment. Stub it so this test is hermetic.
    monkeypatch.setattr(
        catalog, "fetch_catalog", lambda provider, pconf, api_key: [("claude-3-opus", "opus")]
    )

    fixture = Path(__file__).parents[1] / "fixtures" / "config_with_comments.toml"
    target = tmp_path / "config.toml"
    shutil.copy(fixture, target)
    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", target)
    before = target.read_text()

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "/config model"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert repl.harness.provider.model != "unset"
        await pilot.press("escape")
        await pilot.pause()
    assert target.read_text() == before
