"""The `/model` picker — an arrow-key `OptionList` alternative to typing `/model <ref>`.

Mirrors `ApprovalModal` (`agent86.tui.screens.approval`): every dismissal path resolves to an
explicit value via `ModalScreen.dismiss(...)` so a chained caller never blocks indefinitely.

`model_choices(cfg)` (D-12) sources the picker's options from today's config — the three role
slots (`model.default`, `model.route.cheap`, `model.route.frontier`) — deduped by ref, with roles
sharing a ref aggregated into a single label. Phase 3 supplies the live catalog via ``extra`` (a
list of ``(ref, label)`` pairs fetched from the provider's models endpoint and cached for the app
session); role slots are still listed first, and entries already covered by a role slot are not
repeated.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


def prefix_catalog_refs(
    provider: str, entries: list[tuple[str, str]] | None
) -> list[tuple[str, str]]:
    """Prefix bare catalog `(ref, label)` pairs with `provider:` so they parse via `ModelRef.parse`.

    `fetch_catalog` (`cognitive/catalog.py`) returns BARE model ids by documented contract — the
    caller prefixes `provider:`. Mirrors `CatalogPickerModal._catalog_ref`
    (`provider_manager.py`), but kept pure here so it's unit-testable without a Pilot app.

    Double-prefix guard: "already prefixed" is tested via an EXACT `f"{provider}:"` prefix match
    only. A bare id can legitimately contain a colon of its own (Ollama's `llama3.1:8b`,
    `nemotron-3.5-lightning:latest`) — "contains a colon" is NOT a valid already-prefixed test,
    that's precisely the bug this function fixes. Same reasoning as
    `CatalogPickerModal._freetext_ref` (`provider_manager.py`).

    Label rule: when the provider supplied no distinct display name (label == ref, e.g. Ollama's
    `(name, name)` or an OpenAI id echoed as its own label), the label is prefixed too so it stays
    equal to the ref and `model_choices`'s `label if label != ref else ref` expression keeps
    rendering the full `provider:model`. A real provider-supplied display name (e.g. OpenRouter's
    `data[].name`) is left untouched.

    Returns a new list; never mutates `entries` (the caller's list may be the session cache stored
    in `Agent86App._catalog_cache` — mutating it would corrupt the cache for later opens).
    """
    out: list[tuple[str, str]] = []
    for ref, label in entries or []:
        full = ref if ref.startswith(f"{provider}:") else f"{provider}:{ref}"
        new_label = full if label == ref else label
        out.append((full, new_label))
    return out


def catalog_has_ref(ref: str, entries: list[tuple[str, str]] | None) -> bool:
    """Does the provider's catalog vouch for `ref` verbatim?

    `fetch_catalog` (`cognitive/catalog.py`) returns BARE model ids by documented contract, so the
    comparison is against the `ref` half of each `(ref, label)` pair only — never the label, which
    may be a provider-supplied display name (OpenRouter's `data[].name`). Exact, case-sensitive
    match: this is the guard that keeps a typo from being masked as a provider-side "model not
    found" at request time (the user's locked decision), so no normalization, no fuzzy matching,
    no `startswith`.

    A `None`/empty `entries` (cold or failed catalog) returns False so the caller falls through to
    the strict error.
    """
    return any(entry_ref == ref for entry_ref, _label in entries or [])


def model_choices(cfg, extra: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """Return (label, value) pairs sourced from the three config role slots, deduped by ref.

    Value is the raw `provider:model` ref string. Label aggregates the role name(s) sharing that
    ref, e.g. "default, route.frontier — anthropic:claude-opus-4-8". Returns `[]` if no role slot
    has a non-empty ref (defensive D-12 fallback for callers to prefill "/model " for typing).

    ``extra`` (Phase 3, D-04) appends live catalog entries after the role slots, deduped against
    them by ref.
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

    out = [(f"{', '.join(roles_by_ref[ref])} — {ref}", ref) for ref in order]
    for ref, label in extra or []:
        if ref in roles_by_ref:
            continue
        if ref in {v for _, v in out}:
            continue
        out.append((label if label != ref else ref, ref))
    return out


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


__all__ = ["ModelPickerModal", "catalog_has_ref", "model_choices", "prefix_catalog_refs"]
