"""The approval-mode picker — an arrow-key `RadioSet` alternative to typing `/mode <value>`.

Mirrors `ApprovalModal` (`agent86.tui.screens.approval`): every dismissal path resolves to an
explicit value via `ModalScreen.dismiss(...)` so a chained caller never blocks indefinitely.
Selecting a radio button dismisses with the exact lowercase string `parse_mode` accepts
("ask"/"auto"/"deny") — never an `ApprovalMode` enum member (RESEARCH Pitfall 4).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, RadioButton, RadioSet


class ModePickerModal(ModalScreen[str | None]):
    """Modal dialog for arrow-key selecting the approval mode (ask/auto/deny)."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Container(id="mode-picker-dialog"):
            yield Label("Approval mode")
            with RadioSet(id="mode-options"):
                for value in ("ask", "auto", "deny"):
                    yield RadioButton(value, value=(value == self._current))

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        # Emit the label string directly — do NOT compare against ApprovalMode members.
        self.dismiss(str(event.pressed.label))

    def action_cancel(self) -> None:  # Escape binding -> explicit None, never hangs
        self.dismiss(None)


__all__ = ["ModePickerModal"]
