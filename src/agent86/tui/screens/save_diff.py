"""Scope selection + TOML diff preview before a config write (MODEL-02, D-16/D-17).

Deliberately a trust-building artifact: the user sees the exact unified diff and the full target
path *before* anything is committed, which is how success criterion 3 ("comments preserved") is
demonstrated rather than asserted. Scope is explicit on every write — user
(`~/.agent86/config.toml`) is pre-selected, project (`./.agent86/config.toml`) is one arrow key
away.

This modal never touches disk. `plan_edit` computes text and diff in memory; the caller applies
the returned `ConfigEdit` with `config_writer.apply_edit`. Mirrors `ApprovalModal`: every
dismissal path resolves explicitly.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RadioButton, RadioSet, Static

from agent86.config_writer import (
    SCOPE_PROJECT,
    SCOPE_USER,
    ConfigEdit,
    ConfigWriteError,
    plan_edit,
)


class SaveDiffModal(ModalScreen[ConfigEdit | None]):
    """Preview `changes` against the chosen scope; dismiss with the ConfigEdit or None."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, changes: list[tuple[list[str], Any]], scope: str = SCOPE_USER) -> None:
        super().__init__()
        self._changes = changes
        self._scope = scope
        self._edit: ConfigEdit | None = None

    def compose(self) -> ComposeResult:
        with Container(id="save-diff-dialog"):
            yield Label("Save configuration")
            with RadioSet(id="save-scope"):
                yield RadioButton(
                    "user  (~/.agent86/config.toml)",
                    value=self._scope == SCOPE_USER,
                    id="scope-user",
                )
                yield RadioButton(
                    "project  (./.agent86/config.toml)",
                    value=self._scope == SCOPE_PROJECT,
                    id="scope-project",
                )
            yield Static("", id="save-target")
            with VerticalScroll(id="save-diff-scroll"):
                yield Static("", id="save-diff-body", markup=False)
            with Horizontal(id="save-buttons"):
                yield Button("Save", id="save-confirm", variant="primary")
                yield Button("Cancel", id="save-cancel")

    def on_mount(self) -> None:
        self._refresh(self._scope)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "save-scope":
            return
        pressed_id = event.pressed.id
        self._refresh(SCOPE_PROJECT if pressed_id == "scope-project" else SCOPE_USER)

    def _refresh(self, scope: str) -> None:
        self._scope = scope
        confirm = self.query_one("#save-confirm", Button)
        body = self.query_one("#save-diff-body", Static)
        try:
            self._edit = plan_edit(scope, self._changes)
        except (ConfigWriteError, ValueError) as exc:
            self._edit = None
            confirm.disabled = True
            self.query_one("#save-target", Static).update("")
            body.update(str(exc))
            return
        confirm.disabled = False
        self.query_one("#save-target", Static).update(f"target: {self._edit.path}")
        body.update("No changes." if self._edit.is_noop else self._edit.diff)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-confirm" and self._edit is not None:
            self.dismiss(self._edit)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:  # Escape -> explicit None, never hangs
        self.dismiss(None)


__all__ = ["SaveDiffModal"]
