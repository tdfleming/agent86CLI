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
from agent86.tui.screens.model_picker import ModelPickerModal, model_choices, prefix_catalog_refs
from agent86.types import ModelRef


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


def test_prefix_catalog_refs_prefixes_colon_bearing_ollama_id():
    """Reproduces the reported bug: an Ollama id already contains a colon of its own."""
    out = prefix_catalog_refs(
        "ollama", [("nemotron-3.5-lightning:latest", "nemotron-3.5-lightning:latest")]
    )
    assert out == [("ollama:nemotron-3.5-lightning:latest", "ollama:nemotron-3.5-lightning:latest")]


def test_prefixed_ollama_ref_parses_back_to_provider_and_full_model():
    """The exact assertion the reported bug violated: partition(':') must split on the FIRST
    colon after prefixing, giving back the provider and the full (colon-bearing) model id."""
    out = prefix_catalog_refs(
        "ollama", [("nemotron-3.5-lightning:latest", "nemotron-3.5-lightning:latest")]
    )
    ref = ModelRef.parse(out[0][0])
    assert ref.provider == "ollama"
    assert ref.model == "nemotron-3.5-lightning:latest"


def test_prefix_catalog_refs_prefixes_colon_free_id():
    """Guards the broader, all-providers breakage: a colon-free id (openai gpt-4o) failed
    ModelRef.parse outright before this fix."""
    out = prefix_catalog_refs("openai", [("gpt-4o", "gpt-4o")])
    assert out == [("openai:gpt-4o", "openai:gpt-4o")]
    ref = ModelRef.parse(out[0][0])
    assert ref.provider == "openai"
    assert ref.model == "gpt-4o"


def test_prefix_catalog_refs_does_not_double_prefix():
    out = prefix_catalog_refs(
        "ollama", [("ollama:llama3.1:8b", "ollama:llama3.1:8b"), ("gpt-4o", "GPT-4o")]
    )
    assert out[0] == ("ollama:llama3.1:8b", "ollama:llama3.1:8b")
    # A distinct provider-supplied display name is left untouched; only the ref is prefixed.
    assert out[1] == ("ollama:gpt-4o", "GPT-4o")


def test_model_choices_does_not_double_prefix_role_slots():
    cfg = load_config()
    default_ref = cfg.model.default
    provider, _, bare_model = default_ref.partition(":")
    entries = [(bare_model, bare_model)]

    base = model_choices(cfg)
    with_extra = model_choices(cfg, extra=prefix_catalog_refs(provider, entries))

    values = [v for _, v in with_extra]
    assert default_ref in values
    assert f"{provider}:{default_ref}" not in values
    assert len(with_extra) == len(base)
