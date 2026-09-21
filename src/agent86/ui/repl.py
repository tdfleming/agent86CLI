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
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from agent86 import __version__
from agent86.config import Config
from agent86.guardrails.policy import cycle_mode
from agent86.ui.history import PromptHistory, build_history
from agent86.ui.status import (
    StatusState,
    context_window_for,
    format_last_turn,
    format_status_line,
)

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


#: Prefixes of the harness's own mid-turn notices. The loop yields these as ordinary text
#: deltas (``[compacted 12 messages]``, ``[continuing …]``), but they are the HARNESS
#: talking about the conversation, not the model answering — so both surfaces set them
#: apart (dim, on their own line) instead of letting them read as model speech.
NOTICE_PREFIXES: tuple[str, ...] = (
    "[compacted",
    "[compacting",
    # The drop fallback: "[compaction failed; dropped N messages]".
    "[compaction",
    "[continuation",
    "[continuing",
)


def notice_text(text: str) -> str | None:
    """The notice carried by this delta, stripped — or None if it isn't one.

    Shared by the plain loop and ``agent86.tui.turn_bridge`` so the two surfaces classify
    deltas identically.
    """
    stripped = text.strip()
    if stripped.startswith(NOTICE_PREFIXES):
        return stripped
    return None


#: Most lines of a preview `detail` shown before the y/N question. A 4000-line diff is not
#: more informative than its first 40 lines plus the file it applies to — and it would scroll
#: the question itself off the terminal, which is the one thing that must stay visible.
APPROVAL_DETAIL_LINES = 40


def approval_prompt(tool_name: str, preview: str) -> bool:
    """Ask on stdin whether one side-effecting tool call may run. Default: **no**.

    The ``ApprovalPrompt`` the plain loop (and a TTY-attached ``agent86 run``) installs on
    the gate. Without one, ``ApprovalGate`` has no way to ask and declines every
    side-effecting call — which is right for CI and wrong for a person sitting at a
    terminal.

    ``preview`` is an :class:`~agent86.guardrails.policy.ApprovalPreview`: a ``str`` whose
    value is the one-line argument summary, carrying the tool's own ``detail`` (a unified
    diff for a write, the full command for a shell call) and a Pygments ``lexer`` for it.
    The detail is printed ABOVE the question — approving a write sight-unseen is the thing
    this prompt exists to prevent. A plain ``str`` from a test double simply has no detail.
    """
    detail = getattr(preview, "detail", None) or str(preview)
    lexer = getattr(preview, "lexer", None)
    console.print()
    console.print(_approval_detail(detail, lexer))
    # Text(), never markup: the tool name may come from an MCP server and the summary is the
    # model's own JSON.
    console.print(Text.assemble(("approve ", "bold yellow"), (f"{tool_name}?", "bold")))
    try:
        answer = input("  [y/N] ")
    except (EOFError, KeyboardInterrupt):
        # stdin went away (or the user hit Ctrl+C at the question): decline, which is the
        # safe answer whenever nobody is there to give one.
        console.print("[dim]declined[/dim]")
        return False
    return answer.strip().lower() in ("y", "yes")


def _approval_detail(detail: str, lexer: str | None):  # noqa: ANN202 - Rich renderable
    """The preview body, syntax-highlighted when the tool named a lexer, capped either way."""
    body = _cap_lines(detail, APPROVAL_DETAIL_LINES)
    if lexer:
        from rich.syntax import Syntax

        try:
            # Built from the raw string, so the detail is highlighted without ever being
            # parsed as console markup.
            return Syntax(body, lexer, theme="ansi_dark", word_wrap=True,
                          background_color="default")
        except Exception:  # noqa: BLE001 - unknown lexer: plain text still tells the truth
            pass
    return Text(body)


def _cap_lines(text: str, limit: int) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    return "\n".join([*lines[:limit], f"… truncated ({len(lines) - limit} more lines)"])


