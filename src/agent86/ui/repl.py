"""The interactive REPL (v0.2).

Two loops behind one entry point:

- ``_rich_loop`` — a prompt_toolkit prompt with a persistent bottom status line and a hotkey
  (Shift+Tab) that cycles the approval mode, plus a spinner during processing. Turns run in a
  worker thread so the spinner can animate through model latency and tool execution; streamed
  output prints on the main thread.
- ``_plain_loop`` — the dependable stdlib ``input()`` loop (no prompt_toolkit), used when the
  terminal can't host the rich UI (piped stdin, ``--plain``, ``AGENT86_PLAIN``).

Both share command dispatch, so behavior is identical apart from presentation.
"""

from __future__ import annotations

import os
import queue
import sys
import threading

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent86 import __version__
from agent86.config import Config
from agent86.guardrails.policy import cycle_mode, parse_mode
from agent86.ui.spinner import Spinner
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
    """Derive a spinner label from a tool-announce line like '\\n[tool] name({...})'."""
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
        """Return 'exit', 'handled', or 'turn'."""
        if not line:
            return "handled"
        if line in ("/exit", "/quit"):
            console.print("[dim]bye[/dim]")
            return "exit"
        if line == "/help":
            _print_help()
            return "handled"
        if line == "/config":
            from agent86.cli import _show_config

            _show_config(self.cfg)
            return "handled"
        if line == "/models":
            from agent86.cli import _list_models

            _list_models(self.cfg)
            return "handled"
        if line == "/tools":
            console.print("[dim]tools:[/dim] " + ", ".join(self.harness.registry.names()))
            return "handled"
        if line == "/skills":
            if self.harness.skills:
                for s in self.harness.skills.values():
                    console.print(f"  [cyan]{s.name}[/cyan] - {s.description}")
            else:
                console.print("[dim]no skills discovered[/dim]")
            return "handled"
        if line == "/memory":
            self._show_memory()
            return "handled"
        if line == "/cost":
            self._show_cost()
            return "handled"
        if line == "/clear":
            self.state = self.harness.new_session()
            console.print("[dim]conversation cleared[/dim]")
            return "handled"
        if line == "/mode" or line.startswith("/mode "):
            self._set_mode(line[5:].strip())
            return "handled"
        if line == "/model" or line.startswith("/model "):
            self._set_model(line[6:].strip())
            return "handled"
        if line.startswith("/"):
            console.print(f"[dim]unknown command {line}[/dim]")
            return "handled"
        return "turn"

    def _set_mode(self, arg: str) -> None:
        if not arg:
            self._cycle_approval()
        else:
            mode = parse_mode(arg)
            if mode is None:
                console.print(f"[red]unknown mode '{arg}'[/red] (ask|auto|deny)")
                return
            self.harness.gate.mode = mode
            self.status.approval = mode.value
        console.print(f"[dim]approval mode: {self.harness.gate.mode.value}[/dim]")

    def _set_model(self, arg: str) -> None:
        p = self.harness.provider
        if not arg:
            console.print(f"[dim]current model:[/dim] {p.name}:{p.model}")
            console.print(
                "[dim]usage: /model <provider:model>  "
                "e.g. /model openrouter:anthropic/claude-3.7-sonnet[/dim]"
            )
            return
        from agent86.cognitive.base import ProviderError

        try:
            new = self.harness.set_model(arg)
        except (ProviderError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            return
        self._refresh_status()
        console.print(f"[dim]model:[/dim] [cyan]{new.name}:{new.model}[/cyan]")

    def _show_cost(self) -> None:
        u = self.state.usage
        console.print(
            f"[dim]steps[/dim] {self.state.step_count}  "
            f"[dim]in[/dim] {u.input_tokens}  [dim]out[/dim] {u.output_tokens} tok  "
            f"[dim]cost[/dim] ${u.cost_usd:.4f}"
        )

    def _show_memory(self) -> None:
        if self.harness.memory:
            c = self.harness.memory.store.counts()
            console.print(
                f"[dim]memory[/dim] sessions {c['sessions']}  episodes {c['episodes']}  "
                f"facts {c['memories']}  [dim]session[/dim] {self.state.session_id}"
            )
        else:
            console.print("[dim]memory is disabled[/dim]")

    # ---- loops -------------------------------------------------------- #

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

    def rich_loop(self) -> None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.key_binding import KeyBindings

        from agent86.cognitive.base import ProviderError
        from agent86.orchestration.loop import HarnessError

        kb = KeyBindings()

        @kb.add(self.cfg.ui.mode_cycle_key)
        def _cycle(event) -> None:  # noqa: ANN001
            self._cycle_approval()
            event.app.invalidate()

        session: PromptSession = PromptSession(key_bindings=kb)
        toolbar = self.status_line if self.cfg.ui.status_line else None
        refresh = 0.5 if self.cfg.ui.status_line else None

        while True:
            try:
                line = session.prompt("agent86> ", bottom_toolbar=toolbar, refresh_interval=refresh)
                line = line.strip()
            except EOFError:
                console.print("[dim]bye[/dim]")
                return
            except KeyboardInterrupt:
                continue

            action = self.dispatch(line)
            if action == "exit":
                return
            if action == "handled":
                continue

            console.print()  # blank line separating the question from the response
            try:
                self._run_turn_rich(line)
            except (ProviderError, HarnessError) as exc:
                console.print(f"\n[red]error:[/red] {exc}")
            except KeyboardInterrupt:
                console.print("\n[dim]interrupted[/dim]")
            except Exception as exc:  # a turn blew up — report it, but keep the rich UI alive
                console.print(f"\n[red]turn failed ({type(exc).__name__}):[/red] {exc}")
            console.print()  # blank line separating the response from the next prompt
            self._refresh_status()

    def _run_turn_rich(self, line: str) -> None:
        q: queue.Queue = queue.Queue()

        def approval_cb(tool_name: str, preview: str) -> bool:
            event = threading.Event()
            box: dict[str, bool] = {}
            q.put(("approval", tool_name, preview, event, box))
            event.wait()
            return box.get("ok", False)

        self.harness.gate.prompt = approval_cb

        def worker() -> None:
            try:
                for delta in self.harness.run_turn(line, self.state):
                    q.put(("delta", delta))
                q.put(("done",))
            except BaseException as exc:  # deliver any error to the main thread
                q.put(("error", exc))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        spinner = Spinner()
        spinning = False
        printed = False
        prefix_shown = False
        # The spinner draws with a carriage return, so it may only animate when the cursor is
        # on a fresh line — otherwise inter-token gaps (common on slow local models) would let
        # it overwrite the partial line of a multi-line response mid-stream.
        at_line_start = True
        label = "thinking"

        try:
            while True:
                try:
                    item = q.get(timeout=0.12)
                except queue.Empty:
                    if not spinning and at_line_start:
                        spinner.start(label)
                        spinning = True
                    continue

                if spinning:
                    spinner.stop()
                    spinning = False

                kind = item[0]
                if kind == "delta":
                    text = item[1].text
                    if text:
                        if not prefix_shown:
                            console.print("[bold cyan]agent86[/bold cyan] ", end="")
                            prefix_shown = True
                        _emit(text)
                        printed = True
                        at_line_start = text.endswith("\n")
                        label = _tool_label(text) or ("thinking" if text.strip() else label)
                elif kind == "approval":
                    _, tool_name, preview, event, box = item
                    console.print(
                        f"\n[yellow]approve[/yellow] [bold]{tool_name}[/bold] [dim]{preview}[/dim]"
                    )
                    try:
                        answer = input("  run it? [y/N] ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        answer = ""
                    box["ok"] = answer in ("y", "yes")
                    event.set()
                    at_line_start = True  # input() moved us to a fresh line
                    label = "thinking"
                elif kind == "done":
                    break
                elif kind == "error":
                    raise item[1]
        finally:
            if spinning:
                spinner.stop()

        if not printed:
            console.print("[bold cyan]agent86[/bold cyan] [dim](no response)[/dim]", end="")
        console.print()


def _print_help() -> None:
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_row("[cyan]/help[/cyan]", "Show this help")
    table.add_row("[cyan]/config[/cyan]", "Show the resolved configuration")
    table.add_row("[cyan]/models[/cyan]", "List configured models")
    table.add_row(
        "[cyan]/model <provider:model>[/cyan]", "Switch the active model for this session"
    )
    table.add_row("[cyan]/tools[/cyan]", "List available tools")
    table.add_row("[cyan]/skills[/cyan]", "List available skills")
    table.add_row("[cyan]/memory[/cyan]", "Show memory stats and session id")
    table.add_row("[cyan]/mode [ask|auto|deny][/cyan]", "Show/set approval mode (Shift+Tab cycles)")
    table.add_row("[cyan]/cost[/cyan]", "Show token usage and cost this session")
    table.add_row("[cyan]/clear[/cyan]", "Start a fresh conversation")
    table.add_row("[cyan]/exit[/cyan]", "Quit")
    console.print(table)


def _use_rich(cfg: Config, plain: bool) -> bool:
    if plain or os.getenv("AGENT86_PLAIN"):
        return False
    return bool(cfg.ui.status_line) and sys.stdin.isatty() and sys.stdout.isatty()


def run_repl(cfg: Config, resume: str | None = None, plain: bool = False) -> None:
    """Entry point: build the harness, print the banner, and run the best available loop."""
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

    if _use_rich(cfg, plain):
        try:
            repl.rich_loop()
            return
        except Exception as exc:  # prompt_toolkit couldn't run this terminal -> fall back
            console.print(
                f"[dim]rich UI unavailable ({type(exc).__name__}); using plain REPL.[/dim]"
            )
    repl.plain_loop()


__all__ = ["run_repl"]
