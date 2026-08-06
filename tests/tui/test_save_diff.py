"""Wave 0 scaffold for MODEL-02: `SaveDiffModal` Pilot tests.

Implemented by plan 03-07. Follows the `_PickerHost` shape from `tests/tui/test_pickers.py`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from textual.app import App, ComposeResult

FIXTURE = Path(__file__).parents[1] / "fixtures" / "config_with_comments.toml"


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


def _patch_user_scope(monkeypatch, tmp_path):
    import agent86.config_writer as config_writer

    target = tmp_path / "config.toml"
    shutil.copy(FIXTURE, target)
    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", target)
    return target


async def test_diff_matches_actual_write(tmp_path, monkeypatch):
    from agent86.config_writer import apply_edit
    from agent86.tui.screens.save_diff import SaveDiffModal
    from textual.widgets import Static

    target = _patch_user_scope(monkeypatch, tmp_path)

    host = _PickerHost(
        SaveDiffModal([(["model", "default"], "groq:llama-3.3-70b-versatile")])
    )
    async with host.run_test() as pilot:
        await pilot.pause()
        body = host.screen.query_one("#save-diff-body", Static)
        previewed_text = str(body.render())
        await pilot.click("#save-confirm")
        await pilot.pause()

    edit = host.result
    apply_edit(edit)
    assert previewed_text == edit.diff
    assert edit.after_text == target.read_text()


async def test_default_scope_is_user(tmp_path, monkeypatch):
    from agent86.tui.screens.save_diff import SaveDiffModal
    from textual.widgets import RadioButton

    _patch_user_scope(monkeypatch, tmp_path)
    host = _PickerHost(
        SaveDiffModal([(["model", "default"], "groq:llama-3.3-70b-versatile")])
    )
    async with host.run_test() as pilot:
        await pilot.pause()
        assert host.screen.query_one("#scope-user", RadioButton).value is True
        await pilot.click("#save-confirm")
        await pilot.pause()
    assert host.result.scope == "user"


async def test_project_scope_recomputes_path(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer
    from agent86.tui.screens.save_diff import SaveDiffModal

    _patch_user_scope(monkeypatch, tmp_path)
    project_path = tmp_path / "project_config.toml"
    monkeypatch.setattr(config_writer, "PROJECT_CONFIG_PATH", project_path)

    host = _PickerHost(
        SaveDiffModal([(["model", "default"], "groq:llama-3.3-70b-versatile")])
    )
    async with host.run_test() as pilot:
        await pilot.pause()
        host.screen.query_one("#save-scope").focus()
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.click("#save-confirm")
        await pilot.pause()
    assert host.result.scope == "project"
    assert host.result.path == project_path


async def test_cancel_returns_none(tmp_path, monkeypatch):
    from agent86.tui.screens.save_diff import SaveDiffModal

    target = _patch_user_scope(monkeypatch, tmp_path)
    before = target.read_text()

    host = _PickerHost(
        SaveDiffModal([(["model", "default"], "groq:llama-3.3-70b-versatile")])
    )
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert host.result is None
    assert target.read_text() == before
