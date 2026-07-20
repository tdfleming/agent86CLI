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
from typing import Any

from agent86.guardrails.policy import cycle_mode, parse_mode

__all__ = ["CommandResult", "handle_command", "startup_notes"]


@dataclass
class CommandResult:
    """The outcome of dispatching one input line.

    ``action`` is one of "handled" | "turn" | "exit" | "noop".
    ``render`` is a str or Rich renderable to write into the transcript (may be None).
    """

    action: str
    render: Any | None = None


def _help_table():
    from rich.table import Table

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


def handle_command(repl, line: str) -> CommandResult:
    """Dispatch one input line for ``repl``, returning a :class:`CommandResult`.

    Reproduces ``_Repl.dispatch``'s behavior branch-for-branch, but returns renderables/messages
    instead of printing to stdout, so a Textual app can write them into its own transcript.
    """
    if not line:
        return CommandResult("noop")
    if line in ("/exit", "/quit"):
        return CommandResult("exit")
    if line == "/help":
        return CommandResult("handled", _help_table())
    if line == "/config":
        return CommandResult("handled", repl.cfg.model_dump_json(indent=2))
    if line == "/models":
        providers, roles = _models_tables(repl.cfg)
        return CommandResult("handled", (providers, roles))
    if line == "/tools":
        return CommandResult("handled", "tools: " + ", ".join(repl.harness.registry.names()))
    if line == "/skills":
        if repl.harness.skills:
            render = "\n".join(
                f"{s.name} - {s.description}" for s in repl.harness.skills.values()
            )
        else:
            render = "no skills discovered"
        return CommandResult("handled", render)
    if line == "/memory":
        return CommandResult("handled", _show_memory(repl))
    if line == "/cost":
        return CommandResult("handled", _show_cost(repl))
    if line == "/clear":
        repl.state = repl.harness.new_session()
        return CommandResult("handled", "conversation cleared")
    if line == "/mode" or line.startswith("/mode "):
        return CommandResult("handled", _set_mode(repl, line[5:].strip()))
    if line == "/model" or line.startswith("/model "):
        return CommandResult("handled", _set_model(repl, line[6:].strip()))
    if line.startswith("/"):
        return CommandResult("handled", f"unknown command {line}")
    return CommandResult("turn")


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
