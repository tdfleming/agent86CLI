"""Pick a past session to resume.

``/resume`` with no argument opens this: the recent sessions, newest first, narrowed by
typing. Same shape as ``CatalogPickerModal`` in ``provider_manager`` — a filter ``Input``
above an ``OptionList``, Escape to cancel — because a user who has learned one picker in
this app has learned all of them. Dismisses with the chosen ``session_id``, or None.

Rows are built from :class:`~agent86.memory.store.SessionInfo` and labelled by
``agent86.tui.commands.session_label`` — the same function ``/sessions`` prints with, so the
picker and the table can't drift. A title is the first thing the user ever typed into that
session, so it is *their* text: options are built as Rich ``Text``, never markup, so a prompt
containing ``[bold]`` can't style (or break) the list.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from agent86.memory.store import SessionInfo
from agent86.tui.commands import session_label
from agent86.tui.screens._shutdown import maybe_one


class SessionPickerModal(ModalScreen[str | None]):
    """Choose one of ``sessions`` to resume. Dismisses with its id, or None."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    #: Carried on the screen rather than added to the App's CSS, so the picker looks right
    #: the moment it's pushed; an app-level `#session-picker-dialog` rule still wins.
    DEFAULT_CSS = """
    SessionPickerModal #session-picker-dialog {
        width: 80%;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    SessionPickerModal #session-list {
        max-height: 15;
    }
    """

    def __init__(self, sessions: Sequence[SessionInfo]) -> None:
        super().__init__()
        self._sessions = list(sessions)
        self._focus_retried = False

    def compose(self) -> ComposeResult:
        with Container(id="session-picker-dialog"):
            yield Label("Resume a session")
            yield Input(
                id="session-filter",
                placeholder=(
                    "type to filter…" if self._sessions else "no saved sessions yet"
                ),
            )
            yield OptionList(*self._options(self._sessions), id="session-list")

    def on_mount(self) -> None:
        self._focus_filter()

    def _focus_filter(self) -> None:
        """Focus the filter, tolerating a dialog whose children aren't mounted.

        See ``screens/_shutdown``: a modal pushed from a worker result can arrive inside the
        shutdown window, where ``compose``'s children are never registered and an unguarded
        ``query_one`` raises ``NoMatches`` straight out of ``on_mount``.
        """
        found = maybe_one(self, "#session-filter", Input)
        if found is not None:
            found.focus()
        elif not self._focus_retried and self.is_running:
            self._focus_retried = True
            self.call_after_refresh(self._focus_filter)

    @staticmethod
    def _options(sessions: Sequence[SessionInfo]) -> list[Option]:
        # Text(), not a markup string: session titles are user prompts.
        return [Option(Text(session_label(s)), id=s.session_id) for s in sessions]

    def _filtered(self, text: str) -> list[SessionInfo]:
        needle = text.strip().lower()
        if not needle:
            return self._sessions
        return [
            s
            for s in self._sessions
            if needle in (s.title or "").lower() or needle in s.session_id.lower()
        ]

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "session-filter":
            return
        option_list = maybe_one(self, "#session-list", OptionList)
        if option_list is None:
            return
        option_list.clear_options()
        matches = self._filtered(event.value)
        option_list.add_options(self._options(matches))
        if matches:
            option_list.highlighted = 0

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the filter takes the only match — otherwise it cancels.

        ``event.stop()`` first: unconsumed, this bubbles to the App and is dispatched as a
        typed prompt line (the same leak CatalogPickerModal guards against).
        """
        event.stop()
        matches = self._filtered(event.value or "")
        if len(matches) == 1:
            self.dismiss(matches[0].session_id)
            return
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id:
            self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["SessionPickerModal"]
