"""The tool-approval modal — a Textual replacement for the inline `y/N` prompt.

Every dismissal path (approve, deny, Escape) resolves to an explicit `bool` via
`ModalScreen.dismiss(...)`, so the worker thread's `threading.Event`-blocked `approval_cb`
(see `agent86.tui.turn_bridge`) is never left hanging (RESEARCH Pitfall 3).

The modal shows *what the call would do*, not just its arguments: when the gate attaches a
`detail` to the preview (`guardrails.policy.ApprovalPreview`) it is rendered in a scrollable,
syntax-highlighted panel — a unified diff for `write_file`/`edit_file`, the full command or
snippet for `run_command`/`python_exec`. Approving a write sight-unseen is the thing this
screen exists to prevent.
"""

from __future__ import annotations

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ApprovalModal(ModalScreen[bool]):
    """Modal dialog asking the user to approve or deny a pending tool call."""

    BINDINGS = [
        ("escape", "deny", "Deny"),
        ("y", "approve", "Approve"),
        ("n", "deny", "Deny"),
    ]

    DEFAULT_CSS = """
    ApprovalModal #approval-detail-scroll {
        max-height: 20;
        border: round $panel;
    }
    """

    def __init__(self, tool_name: str, preview: str) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._preview = preview
        # The gate hands us an `ApprovalPreview` (a str subclass); a plain str from an older
        # caller or a test double simply has no detail and renders as before.
        self._detail: str | None = getattr(preview, "detail", None)
        self._lexer: str | None = getattr(preview, "lexer", None)

    def compose(self) -> ComposeResult:
        with Container(id="approval-dialog"):
            # Both the tool name (MCP servers name their own tools) and the JSON argument
            # preview are untrusted. `Static`/`Label` interpret markup by default, so a
            # preview containing `[` would either raise MarkupError while composing the modal
            # — on the main thread, with the worker still blocked — or silently hide the very
            # arguments the user is being asked to approve. `Text` disables markup entirely.
            yield Label(Text(f"Approve tool: {self._tool_name}?"))
            yield Static(Text(self._preview), id="approval-preview")
            if self._detail:
                with VerticalScroll(id="approval-detail-scroll"):
                    # `Syntax` is a Rich renderable built from the raw string, so the detail is
                    # highlighted without ever being parsed as console markup.
                    yield Static(self._render_detail(), id="approval-detail", markup=False)
            yield Button("Run it", id="approve", variant="warning")
            yield Button("Deny", id="deny", variant="error")

    def _render_detail(self) -> Syntax | Text:
        detail = self._detail or ""
        if not self._lexer:
            return Text(detail)
        try:
            return Syntax(
                detail,
                self._lexer,
                theme="ansi_dark",
                word_wrap=True,
                background_color="default",
            )
        except Exception:  # unknown lexer / pygments hiccup — plain text still tells the truth
            return Text(detail)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:  # Escape binding -> explicit deny, never hangs
        self.dismiss(False)


__all__ = ["ApprovalModal"]
