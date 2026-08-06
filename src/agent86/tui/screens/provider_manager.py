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
from textual.widgets import Label, OptionList
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


__all__ = ["ProviderRow", "provider_rows", "ProviderManagerModal"]
