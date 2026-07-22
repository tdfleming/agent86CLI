"""Wave 0 scaffold for MODEL-01: `ProviderManagerModal` / `CatalogPickerModal` Pilot tests,
and the full-app chained flows that hook `/config model` -> key entry -> connection test ->
save diff together.

Implemented by plans 03-08 / 03-09. Follows the `_PickerHost` shape from
`tests/tui/test_pickers.py` and the full-app fake-provider harness in `tests/tui/test_app.py`.
"""

from __future__ import annotations

import sys
import types

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from agent86.config import ProviderConfig, load_config
from agent86.orchestration.loop import Harness
from agent86.tui.app import Agent86App
from agent86.types import ApprovalMode
from agent86.ui.repl import _Repl
from tests.support import make_text_provider

pytestmark = pytest.mark.xfail(
    reason="Wave 0 scaffold — implemented in plans 03-08/03-09", strict=False
)


class _PickerHost(App):
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
    from agent86.tui.screens.provider_manager import CatalogPickerModal
    from textual.widgets import OptionList

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
    from agent86.tui.screens.save_diff import SaveDiffModal

    _fake_keyring(monkeypatch)
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "/config model"
        await pilot.press("enter")
        await pilot.pause()
        # navigate the full chain: pick provider -> key entry -> failing connection test ->
        # "Save anyway" (exact key bindings owned by 03-08/03-09)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, SaveDiffModal)


async def test_switch_is_immediate_persist_is_separate(monkeypatch, tmp_path):
    import shutil
    from pathlib import Path

    import agent86.config_writer as config_writer

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
