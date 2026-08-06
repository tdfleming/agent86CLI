"""Pilot tests for the arrow-key `/mode` and `/model` pickers (TUI-04).

Each picker is a standalone `ModalScreen[str | None]` (mirrors `ApprovalModal`), so it's
driven headlessly via a tiny host `App` that pushes the picker and stores whatever value it
dismisses with — the same `push_screen(screen, callback)` shape used by
`agent86.tui.app.Agent86App` for `ApprovalModal` (see `tests/tui/test_app.py`).
"""

from __future__ import annotations

from textual.app import App, ComposeResult

from agent86.config import load_config
from agent86.tui.screens.mode_picker import ModePickerModal
from agent86.tui.screens.model_picker import ModelPickerModal, model_choices


class _PickerHost(App):
    """Minimal host app: pushes a given picker screen on mount, records the dismissed value."""

    def __init__(self, picker) -> None:
        super().__init__()
        self._picker = picker
        self.result: object = "__unset__"

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(self._picker, self._store)

    def _store(self, value) -> None:
        self.result = value


async def test_mode_picker_dismisses_with_selected_value():
    host = _PickerHost(ModePickerModal("ask"))
    async with host.run_test() as pilot:
        await pilot.pause()
        radio_set = host.screen.query_one("#mode-options")
        radio_set.focus()
        await pilot.pause()
        await pilot.press("down")  # ask -> auto
        await pilot.press("enter")
        await pilot.pause()
        assert host.result == "auto"


async def test_mode_picker_cancel_returns_none():
    host = _PickerHost(ModePickerModal("ask"))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert host.result is None


async def test_model_picker_dismisses_with_ref():
    choices = model_choices(load_config())
    assert choices, "expected at least one model choice from the default config"
    host = _PickerHost(ModelPickerModal(choices))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert host.result == choices[0][1]


async def test_model_picker_cancel_returns_none():
    choices = model_choices(load_config())
    host = _PickerHost(ModelPickerModal(choices))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert host.result is None


def test_model_choices_dedups_roles():
    vals = [v for _, v in model_choices(load_config())]
    assert len(vals) == len(set(vals))
    assert len(vals) >= 1


def test_model_choices_appends_extras():
    base = model_choices(load_config())
    with_extra = model_choices(load_config(), extra=[("openai:gpt-4o", "gpt-4o")])
    assert len(with_extra) == len(base) + 1
    assert with_extra[-1][1] == "openai:gpt-4o"


def test_model_choices_extras_deduped_against_roles():
    cfg = load_config()
    base = model_choices(cfg)
    with_extra = model_choices(cfg, extra=[(cfg.model.default, "dupe")])
    assert len(with_extra) == len(base)


def test_model_choices_signature_backward_compatible():
    cfg = load_config()
    assert model_choices(cfg) == model_choices(cfg)


def test_model_choices_empty_fallback():
    class _Route:
        cheap = ""
        frontier = ""

    class _Model:
        default = ""
        route = _Route()

    class _Cfg:
        model = _Model()

    assert model_choices(_Cfg()) == []
