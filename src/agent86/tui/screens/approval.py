"""The tool-approval modal — a Textual replacement for the inline `y/N` prompt.

Every dismissal path (approve, deny, Escape) resolves to an explicit `bool` via
`ModalScreen.dismiss(...)`, so the worker thread's `threading.Event`-blocked `approval_cb`
(see `agent86.tui.turn_bridge`) is never left hanging (RESEARCH Pitfall 3).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ApprovalModal(ModalScreen[bool]):
    """Modal dialog asking the user to approve or deny a pending tool call."""

    BINDINGS = [("escape", "deny", "Deny")]

    def __init__(self, tool_name: str, preview: str) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._preview = preview

    def compose(self) -> ComposeResult:
        with Container(id="approval-dialog"):
            yield Label(f"Approve tool: {self._tool_name}?")
            yield Static(self._preview, id="approval-preview")
            yield Button("Run it", id="approve", variant="warning")
            yield Button("Deny", id="deny", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve")

    def action_deny(self) -> None:  # Escape binding -> explicit deny, never hangs
        self.dismiss(False)


__all__ = ["ApprovalModal"]
