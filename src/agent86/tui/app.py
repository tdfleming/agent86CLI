"""The full-screen `Agent86App(App)` — the TUI shell (TUI-01, TUI-02, TUI-05).

Composes a scrollable transcript, a prompt input, and a live status footer; runs turns on a
Textual thread worker (the harness's `run_turn` generator stays synchronous, per CONTEXT.md
lock), streams deltas into the transcript, keeps the footer live during processing, and pops a
modal to resolve tool-approval requests. Textual is only ever imported by this module and by
whatever calls `run_tui` — never at `cli.py` module-import time (RESEARCH Pitfall 1).
"""

from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, RichLog, Static

from agent86.config import Config
from agent86.tui.commands import handle_command, startup_notes
from agent86.tui.messages import ApprovalRequest, ToolAnnounce, TurnDelta, TurnDone, TurnError
from agent86.tui.screens.approval import ApprovalModal
from agent86.tui.turn_bridge import run_turn_worker
from agent86.tui.widgets.status_footer import StatusFooter

__all__ = ["Agent86App", "run_tui"]


class Agent86App(App):
    """The default interactive UI: transcript + prompt + live status footer."""

    BINDINGS = [Binding("shift+tab", "cycle_mode", "cycle approval mode")]

    CSS = """
    #transcript {
        height: 1fr;
    }
    #stream {
        height: auto;
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
        yield Input(id="prompt", placeholder="agent86> ")
        yield StatusFooter(id="status")

    def on_mount(self) -> None:
        self.query_one("#status", StatusFooter).status = self.repl.status
        log = self.query_one("#transcript", RichLog)
        for note in startup_notes(self.repl):
            log.write(f"[dim]{note}[/dim]")
        self.query_one("#prompt", Input).focus()

    # ---- input submission ------------------------------------------------ #

    def on_input_submitted(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        event.input.value = ""
        if not line:
            return

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
        self.repl._cycle_approval()
        self.query_one("#status", StatusFooter).status = self.repl.status


def run_tui(cfg: Config, resume: str | None = None) -> None:
    """Build the harness/state/status (reusing `_Repl`) and run `Agent86App`."""
    from agent86.ui.repl import _Repl

    repl = _Repl(cfg, resume)
    Agent86App(repl).run()
