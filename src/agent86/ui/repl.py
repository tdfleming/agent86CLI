"""The interactive REPL.

One entry point, two surfaces:

- the full-screen Textual app (``agent86.tui.app``) — the default whenever ``[ui] tui`` is
  on and stdin/stdout are a TTY;
- ``_Repl.plain_loop`` — the dependable stdlib ``input()`` loop, used for ``--plain``,
  ``AGENT86_PLAIN``, piped stdin, or when the TUI can't be imported/started.

Both surfaces share the same ``_Repl`` (harness, session state, status), so ``run_repl``
builds it once and hands it to whichever loop runs, and both dispatch slash commands through
the one registry in ``agent86.tui.commands``. Only the presentation differs: the plain loop
prints each ``CommandResult.render`` to a Rich ``Console``, the TUI writes it to its
transcript.
"""

from __future__ import annotations

import os
import sys

from rich.console import Console
from rich.panel import Panel

from agent86 import __version__
from agent86.config import Config
from agent86.guardrails.policy import cycle_mode
from agent86.ui.status import StatusState, context_window_for, format_status_line

console = Console()


def _emit(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _banner(cfg: Config) -> Panel:
    body = (
        f"[bold]agent86[/bold] [dim]v{__version__}[/dim]\n"
        f"model    [cyan]{cfg.model.default}[/cyan]"
        f"   router [cyan]{cfg.model.router}[/cyan]\n"
        f"sandbox  [cyan]{cfg.sandbox.mode}[/cyan]"
        f"   approval [cyan]{cfg.guardrails.approval.value}[/cyan]\n"
        f"[dim]Type /help for commands, /exit to quit.[/dim]"
    )
    return Panel(body, title="agentic harness", border_style="cyan", expand=False)


def _tool_label(text: str) -> str | None:
    """Derive a progress label from a tool-announce line like '\\n[tool] name({...})'.

    Shared with ``agent86.tui.turn_bridge``, which labels its working indicator the same way.
    """
    if "[tool] " in text and "(" in text and "->" not in text:
        name = text.split("[tool] ", 1)[1].split("(", 1)[0].strip()
        if name:
            return f"running {name}"
    return None


class _Repl:
    def __init__(self, cfg: Config, resume: str | None, harness=None):  # noqa: ANN001
        from agent86.orchestration.loop import Harness
        from agent86.orchestration.state import AgentState

        self.cfg = cfg
        self.harness = harness if harness is not None else Harness(cfg)
        state: AgentState | None = None
        if resume:
            state = self.harness.resume(resume)
            if state is None:
                console.print(f"[yellow]No session '{resume}' found; starting fresh.[/yellow]")
            else:
                console.print(
                    f"[dim]resumed session {state.session_id} "
                    f"({len(state.messages)} messages)[/dim]"
                )
        # Past this point state is always an AgentState (never None) — annotate it so, which
        # removes the union-attr / arg-type mypy errors on every self.state access below.
        self.state: AgentState = state if state is not None else self.harness.new_session()

        p = self.harness.provider
        self.status = StatusState(
            model=p.model,
            used_tokens=0,
            window=context_window_for(f"{p.name}:{p.model}", cfg),
            output_tokens=0,
            cost_usd=0.0,
            sandbox=cfg.sandbox.mode,
            approval=self.harness.gate.mode.value,
        )

    # ---- status ------------------------------------------------------- #

    def status_line(self) -> str:
        return format_status_line(self.status)

    def _refresh_status(self) -> None:
        p = self.harness.provider
        self.status.model = p.model
        self.status.window = context_window_for(f"{p.name}:{p.model}", self.cfg)
        self.status.used_tokens = self.state.steps[-1].usage.input_tokens if self.state.steps else 0
        self.status.output_tokens = self.state.usage.output_tokens
        self.status.cost_usd = self.state.usage.cost_usd
        self.status.approval = self.harness.gate.mode.value
        self.status.working = False

    def _cycle_approval(self) -> None:
        self.harness.gate.mode = cycle_mode(self.harness.gate.mode)
        self.status.approval = self.harness.gate.mode.value

    def print_notes(self) -> None:
        from rich.markup import escape

        if self.harness.memory_note:
            console.print(f"[dim]memory: {escape(self.harness.memory_note)}[/dim]")
        if self.harness.mcp_note:
            console.print(f"[dim]mcp: {escape(self.harness.mcp_note)}[/dim]")
        if self.harness.sandbox_note:
            console.print(f"[yellow]sandbox: {escape(self.harness.sandbox_note)}[/yellow]")
        if self.harness.skills:
            console.print(f"[dim]skills: {', '.join(self.harness.skills)}[/dim]")
        console.print(f"[dim]session {self.state.session_id}[/dim]")

    # ---- command dispatch --------------------------------------------- #

    def dispatch(self, line: str) -> str:
        """Dispatch one input line; returns 'exit', 'handled', or 'turn'.

        Every slash-command implementation lives in the shared registry
        (``agent86.tui.commands``) so the plain loop and the TUI can't drift. This method
        only turns the returned :class:`~agent86.tui.commands.CommandResult` into console
        output: ``render`` is a Rich renderable or a markup string, which ``Console.print``
        handles either way. Commands that need a TUI surface (``/config model``,
        ``/config mcp``) already return a plain-mode explanation from the registry.
        """
        from agent86.tui.commands import handle_command

        result = handle_command(self, line)
        if result.action == "exit":
            console.print("[dim]bye[/dim]")
            return "exit"
        if result.render is not None:
            console.print(result.render)
        # "noop" (an empty line) is nothing to run and nothing to say.
        return "turn" if result.action == "turn" else "handled"

    # ---- loop --------------------------------------------------------- #

    def plain_loop(self) -> None:
        from agent86.cognitive.base import ProviderError
        from agent86.orchestration.loop import HarnessError

        while True:
            try:
                line = input("agent86> ").strip()
            except EOFError:
                console.print("\n[dim]bye[/dim]")
                return
            except KeyboardInterrupt:
                console.print("")
                continue

            action = self.dispatch(line)
            if action == "exit":
                return
            if action == "handled":
                continue

            console.print()  # blank line separating the question from the response
            console.print("[bold cyan]agent86[/bold cyan] ", end="")
            printed = False
            try:
                for delta in self.harness.run_turn(line, self.state):
                    if delta.text:
                        _emit(delta.text)
                        printed = True
                if not printed:
                    console.print("[dim](no response)[/dim]", end="")
                console.print()
            except (ProviderError, HarnessError) as exc:
                console.print(f"\n[red]error:[/red] {exc}")
            except KeyboardInterrupt:
                console.print("\n[dim]interrupted[/dim]")
            console.print()  # blank line separating the response from the next prompt
            self._refresh_status()


def _use_tui(cfg: Config, plain: bool) -> bool:
    """Whether to launch the Textual TUI rather than the plain loop."""
    if plain or os.getenv("AGENT86_PLAIN"):
        return False
    return bool(cfg.ui.tui) and sys.stdin.isatty() and sys.stdout.isatty()


def run_repl(cfg: Config, resume: str | None = None, plain: bool = False) -> None:
    """Entry point: build the harness once, then run the TUI or the plain loop on it."""
    from agent86.cognitive.base import ProviderError

    console.print(_banner(cfg))
    try:
        repl = _Repl(cfg, resume)
    except ProviderError as exc:
        console.print(f"[red]Cannot start:[/red] {exc}")
        console.print(
            "[dim]Fix the key/config or choose another model with "
            "`agent86 --model provider:model`, then retry.[/dim]"
        )
        return

    repl.print_notes()

    if _use_tui(cfg, plain):
        try:
            from agent86.tui.app import run_tui  # lazy: textual imported only here
        except ImportError as exc:
            console.print(f"[dim]TUI unavailable ({type(exc).__name__}); using plain REPL.[/dim]")
        else:
            try:
                run_tui(repl)
                return
            except Exception as exc:  # terminal can't host Textual, etc. -> fall back
                console.print(
                    f"[dim]TUI could not start ({type(exc).__name__}); using plain REPL.[/dim]"
                )
    repl.plain_loop()


__all__ = ["run_repl"]
