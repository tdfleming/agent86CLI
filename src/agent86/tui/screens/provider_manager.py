"""The `/config model` manager surfaces: provider list + type-to-filter catalog picker.

`provider_rows` is a pure function over `Config` (mirrors `model_choices` in
`agent86.tui.screens.model_picker`) so it is unit-testable without a running app. Every provider
is listed even when no key resolves (D-05) — selecting one chains into the key-entry flow rather
than being a dead end. Key *status* is shown, never a key *value* (D-10).

Both modals mirror `ApprovalModal`: every dismissal path calls `dismiss(...)` with an explicit
value.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from agent86.config import Config


@dataclass(frozen=True)
class ProviderRow:
    """One row of the provider list. `keyless` means the endpoint needs no key at all."""

    name: str
    base_url: str | None
    api_key_env: str | None
    has_key: bool
    keyless: bool

    @property
    def status(self) -> str:
        if self.keyless:
            return "local, no key needed"
        return "key ok" if self.has_key else "no key"


def provider_rows(cfg: Config) -> list[ProviderRow]:
    """Describe every configured provider, in config order, with its key status.

    Uses `resolve_api_key` (env-first, then keyring) so the status matches exactly what a real
    turn would resolve — never reads or returns the key itself.
    """
    from agent86.secrets import resolve_api_key

    rows: list[ProviderRow] = []
    for name, prov in cfg.providers.items():
        keyless = not prov.api_key_env
        has_key = bool(resolve_api_key(name, prov.api_key_env)) if not keyless else False
        rows.append(
            ProviderRow(
                name=name,
                base_url=prov.base_url,
                api_key_env=prov.api_key_env,
                has_key=has_key,
                keyless=keyless,
            )
        )
    return rows


class ProviderManagerModal(ModalScreen[ProviderRow | None]):
    """Pick a provider to configure. Dismisses with the chosen ProviderRow, or None."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, rows: list[ProviderRow]) -> None:
        super().__init__()
        self._rows = {row.name: row for row in rows}
        self._order = [row.name for row in rows]

    def compose(self) -> ComposeResult:
        with Container(id="provider-manager-dialog"):
            yield Label("Providers — select one to configure")
            yield OptionList(
                *[
                    Option(self._label(self._rows[name]), id=name)
                    for name in self._order
                ],
                id="provider-list",
            )

    @staticmethod
    def _label(row: ProviderRow) -> str:
        base = row.base_url or "-"
        return f"{row.name}  [dim]{base}[/dim]  ({row.status})"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._rows.get(event.option_id or ""))

    def action_cancel(self) -> None:
        self.dismiss(None)


class CatalogPickerModal(ModalScreen[str | None]):
    """Pick a model from a live catalog, narrowing by typing (D-03).

    The filter Input doubles as the D-01 free-text fallback: when the catalog is empty (llama.cpp
    exposes no listing, or the fetch failed), submitting the input is taken as the model name.
    Dismisses with a full ``provider:model`` ref, or None.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, provider: str, entries: list[tuple[str, str]]) -> None:
        super().__init__()
        self._provider = provider
        self._entries = entries

    def compose(self) -> ComposeResult:
        placeholder = (
            "type to filter…"
            if self._entries
            else f"no catalog — type a model name for {self._provider} and press enter"
        )
        with Container(id="catalog-picker-dialog"):
            yield Label(f"Models — {self._provider}")
            yield Input(id="catalog-filter", placeholder=placeholder)
            yield OptionList(*self._options(self._entries), id="catalog-list")

    def on_mount(self) -> None:
        self.query_one("#catalog-filter", Input).focus()

    @staticmethod
    def _options(entries: list[tuple[str, str]]) -> list[Option]:
        return [Option(label if label != ref else ref, id=ref) for ref, label in entries]

    def _filtered(self, text: str) -> list[tuple[str, str]]:
        needle = text.strip().lower()
        if not needle:
            return self._entries
        return [
            (ref, label)
            for ref, label in self._entries
            if needle in ref.lower() or needle in label.lower()
        ]

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "catalog-filter":
            return
        option_list = self.query_one("#catalog-list", OptionList)
        option_list.clear_options()
        matches = self._filtered(event.value)
        option_list.add_options(self._options(matches))
        if matches:
            option_list.highlighted = 0

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Free-text fallback (D-01) — also used when a filter matches nothing."""
        # Consume here — otherwise this bubbles to the App's on_input_submitted and gets
        # dispatched as a typed prompt line/turn (UAT gap 1, same leak as KeyEntryModal).
        event.stop()
        raw = (event.value or "").strip()
        if not raw:
            self.dismiss(None)
            return
        matches = self._filtered(raw)
        if len(matches) == 1:
            self.dismiss(self._catalog_ref(matches[0][0]))
            return
        self.dismiss(self._freetext_ref(raw))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id:
            self.dismiss(self._catalog_ref(event.option_id))

    def _catalog_ref(self, model: str) -> str:
        return f"{self._provider}:{model}"

    def _freetext_ref(self, raw: str) -> str:
        return (
            raw
            if ":" in raw and raw.split(":", 1)[0] in {self._provider}
            else f"{self._provider}:{raw}"
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["ProviderRow", "provider_rows", "ProviderManagerModal", "CatalogPickerModal"]
