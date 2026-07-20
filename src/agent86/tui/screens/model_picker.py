"""The `/model` picker — an arrow-key `OptionList` alternative to typing `/model <ref>`.

Mirrors `ApprovalModal` (`agent86.tui.screens.approval`): every dismissal path resolves to an
explicit value via `ModalScreen.dismiss(...)` so a chained caller never blocks indefinitely.

`model_choices(cfg)` (D-12) sources the picker's options from today's config — the three role
slots (`model.default`, `model.route.cheap`, `model.route.frontier`) — deduped by ref, with roles
sharing a ref aggregated into a single label. No per-provider model catalog exists yet (that's
Phase 3's job); this is a defensive, always-non-empty-in-practice source with a `[]` fallback.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


def model_choices(cfg) -> list[tuple[str, str]]:
    """Return (label, value) pairs sourced from the three config role slots, deduped by ref.

    Value is the raw `provider:model` ref string. Label aggregates the role name(s) sharing that
    ref, e.g. "default, route.frontier — anthropic:claude-opus-4-8". Returns `[]` if no role slot
    has a non-empty ref (defensive D-12 fallback for callers to prefill "/model " for typing).
    """
    roles = (
        ("default", cfg.model.default),
        ("route.cheap", cfg.model.route.cheap),
        ("route.frontier", cfg.model.route.frontier),
    )
    order: list[str] = []
    roles_by_ref: dict[str, list[str]] = {}
    for role_name, ref in roles:
        if not ref:
            continue
        if ref not in roles_by_ref:
            roles_by_ref[ref] = []
            order.append(ref)
        roles_by_ref[ref].append(role_name)

    return [(f"{', '.join(roles_by_ref[ref])} — {ref}", ref) for ref in order]


class ModelPickerModal(ModalScreen[str | None]):
    """Modal dialog for arrow-key selecting the active model from `model_choices(cfg)`."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, choices: list[tuple[str, str]]) -> None:
        super().__init__()
        self._choices = choices

    def compose(self) -> ComposeResult:
        with Container(id="model-picker-dialog"):
            yield Label("Switch model")
            yield OptionList(*[Option(label, id=value) for label, value in self._choices])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:  # Escape binding -> explicit None, never hangs
        self.dismiss(None)


__all__ = ["ModelPickerModal", "model_choices"]
