"""Textual-friendly slash-command adapter.

Ports the existing REPL dispatch (``agent86.ui.repl._Repl.dispatch``) so it can run inside a
Textual app: instead of writing to a Rich ``Console`` (stdout), every branch RETURNS a
:class:`CommandResult` carrying the renderable the app should write to the transcript. State
mutation (mode/model/session) is applied directly to the passed-in ``repl`` object, mirroring
``_Repl`` exactly — this module does not duplicate that logic, it just changes how the result is
surfaced.

``ui/repl.py`` and the plain loop are untouched; this module is purely additive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from agent86.guardrails.policy import cycle_mode, parse_mode

__all__ = [
    "CommandResult",
    "CommandEntry",
    "COMMANDS",
    "find_command",
    "handle_command",
    "startup_notes",
]

ChoiceKind = Literal[None, "model", "mode"]


@dataclass
class CommandResult:
    """The outcome of dispatching one input line.

    ``action`` is one of "handled" | "turn" | "exit" | "noop".
    ``render`` is a str or Rich renderable to write into the transcript (may be None).
    """

    action: str
    render: Any | None = None


@dataclass(frozen=True)
class CommandEntry:
    """Declarative description of one slash-command.

    Backs both ``handle_command`` dispatch and the ``/help`` table (and, in later plans, the
    command palette) so the two can never drift.
    """

    name: str
    usage: str
    description: str
    handler: Callable[[Any, str], "CommandResult"]
    needs_choice: ChoiceKind = None
    terminal: bool = False


def _help_table():
    from rich.table import Table

    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    for entry in COMMANDS:
        table.add_row(f"[cyan]{entry.usage}[/cyan]", entry.description)
    return table


def _models_tables(cfg):
    from rich.table import Table

    from agent86.types import ModelRef

    table = Table(show_header=True, header_style="bold", title="Providers")
    table.add_column("Provider")
    table.add_column("Base URL")
    table.add_column("API key env")
    for name, prov in cfg.providers.items():
        table.add_row(name, prov.base_url or "[dim]-[/dim]", prov.api_key_env or "[dim]-[/dim]")

    roles = Table(show_header=True, header_style="bold", title="Model roles")
    roles.add_column("Role")
    roles.add_column("Model")
    roles.add_column("Valid")
    for role, ref in (
        ("default", cfg.model.default),
        ("route.cheap", cfg.model.route.cheap),
        ("route.frontier", cfg.model.route.frontier),
    ):
        try:
            ModelRef.parse(ref)
            valid = "[green]ok[/green]"
        except ValueError:
            valid = "[red]invalid[/red]"
        roles.add_row(role, ref, valid)

    return table, roles


def _set_mode(repl, arg: str) -> str:
    if not arg:
        repl._cycle_approval()
    else:
        mode = parse_mode(arg)
        if mode is None:
            return f"unknown mode '{arg}' (ask|auto|deny)"
        repl.harness.gate.mode = mode
        repl.status.approval = mode.value
    return f"approval mode: {repl.harness.gate.mode.value}"


def _set_model(repl, arg: str) -> str:
    p = repl.harness.provider
    if not arg:
        return (
            f"current model: {p.name}:{p.model}\n"
            "usage: /model <provider:model>  "
            "e.g. /model openrouter:anthropic/claude-3.7-sonnet"
        )
    from agent86.cognitive.base import ProviderError

    try:
        new = repl.harness.set_model(arg)
    except (ProviderError, ValueError) as exc:
        return str(exc)
    repl._refresh_status()
    return f"model: {new.name}:{new.model}"


def _show_cost(repl) -> str:
    u = repl.state.usage
    return (
        f"steps {repl.state.step_count}  "
        f"in {u.input_tokens}  out {u.output_tokens} tok  "
        f"cost ${u.cost_usd:.4f}"
    )


def _show_memory(repl) -> str:
    if repl.harness.memory:
        c = repl.harness.memory.store.counts()
        return (
            f"memory sessions {c['sessions']}  episodes {c['episodes']}  "
            f"facts {c['memories']}  session {repl.state.session_id}"
        )
    return "memory is disabled"


def _skills_render(repl) -> str:
    if repl.harness.skills:
        return "\n".join(f"{s.name} - {s.description}" for s in repl.harness.skills.values())
    return "no skills discovered"


def _clear_session(repl) -> CommandResult:
    repl.state = repl.harness.new_session()
    return CommandResult("handled", "conversation cleared")


COMMANDS: list[CommandEntry] = [
    CommandEntry(
        name="/help",
        usage="/help",
        description="Show this help",
        handler=lambda repl, arg: CommandResult("handled", _help_table()),
    ),
    CommandEntry(
        name="/config",
        usage="/config",
        description="Show the resolved configuration",
        handler=lambda repl, arg: CommandResult(
            "handled", repl.cfg.model_dump_json(indent=2)
        ),
    ),
    CommandEntry(
        name="/models",
        usage="/models",
        description="List configured models",
        handler=lambda repl, arg: CommandResult("handled", _models_tables(repl.cfg)),
    ),
    CommandEntry(
        name="/model",
        usage="/model <provider:model>",
        description="Switch the active model for this session",
        handler=lambda repl, arg: CommandResult("handled", _set_model(repl, arg)),
        needs_choice="model",
    ),
    CommandEntry(
        name="/tools",
        usage="/tools",
        description="List available tools",
        handler=lambda repl, arg: CommandResult(
            "handled", "tools: " + ", ".join(repl.harness.registry.names())
        ),
    ),
    CommandEntry(
        name="/skills",
        usage="/skills",
        description="List available skills",
        handler=lambda repl, arg: CommandResult("handled", _skills_render(repl)),
    ),
    CommandEntry(
        name="/memory",
        usage="/memory",
        description="Show memory stats and session id",
        handler=lambda repl, arg: CommandResult("handled", _show_memory(repl)),
    ),
    CommandEntry(
        name="/mode",
        usage="/mode [ask|auto|deny]",
        description="Show/set approval mode (Shift+Tab cycles)",
        handler=lambda repl, arg: CommandResult("handled", _set_mode(repl, arg)),
        needs_choice="mode",
    ),
    CommandEntry(
        name="/cost",
        usage="/cost",
        description="Show token usage and cost this session",
        handler=lambda repl, arg: CommandResult("handled", _show_cost(repl)),
    ),
    CommandEntry(
        name="/clear",
        usage="/clear",
        description="Start a fresh conversation",
        handler=lambda repl, arg: _clear_session(repl),
    ),
    CommandEntry(
        name="/exit",
        usage="/exit",
        description="Quit",
        handler=lambda repl, arg: CommandResult("exit"),
        terminal=True,
    ),
]


def find_command(name: str) -> CommandEntry | None:
    return next((c for c in COMMANDS if c.name == name), None)


def handle_command(repl, line: str) -> CommandResult:
    """Dispatch one input line for ``repl``, returning a :class:`CommandResult`.

    Reproduces ``_Repl.dispatch``'s behavior branch-for-branch, but returns renderables/messages
    instead of printing to stdout, so a Textual app can write them into its own transcript.
    """
    if not line:
        return CommandResult("noop")
    if line in ("/exit", "/quit"):
        return CommandResult("exit")
    if not line.startswith("/"):
        return CommandResult("turn")
    name, _, arg = line.partition(" ")
    entry = find_command(name)
    if entry is None:
        return CommandResult("handled", f"unknown command {line}")
    return entry.handler(repl, arg.strip())


def startup_notes(repl) -> list[str]:
    """Return the launch-note strings (mirrors ``_Repl.print_notes``) for the transcript."""
    notes: list[str] = []
    if repl.harness.memory_note:
        notes.append(f"memory: {repl.harness.memory_note}")
    if repl.harness.mcp_note:
        notes.append(f"mcp: {repl.harness.mcp_note}")
    if repl.harness.sandbox_note:
        notes.append(f"sandbox: {repl.harness.sandbox_note}")
    if repl.harness.skills:
        notes.append(f"skills: {', '.join(repl.harness.skills)}")
    notes.append(f"session {repl.state.session_id}")
    return notes
