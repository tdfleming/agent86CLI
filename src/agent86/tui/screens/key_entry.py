"""Masked API-key entry (SEC-01, D-08/D-10).

Appears at the point of need when neither the environment variable nor the OS keyring yields a
key for a provider. Mirrors `ApprovalModal` (`agent86.tui.screens.approval`): every dismissal
path resolves to an explicit value via `ModalScreen.dismiss(...)`, so a chained caller can never
block indefinitely.

The entered key is returned to the caller and held in memory only — it is written to the keyring
only after the connection test passes (D-14), and it is never echoed, logged to the transcript,
or rendered in plaintext (D-10: no reveal action exists).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class KeyEntryModal(ModalScreen[str | None]):
    """Collect one API key for `provider_name`. Dismisses with the key, or None to cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, provider_name: str, keyring_ok: bool) -> None:
        super().__init__()
        self._provider_name = provider_name
        self._keyring_ok = keyring_ok

    def compose(self) -> ComposeResult:
        with Container(id="key-entry-dialog"):
            yield Label(f"API key for {self._provider_name}")
            yield Input(id="key-input", password=True, placeholder="paste key (never shown)")
            yield Label(
                "Stored in the OS keyring after a successful connection test."
                if self._keyring_ok
                else "OS keyring unavailable — this key will only be used for this test.",
                id="key-store-status",
            )

    def on_mount(self) -> None:
        self.query_one("#key-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = (event.value or "").strip()
        self.dismiss(value or None)

    def action_cancel(self) -> None:  # Escape -> explicit None, never hangs
        self.dismiss(None)


__all__ = ["KeyEntryModal"]