def install_approval_prompt(harness) -> bool:  # noqa: ANN001 - Harness, kept import-free
    """Give ``harness``'s gate a stdin prompt when there is a terminal to ask at.

    Returns whether one was installed. Non-interactive callers (a piped stdin, CI, a cron
    job) deliberately get nothing: the gate then declines every side-effecting call under
    ``ask``, and ``--yes`` / ``approval = "auto"`` is the explicit way to say otherwise. A
    gate that already has a prompt (the TUI's bridge) is left alone.
    """
    if harness.gate.prompt is not None:
        return False
    try:
        interactive = sys.stdin.isatty()
    except (AttributeError, ValueError):  # a detached/closed stdin
        interactive = False
    if not interactive:
        return False
    harness.gate.prompt = approval_prompt
    return True


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
        # Collected, not printed: under the TUI stdout is behind the alternate screen, so
        # anything printed here would surface only after the user quits.
        self.resume_notes: list[str] = []
        state: AgentState | None = None
        if resume:
            state = self.harness.resume(resume)
            if state is None:
                self.resume_notes.append(f"no session '{resume}' found; starting fresh")
            else:
                # The stored title (the session's first user message) is what tells the user
                # WHICH conversation they just walked back into — an id alone doesn't.
                title = None
                if self.harness.memory:
                    title = self.harness.memory.store.session_title(state.session_id)
                note = f"resumed session {state.session_id} ({len(state.messages)} messages)"
                self.resume_notes.append(f"{note} - {title}" if title else note)
        # Past this point state is always an AgentState (never None) — annotate it so, which
        # removes the union-attr / arg-type mypy errors on every self.state access below.
        self.state: AgentState = state if state is not None else self.harness.new_session()

        p = self.harness.provider
        # `config_ref`, not `f"{p.name}:{p.model}"`: the adapter behind `openrouter:` is
        # named "openai", and this ref is what the window lookup and the price table key on.
        self.status = StatusState(
            model=p.model,
            model_ref=p.config_ref,
            used_tokens=0,
            window=self._context_window(p.config_ref),
            output_tokens=0,
            cost_usd=0.0,
            sandbox=cfg.sandbox.mode,
            approval=self.harness.gate.mode.value,
        )

        # Built on first use, not here: constructing a _Repl (which every test does) must not
        # read the user's real history file, and a `run` one-shot never needs it at all.
        self._history: PromptHistory | None = None

        from agent86.tui.commands import startup_notes  # textual-free; see module docstring

        #: Launch notes — resume, memory/mcp/sandbox/skills, session id — already
        #: markup-escaped. The plain path prints these (``print_notes``); the TUI renders
        #: them into its transcript on mount.
        self.startup_notes: list[str] = startup_notes(self)

    # ---- shared prompt history ---------------------------------------- #

    @property
    def history(self) -> PromptHistory:
        """The prompt history both surfaces record into (``[ui] history_file``).

        The plain loop can only *append* — stdlib ``input()`` has no line editor to navigate
        with — but appending is what keeps one shared file honest: a prompt typed under
        ``--plain`` is waiting on Up the next time the TUI starts.
        """
        if self._history is None:
            self._history = build_history(self.cfg)
        return self._history

    # ---- status ------------------------------------------------------- #

    def status_line(self) -> str:
        return format_status_line(self.status)

    def _context_window(self, ref: str) -> int:
        """The real window if the harness knows it, else this module's per-model table.

        The harness resolves the window it actually budgets against (provider settings, config
        overrides, live model metadata); when it exposes that, the gauge must agree with it
        rather than with a second, independent guess.
        """
        window = getattr(self.harness, "context_window", None)
        if callable(window):  # a method rather than a property -> ask it
            try:
                window = window()
            except Exception:  # noqa: BLE001 - never let the status line break a turn
                window = None
        try:
            if window and int(window) > 0:
                return int(window)
        except (TypeError, ValueError):
            pass
        return context_window_for(ref, self.cfg)

    def _refresh_status(self) -> None:
        p = self.harness.provider
        ref = p.config_ref
        self.status.model = p.model
        self.status.model_ref = ref
        self.status.window = self._context_window(ref)
        self.status.used_tokens = self.state.steps[-1].usage.input_tokens if self.state.steps else 0
        self.status.output_tokens = self.state.usage.output_tokens
        self.status.cost_usd = self.state.usage.cost_usd
        # getattr: a Usage predating the cache fields leaves the tokens segment cache-free.
        self.status.cache_read_tokens = getattr(self.state.usage, "cache_read_tokens", 0) or 0
        self.status.cache_creation_tokens = (
            getattr(self.state.usage, "cache_creation_tokens", 0) or 0
        )
        self.status.approval = self.harness.gate.mode.value
        self.status.working = False

    def turn_summary_line(self) -> str | None:
        """The per-turn cost line for the turn that just finished, or None if unavailable."""
        return format_last_turn(self.state, self.status.price_ref)

    def _cycle_approval(self) -> None:
        self.harness.gate.mode = cycle_mode(self.harness.gate.mode)
        self.status.approval = self.harness.gate.mode.value

    def print_notes(self) -> None:
        """Print ``startup_notes`` to the console — plain path only.

        Under the TUI these go into the transcript instead; printing them here would put
        them behind the alternate screen, where they'd appear only on quit.
        """
        for note in self.startup_notes:
            style = "yellow" if note.startswith("sandbox:") else "dim"
            console.print(f"[{style}]{note}[/{style}]")

    # ---- @file mentions ----------------------------------------------- #

    def expand_mentions(self, line: str):  # noqa: ANN201 - MentionResult, imported lazily
        """Expand ``@path`` mentions in ``line`` into the text actually sent to the model.

        The seam both surfaces share: call it on a turn line, send ``result.prompt``, and
        show ``result.errors`` to the user. Every path is jailed by the harness's sandbox
        policy, so a mention can only ever read what a tool could have read.
        """
        from agent86.tui.mentions import expand_mentions  # textual-free; see module docstring

        return expand_mentions(
            line, self.harness.policy, max_bytes=self.cfg.tools.mention_max_bytes
        )

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

        # The gate had no way to ask here, so `ask` mode declined every write, every shell
        # call and every MCP side effect — with the only clue being "approval required but no
        # prompt available" buried in a tool result. Installed here rather than in
        # `run_repl` so the TUI's own fallback into this loop gets it too.
        install_approval_prompt(self.harness)

        while True:
            try:
                raw = input("agent86> ")
            except EOFError:
                console.print("\n[dim]bye[/dim]")
                return
            except KeyboardInterrupt:
                console.print("")
                continue

            line = raw.strip()
            # The UNSTRIPPED line, so the bash escape hatch survives: a prompt typed with a
            # leading space is refused by PromptHistory and never hits the file.
            self.history.append(raw.rstrip())
            action = self.dispatch(line)
            if action == "exit":
                return
            if action == "handled":
                continue

            # `@path` mentions become inline file blocks before the model ever sees the
            # line. Refusals are reported to the user here AND carried in the prompt, so
            # neither side is left assuming a file arrived when it didn't.
            mentions = self.expand_mentions(line)
            for problem in mentions.errors:
                console.print(f"[yellow]{escape(problem)}[/yellow]")

            console.print()  # blank line separating the question from the response
            console.print("[bold cyan]agent86[/bold cyan] ", end="")
            printed = False
            # The `agent86` label above was printed with end="": the cursor is mid-line.
            at_line_start = False
            try:
                # `display_text=line`: the model gets the expanded prompt, the trace gets the
                # sentence the user actually typed rather than the files behind it.
                for delta in self.harness.run_turn(
                    mentions.prompt, self.state, display_text=line
                ):
                    if delta.text:
                        notice = notice_text(delta.text)
                        if notice is not None:
                            # Harness chatter, not the answer: break the stream's current
                            # line first so it can't be glued onto the model's sentence.
                            if not at_line_start:
                                console.print()
                                at_line_start = True
                            console.print(f"[dim]{escape(notice)}[/dim]")
                            continue
                        _emit(delta.text)
                        at_line_start = delta.text.endswith("\n")
                        printed = True
                if not printed:
                    console.print("[dim](no response)[/dim]", end="")
                console.print()
            except (ProviderError, HarnessError) as exc:
                console.print(f"\n[red]error:[/red] {exc}")
            except KeyboardInterrupt:
                console.print("\n[dim]interrupted[/dim]")
            self._refresh_status()
            # Printed on the error/interrupt paths too: the loop publishes a fresh summary at
            # the START of every turn and closes it on every exit, so what's on `state` is
            # always THIS turn — and a turn that failed halfway still spent tokens.
            summary = self.turn_summary_line()
            if summary:
                console.print(f"[dim]{escape(summary)}[/dim]")
            console.print()  # blank line separating the response from the next prompt


def _use_tui(cfg: Config, plain: bool) -> bool:
    """Whether to launch the Textual TUI rather than the plain loop."""
    if plain or os.getenv("AGENT86_PLAIN"):
        return False
    return bool(cfg.ui.tui) and sys.stdin.isatty() and sys.stdout.isatty()


def run_repl(cfg: Config, resume: str | None = None, plain: bool = False) -> None:
    """Entry point: build the harness once, then run the TUI or the plain loop on it."""
    from agent86.cognitive.base import ProviderError

    try:
        repl = _Repl(cfg, resume)
    except ProviderError as exc:
        console.print(f"[red]Cannot start:[/red] {exc}")
        console.print(
            "[dim]Fix the key/config or choose another model with "
            "`agent86 --model provider:model`, then retry.[/dim]"
        )
        return

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
    # Plain path only. Printed before the TUI launches, the banner and notes would be
    # painted onto the terminal's normal screen and then hidden by the alternate screen,
    # only flashing past on quit — so the TUI renders `repl.startup_notes` itself instead.
    console.print(_banner(cfg))
    repl.print_notes()
    repl.plain_loop()


__all__ = ["approval_prompt", "install_approval_prompt", "run_repl"]
