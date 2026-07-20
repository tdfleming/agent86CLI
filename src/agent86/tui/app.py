"""The full-screen `Agent86App(App)` — the TUI shell (TUI-01, TUI-02, TUI-05).

Composes a scrollable transcript, a prompt input, and a live status footer; runs turns on a
Textual thread worker (the harness's `run_turn` generator stays synchronous, per CONTEXT.md
lock), streams deltas into the transcript, keeps the footer live during processing, and pops a
modal to resolve tool-approval requests. Textual is only ever imported by this module and by
whatever calls `run_tui` — never at `cli.py` module-import time (RESEARCH Pitfall 1).
"""

from __future__ import annotations

from textual import work
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from agent86.config import Config
from agent86.tui.commands import COMMANDS, find_command, handle_command, startup_notes
from agent86.tui.messages import ApprovalRequest, ToolAnnounce, TurnDelta, TurnDone, TurnError
from agent86.tui.screens.approval import ApprovalModal
from agent86.tui.screens.mode_picker import ModePickerModal
from agent86.tui.screens.model_picker import ModelPickerModal, model_choices
from agent86.tui.turn_bridge import run_turn_worker
from agent86.tui.widgets.status_footer import StatusFooter

__all__ = ["Agent86App", "run_tui"]


class Agent86App(App):
    """The default interactive UI: transcript + prompt + live status footer."""

    BINDINGS = [
        Binding("shift+tab", "cycle_mode", "cycle approval mode", priority=True),
        Binding("up", "palette_up", show=False, priority=True),
        Binding("down", "palette_down", show=False, priority=True),
        Binding("escape", "palette_dismiss", show=False, priority=True),
    ]

    CSS = """
    #transcript {
        height: 1fr;
    }
    #stream {
        height: auto;
    }
    #palette {
        display: none;
        max-height: 10;
        border: round $accent;
    }
    #status {
        dock: bottom;
    }
    """

    def __init__(self, repl) -> None:  # noqa: ANN001
        super().__init__()
        self.repl = repl
        self._stream_buf = ""

    # ---- composition ---------------------------------------------------- #

    def compose(self) -> ComposeResult:
        yield RichLog(id="transcript", markup=True, wrap=True, highlight=False)
        yield Static(id="stream")
        yield OptionList(id="palette")
        yield Input(id="prompt", placeholder="agent86> ")
        yield StatusFooter(id="status")

    def on_mount(self) -> None:
        self.query_one("#status", StatusFooter).status = self.repl.status
        log = self.query_one("#transcript", RichLog)
        for note in startup_notes(self.repl):
            log.write(f"[dim]{note}[/dim]")
        self.query_one("#palette", OptionList).display = False
        self.query_one("#prompt", Input).focus()

    # ---- palette ----------------------------------------------------------- #

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "prompt":
            return
        self._sync_palette(event.value)

    def _sync_palette(self, text: str) -> None:
        palette = self.query_one("#palette", OptionList)
        if not text.startswith("/") or " " in text:
            palette.display = False
            return
        matches = [c for c in COMMANDS if c.name.startswith(text)]
        palette.display = bool(matches)
        if matches:
            palette.clear_options()
            palette.add_options(
                Option(f"{c.name}  [dim]{c.description}[/dim]", id=c.name) for c in matches
            )
            palette.highlighted = 0

    # ---- input submission ------------------------------------------------ #

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Approach B (02-02-SUMMARY.md): no permanent priority `enter` Binding is registered at
        # the App level, so Input.Submitted still fires normally when the palette is closed. An
        # open palette consumes this Enter itself, before the typed-line dispatch below.
        palette = self.query_one("#palette", OptionList)
        if palette.display:
            self._select_palette()
            return
        line = event.value.strip()
        event.input.value = ""
        if not line:
            return
        self._dispatch_line(line)

    def _dispatch_line(self, line: str) -> None:
        """Run one command/turn line through the existing execution path.

        Shared by typed Input submission and picker-chained selections (palette / /model /
        /mode) so both paths behave identically.
        """
        log = self.query_one("#transcript", RichLog)
        log.write(f"[bold]> {line}[/bold]")

        result = handle_command(self.repl, line)
        if result.action == "exit":
            self.exit()
            return
        if result.action == "turn":
            self._start_turn(line)
            return
        # "handled" / "noop"
        if result.render is not None:
            log.write(result.render)
        self.query_one("#status", StatusFooter).status = self.repl.status

    # ---- palette selection + picker chaining -------------------------------- #

    def action_palette_up(self) -> None:
        # These bindings are registered with priority=True (App-level, checked before the
        # focused widget's own bindings — see RESEARCH/02-02-SUMMARY.md). When the palette is
        # hidden — e.g. while a ModePickerModal/ModelPickerModal is on top and its RadioSet /
        # OptionList owns up/down/escape — raising SkipAction lets the key event fall through to
        # that widget's own binding instead of being silently swallowed here.
        palette = self.query_one("#palette", OptionList)
        if not palette.display:
            raise SkipAction()
        palette.action_cursor_up()

    def action_palette_down(self) -> None:
        palette = self.query_one("#palette", OptionList)
        if not palette.display:
            raise SkipAction()
        palette.action_cursor_down()

    def action_palette_dismiss(self) -> None:
        palette = self.query_one("#palette", OptionList)
        if not palette.display:
            raise SkipAction()
        palette.display = False

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "palette":
            self._select_palette()

    def _select_palette(self) -> None:
        palette = self.query_one("#palette", OptionList)
        highlighted = palette.highlighted
        if highlighted is None:
            palette.display = False
            return
        option = palette.get_option_at_index(highlighted)
        name = option.id
        palette.display = False
        prompt = self.query_one("#prompt", Input)
        prompt.value = ""
        entry = find_command(name)
        if entry is not None:
            self._run_or_chain(entry)

    def _run_or_chain(self, entry) -> None:  # noqa: ANN001
        if entry.needs_choice == "mode":
            self.push_screen(
                ModePickerModal(self.repl.harness.gate.mode.value), self._on_mode_picked
            )
        elif entry.needs_choice == "model":
            choices = model_choices(self.repl.cfg)
            if not choices:
                prompt = self.query_one("#prompt", Input)
                prompt.value = "/model "
                prompt.focus()
                return
            self.push_screen(ModelPickerModal(choices), self._on_model_picked)
        else:
            self._dispatch_line(entry.name)

    def _on_mode_picked(self, value: str | None) -> None:
        if value is not None:
            self._dispatch_line(f"/mode {value}")

    def _on_model_picked(self, value: str | None) -> None:
        if value is not None:
            self._dispatch_line(f"/model {value}")

    # ---- turn worker ------------------------------------------------------ #

    def _start_turn(self, line: str) -> None:
        self.repl.status.working = True
        self.repl.status.phase = "thinking"
        self.query_one("#status", StatusFooter).status = self.repl.status
        self.query_one("#prompt", Input).disabled = True
        self._stream_buf = ""
        self._run_turn(line)

    @work(thread=True, exclusive=True)
    def _run_turn(self, line: str) -> None:
        run_turn_worker(self.repl.harness, line, self.repl.state, self.post_message)

    # ---- message handlers (main thread) ------------------------------------ #

    def on_turn_delta(self, message: TurnDelta) -> None:
        self._stream_buf += message.text
        self.query_one("#stream", Static).update(self._stream_buf)
        self.repl.status.working = True
        self.repl.status.phase = "thinking"
        self.query_one("#status", StatusFooter).status = self.repl.status
        self.query_one("#transcript", RichLog).scroll_end(animate=False)

    def on_tool_announce(self, message: ToolAnnounce) -> None:
        self._flush_stream()
        self.query_one("#transcript", RichLog).write(message.text.strip())
        self.repl.status.working = True
        self.repl.status.phase = message.label
        self.query_one("#status", StatusFooter).status = self.repl.status

    def on_approval_request(self, message: ApprovalRequest) -> None:
        def _resolve(approved: bool | None) -> None:
            message.box["ok"] = bool(approved)
            message.event.set()

        self.push_screen(ApprovalModal(message.tool_name, message.preview), _resolve)

    def on_turn_done(self, message: TurnDone) -> None:
        self._flush_stream(prefix="[bold cyan]agent86[/bold cyan] ")
        self.repl._refresh_status()
        self.query_one("#status", StatusFooter).status = self.repl.status
        self._reenable_input()

    def on_turn_error(self, message: TurnError) -> None:
        self._flush_stream()
        self.query_one("#transcript", RichLog).write(f"[red]error:[/red] {message.error}")
        self.repl._refresh_status()
        self.query_one("#status", StatusFooter).status = self.repl.status
        self._reenable_input()

    def _flush_stream(self, prefix: str = "") -> None:
        if self._stream_buf:
            self.query_one("#transcript", RichLog).write(f"{prefix}{self._stream_buf}")
        self.query_one("#stream", Static).update("")
        self._stream_buf = ""

    def _reenable_input(self) -> None:
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = False
        prompt.focus()

    # ---- bindings ----------------------------------------------------------- #

    def action_cycle_mode(self) -> None:
        # `shift+tab` is a priority binding (App-level, checked before focus-traversal and the
        # focused widget's own bindings — see RESEARCH/02-02-SUMMARY.md). While a modal
        # (ApprovalModal / ModePickerModal / ModelPickerModal) is pushed, Shift+Tab must fall
        # through to that screen's own focus/traversal handling instead of cycling the approval
        # mode underneath it — mirrors the `action_palette_up`/`_down`/`_dismiss` SkipAction
        # pattern above.
        if len(self.screen_stack) > 1:
            raise SkipAction()
        self.repl._cycle_approval()
        self.query_one("#status", StatusFooter).status = self.repl.status


def run_tui(cfg: Config, resume: str | None = None) -> None:
    """Build the harness/state/status (reusing `_Repl`) and run `Agent86App`."""
    from agent86.ui.repl import _Repl

    repl = _Repl(cfg, resume)
    Agent86App(repl).run()
