"""The multi-line prompt — a ``TextArea`` that behaves like a coding agent's composer.

The TUI's prompt started life as a single-line ``Input``, which is wrong for the job: a
pasted stack trace collapsed onto one line, a multi-paragraph instruction was impossible to
compose, and nothing remembered what you asked last time. This widget keeps the ``Input``
*interface* (``.value``, ``.clear()``, a ``Submitted`` message carrying ``.value``) so the
app can swap it in, and changes the behaviour underneath:

- **Enter** submits (posting :class:`PromptInput.Submitted`), rather than inserting a newline;
- **Shift+Enter** / **Ctrl+J** insert a newline, so a prompt can be many lines;
- **Up/Down** walk the shared prompt history — but only from the first/last line, so inside a
  multi-line draft they still move the cursor, which is what the fingers expect;
- **Escape** clears the draft (and abandons any history navigation in progress);
- the widget grows with its content up to 8 rows and then scrolls, so a long paste can never
  push the transcript or the status footer off the screen.

History is the same :class:`~agent86.ui.history.PromptHistory` the plain loop appends to, so
the two surfaces share one file. Recording happens here, on submit, which means the app
wiring gets persistence for free.
"""

from __future__ import annotations

from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import TextArea
from textual.widgets.text_area import EditResult

from agent86.ui.history import PromptHistory

#: Tallest the prompt grows before it starts scrolling instead (rows).
MAX_ROWS = 8


class PromptInput(TextArea):
    """A multi-line prompt with history navigation. Drop-in for the prompt ``Input``."""

    DEFAULT_CSS = f"""
    PromptInput {{
        height: auto;
        min-height: 1;
        max-height: {MAX_ROWS};
        border: none;
        padding: 0;
    }}
    """

    #: Up/Down are bound here so they reach `action_history_*` before `TextArea`'s own
    #: cursor bindings; each action falls back to the cursor move when the cursor is not on
    #: the edge line, so nothing is taken away from multi-line editing.
    BINDINGS = [
        Binding("up", "history_prev", "history back", show=False),
        Binding("down", "history_next", "history forward", show=False),
    ]

    class Submitted(Message):
        """Posted when the user presses Enter. Mirrors ``Input.Submitted``.

        ``input`` is an alias of ``prompt_input`` purely so existing handlers written
        against ``Input.Submitted`` (``event.input.id``, ``event.input.value = ""``) keep
        working unchanged when this widget is swapped in.
        """

        def __init__(self, prompt_input: PromptInput, value: str) -> None:
            super().__init__()
            self.prompt_input = prompt_input
            self.value = value

        @property
        def control(self) -> PromptInput:
            return self.prompt_input

        @property
        def input(self) -> PromptInput:
            return self.prompt_input

    def __init__(
        self,
        *,
        history: PromptHistory | None = None,
        placeholder: str = "agent86> ",
        id: str | None = None,  # noqa: A002 - matches Textual's widget kwarg
        **kwargs,
    ) -> None:
        # tab_behavior="focus": Tab moves on rather than indenting — a prompt is not an
        # editor, and Tab is how you get out of it.
        super().__init__(
            "",
            soft_wrap=True,
            tab_behavior="focus",
            placeholder=placeholder,
            id=id,
            **kwargs,
        )
        self._history = history
        #: Index into the history snapshot while navigating; None = editing a fresh draft.
        self._hist_index: int | None = None
        #: The draft that was on screen when navigation started, restored on the way back.
        self._draft = ""

    # ---- Input-compatible surface --------------------------------------- #

    @property
    def value(self) -> str:
        """The current text. ``Input``-compatible alias of ``TextArea.text``."""
        return self.text

    @value.setter
    def value(self, new_value: str) -> None:
        self._set_text(new_value or "")
        self._reset_history()

    def clear(self) -> EditResult:
        """Empty the prompt and abandon any history navigation in progress."""
        self._reset_history()
        return super().clear()

    # ---- key handling ---------------------------------------------------- #

    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        if key == "enter":
            event.stop()
            event.prevent_default()
            self._submit()
            return
        # Two spellings of "newline, don't send": Shift+Enter where the terminal reports it
        # (kitty/modern protocols), Ctrl+J everywhere else.
        if key in ("shift+enter", "ctrl+j"):
            event.stop()
            event.prevent_default()
            self.insert("\n", maintain_selection_offset=False)
            return
        if key == "escape":
            event.stop()
            event.prevent_default()
            self.clear()
            return
        # Any other key is ordinary editing, and ends history navigation: what's on screen
        # is now the user's draft, not a recalled entry.
        if event.is_printable or key in ("backspace", "delete"):
            self._hist_index = None
        await super()._on_key(event)

    def _submit(self) -> None:
        value = self.text.strip()
        if self._history is not None:
            self._history.append(value)
        self._reset_history()
        # Not cleared here: `Input` doesn't clear itself either, and the app decides (it has
        # to keep the line out of the prompt only once it has accepted it).
        self.post_message(self.Submitted(self, value))

    # ---- history navigation ---------------------------------------------- #

    def action_history_prev(self) -> None:
        """Older entry — or just move the cursor up when there's a line above it."""
        entries = self._entries()
        if self.cursor_location[0] > 0 or not entries:
            self.action_cursor_up()
            return
        if self._hist_index is None:
            self._draft = self.text
            self._hist_index = len(entries) - 1
        elif self._hist_index > 0:
            self._hist_index -= 1
        else:
            return  # already at the oldest entry; stay put rather than wrap
        self._set_text(entries[self._hist_index])

    def action_history_next(self) -> None:
        """Newer entry, then back to the draft — or move the cursor down."""
        entries = self._entries()
        if self.cursor_location[0] < self.document.line_count - 1 or self._hist_index is None:
            self.action_cursor_down()
            return
        if self._hist_index < len(entries) - 1:
            self._hist_index += 1
            self._set_text(entries[self._hist_index])
            return
        # Past the newest entry: hand the half-typed draft back.
        self._hist_index = None
        draft, self._draft = self._draft, ""
        self._set_text(draft)

    def _entries(self) -> list[str]:
        return self._history.entries if self._history is not None else []

    def _set_text(self, text: str) -> None:
        """Replace the content and park the cursor at the end (where typing continues)."""
        self.load_text(text)
        self.move_cursor(self.document.end)

    def _reset_history(self) -> None:
        self._hist_index = None
        self._draft = ""


__all__ = ["MAX_ROWS", "PromptInput"]
