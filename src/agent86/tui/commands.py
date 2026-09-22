"""Textual-friendly slash-command adapter.

Ports the existing REPL dispatch (``agent86.ui.repl._Repl.dispatch``) so it can run inside a
Textual app: instead of writing to a Rich ``Console`` (stdout), every branch RETURNS a
:class:`CommandResult` carrying the renderable the app should write to the transcript. State
mutation (mode/model/session) is applied directly to the passed-in ``repl`` object, mirroring
``_Repl`` exactly — this module does not duplicate that logic, it just changes how the result is
surfaced.

Both surfaces dispatch through here: the TUI writes ``CommandResult.render`` to its
``RichLog(markup=True)`` transcript, and ``_Repl.dispatch`` prints it to a Rich ``Console``.
Both interpret console markup, so every untrusted interpolation below — model refs, provider
names, config values, skill/tool names, exception strings, the echoed command line — goes
through ``rich.markup.escape``. Only this module's own literal tags are live markup.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from agent86.guardrails.policy import parse_mode

__all__ = [
    "CommandResult",
    "CommandEntry",
    "COMMANDS",
    "find_command",
    "find_command_for_line",
    "handle_command",
    "recent_sessions",
    "relative_time",
    "session_label",
    "startup_notes",
]

ChoiceKind = Literal[None, "model", "mode", "config_model", "config_mcp", "resume"]


@dataclass
class CommandResult:
    """The outcome of dispatching one input line.

    ``action`` is one of "handled" | "turn" | "exit" | "noop".
    ``render`` is a str or Rich renderable to write into the transcript (may be None).
    ``clears_transcript`` signals the wipe **structurally**, not by name — the app must not
    special-case the string ``/clear``, since matching on a command name is exactly the
    coupling that drifts. Only the TUI acts on it (wipe + reprint the banner); the plain loop
    has no transcript to wipe and keeps printing ``render`` regardless.
    """

    action: str
    render: Any | None = None
    clears_transcript: bool = False


@dataclass(frozen=True)
class CommandEntry:
    """Declarative description of one slash-command.

    Backs both ``handle_command`` dispatch and the ``/help`` table (and, in later plans, the
    command palette) so the two can never drift.
    """

    name: str
    usage: str
    description: str
    handler: Callable[[Any, str], CommandResult]
    needs_choice: ChoiceKind = None
    terminal: bool = False


def _help_table():
    from rich.markup import escape
    from rich.table import Table

    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    for entry in COMMANDS:
        # Usage strings carry literal brackets ("/mode [ask|auto|deny]") that console
        # markup would otherwise eat as an unknown style tag.
        table.add_row(f"[cyan]{escape(entry.usage)}[/cyan]", entry.description)
    return table


def _key_source(name: str, prov) -> str:
    """Where this provider's key comes from — never the key itself (D-10)."""
    import os

    from agent86.secrets import has_stored_key

    if not prov.api_key_env:
        return "[dim]n/a[/dim]"
    if os.getenv(prov.api_key_env):
        return "[green]env[/green]"
    if has_stored_key(name):
        return "[green]keyring[/green]"
    return "[yellow]none[/yellow]"


def _models_tables(cfg):
    from rich.console import Group
    from rich.markup import escape
    from rich.table import Table
    from rich.text import Text

    from agent86.secrets import keyring_available
    from agent86.types import ModelRef

    table = Table(show_header=True, header_style="bold", title="Providers")
    table.add_column("Provider")
    table.add_column("Base URL")
    table.add_column("API key env")
    table.add_column("Key")
    for name, prov in cfg.providers.items():
        # Provider names, URLs and env-var names come from config.toml — user data, not markup.
        table.add_row(
            escape(name),
            escape(prov.base_url) if prov.base_url else "[dim]-[/dim]",
            escape(prov.api_key_env) if prov.api_key_env else "[dim]-[/dim]",
            _key_source(name, prov),
        )

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
        roles.add_row(role, escape(ref), valid)

    keyring_line = Text.from_markup(
        "OS keyring: [green]available[/green]"
        if keyring_available()
        else "OS keyring: [yellow]unavailable[/yellow] "
        "(keys resolve from environment variables only)"
    )

    return Group(table, roles, keyring_line)


def _set_mode(repl, arg: str) -> str:
    from rich.markup import escape

    if not arg:
        repl._cycle_approval()
    else:
        mode = parse_mode(arg)
        if mode is None:
            return f"unknown mode '{escape(arg)}' (ask|auto|deny)"
        repl.harness.gate.mode = mode
        repl.status.approval = mode.value
    return f"approval mode: {repl.harness.gate.mode.value}"


def _set_model(repl, arg: str) -> str:
    from rich.markup import escape

    p = repl.harness.provider
    if not arg:
        return (
            f"current model: {escape(p.name)}:{escape(p.model)}\n"
            "usage: /model <provider:model>  "
            "e.g. /model openrouter:anthropic/claude-3.7-sonnet"
        )
    from agent86.cognitive.base import ProviderError

    try:
        new = repl.harness.set_model(arg)
    except (ProviderError, ValueError) as exc:
        # The message quotes the ref the user typed, and SDK errors are arbitrary text.
        return escape(str(exc))
    repl._refresh_status()
    return f"model: {escape(new.name)}:{escape(new.model)}"


def _cache_savings(model_ref: str, usage) -> float | None:  # noqa: ANN001
    """What prompt caching saved this session, if the pricing module can say.

    ``pricing.cache_savings`` is an optional contract (v0.8): absent, or unhappy with the
    arguments we offer, and ``/cost`` simply reports the cache token counts instead. Cost
    reporting must never be the thing that breaks a session, so every failure is swallowed.
    """
    from agent86.cognitive import pricing

    fn = getattr(pricing, "cache_savings", None)
    if fn is None:
        return None
    for args in ((model_ref, usage), (usage,), (model_ref, usage.input_tokens,
                 getattr(usage, "cache_read_tokens", 0),
                 getattr(usage, "cache_creation_tokens", 0))):
        try:
            value = fn(*args)
        except TypeError:
            continue  # a different signature than this shape; try the next
        except Exception:  # noqa: BLE001 - never let a price lookup break /cost
            return None
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
    return None


def _show_cost(repl) -> str:
    from agent86.ui.status import UNPRICED_LABEL, format_cost

    u = repl.state.usage
    # Same honesty rule as the status line: on a model with no known rate (Groq, most
    # OpenRouter routes) a running total of $0.0000 reads as "this turn was free" when the
    # truth is "we have no idea what this cost". `format_cost` spells that out itself, so
    # only the dollar figure gets the "cost" label in front of it.
    cost = format_cost(u.cost_usd, repl.status.price_ref)
    cost_text = cost if cost == UNPRICED_LABEL else f"cost {cost}"
    line = (
        f"steps {repl.state.step_count}  "
        f"in {u.input_tokens}  out {u.output_tokens} tok  "
        f"{cost_text}"
    )
    # getattr: a Usage predating the cache fields says nothing about caching at all, rather
    # than claiming a confident zero.
    read = getattr(u, "cache_read_tokens", 0) or 0
    written = getattr(u, "cache_creation_tokens", 0) or 0
    if read or written:
        line += f"\ncache read {read}  written {written} tok"
        saved = _cache_savings(repl.status.price_ref, u)
        if saved:
            line += f"  saved ${saved:.4f}"
    return line


def _show_memory(repl) -> str:
    from rich.markup import escape

    if repl.harness.memory:
        c = repl.harness.memory.store.counts()
        return (
            f"memory sessions {c['sessions']}  episodes {c['episodes']}  "
            f"facts {c['memories']}  session {escape(repl.state.session_id)}"
        )
    return "memory is disabled"


def _skills_render(repl) -> str:
    from rich.markup import escape

    # Skill names and descriptions are read off disk (SKILL.md front-matter) — untrusted.
    if repl.harness.skills:
        return "\n".join(
            f"{escape(s.name)} - {escape(s.description)}" for s in repl.harness.skills.values()
        )
    return "no skills discovered"


def _tools_render(repl) -> str:
    from rich.markup import escape

    # Tool names include MCP tools, named by the server rather than by us.
    return "tools: " + ", ".join(escape(n) for n in repl.harness.registry.names())


def _config_render(repl) -> str:
    from rich.markup import escape

    return escape(repl.cfg.model_dump_json(indent=2))


def _clear_session(repl) -> CommandResult:
    repl.state = repl.harness.new_session()
    return CommandResult("handled", "conversation cleared", clears_transcript=True)


# ---- sessions (/sessions, /resume) ------------------------------------- #

#: What both surfaces show when the session log isn't being kept.
NO_MEMORY_NOTE = "memory is disabled - sessions are not saved, so there is nothing to resume"


def relative_time(when: float, now: float | None = None) -> str:
    """``when`` (a UNIX timestamp) as a short "how long ago" — "3h ago", "2d ago".

    Deliberately coarse. The question a session list answers is "which one was I in", and a
    full timestamp costs more width than it earns; anything older than a month rounds to
    months, because by then the exact day has stopped being the thing you remember.
    """
    import time

    if not when:
        return "unknown"
    delta = (time.time() if now is None else now) - when
    if delta < 60:  # covers a clock that skewed backwards, too
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    if delta < 86400 * 30:
        return f"{int(delta // 86400)}d ago"
    return f"{int(delta // (86400 * 30))}mo ago"


def session_label(info, now: float | None = None) -> str:  # noqa: ANN001 - SessionInfo
    """One session as a single line: ``title · id[:8] · relative time``.

    Shared by the ``/sessions`` table and the session picker's options so the two lists read
    identically. NOT markup-escaped — the caller decides, because one renders into a Rich
    console and the other into a Textual ``Text``.
    """
    return f"{info.label} · {info.session_id[:8]} · {relative_time(info.updated_at, now)}"


def recent_sessions(repl, limit: int = 20):  # noqa: ANN201 - list[SessionInfo] | None
    """Recent sessions for this repl, or None when memory (and so the log) is off."""
    memory = getattr(repl.harness, "memory", None)
    if memory is None:
        return None
    try:
        return memory.store.recent_sessions(limit)
    except Exception:  # noqa: BLE001 - a broken log must not take a command down
        return []


def _sessions_render(repl):
    from rich.markup import escape
    from rich.table import Table

    sessions = recent_sessions(repl)
    if sessions is None:
        return NO_MEMORY_NOTE
    if not sessions:
        return "no saved sessions yet"
    table = Table(show_header=True, header_style="bold", title="Recent sessions")
    table.add_column("Session")
    table.add_column("Title")
    table.add_column("Updated")
    for info in sessions:
        active = info.session_id == repl.state.session_id
        # Titles are the user's own first prompt: escaped, never live markup.
        table.add_row(
            f"[green]{escape(info.session_id[:8])}[/green]"
            if active
            else escape(info.session_id[:8]),
            escape(info.label),
            relative_time(info.updated_at),
        )
    return table


def _resolve_session_id(repl, arg: str) -> str | None:
    """Turn what the user typed into a full session id.

    The lists show ``id[:8]``, so that prefix has to be resumable — otherwise every resume
    means copying an id out of a column that never showed it in full. An exact id always
    wins; an ambiguous prefix resolves to nothing rather than to a guess.
    """
    sessions = recent_sessions(repl, limit=200) or []
    ids = [s.session_id for s in sessions]
    if arg in ids:
        return arg
    matches = [sid for sid in ids if sid.startswith(arg)]
    return matches[0] if len(matches) == 1 else None


def _resume(repl, arg: str) -> CommandResult:
    """Load a saved session and make it the live one."""
    from rich.markup import escape

    if getattr(repl.harness, "memory", None) is None:
        return CommandResult("handled", NO_MEMORY_NOTE)
    if not arg:
        # Bare /resume is the picker's job in the TUI; the plain loop shows the list so the
        # user can copy an id out of it.
        return CommandResult(
            "handled",
            _sessions_render(repl)
            if recent_sessions(repl)
            else "no saved sessions yet",
        )
    session_id = _resolve_session_id(repl, arg)
    state = repl.harness.resume(session_id) if session_id else None
    if state is None:
        return CommandResult("handled", f"no session '{escape(arg)}' found")
    repl.state = state
    repl._refresh_status()
    title = repl.harness.memory.store.session_title(state.session_id)
    suffix = f" - {escape(title)}" if title else ""
    return CommandResult(
        "handled",
        f"resumed session {escape(state.session_id)} "
        f"({len(state.messages)} messages){suffix}",
    )


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
        handler=lambda repl, arg: CommandResult("handled", _config_render(repl)),
    ),
    CommandEntry(
        name="/config model",
        usage="/config model",
        description="Manage providers & models: add, key, test, switch, save",
        handler=lambda repl, arg: CommandResult(
            "handled",
            "The model manager is a TUI surface — press / and pick "
            "[cyan]/config model[/cyan], or run agent86 without --plain.",
        ),
        needs_choice="config_model",
    ),
    CommandEntry(
        name="/config mcp",
        usage="/config mcp",
        description="Manage MCP servers: add, test, enable/disable, remove",
        handler=lambda repl, arg: CommandResult(
            "handled",
            "The MCP manager is a TUI surface — press / and pick "
            "[cyan]/config mcp[/cyan], or run agent86 without --plain.",
        ),
        needs_choice="config_mcp",
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
        handler=lambda repl, arg: CommandResult("handled", _tools_render(repl)),
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
        name="/sessions",
        usage="/sessions",
        description="List recent sessions",
        handler=lambda repl, arg: CommandResult("handled", _sessions_render(repl)),
    ),
    CommandEntry(
        name="/resume",
        usage="/resume [session-id]",
        description="Resume a saved session",
        handler=lambda repl, arg: _resume(repl, arg),
        needs_choice="resume",
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


def find_command_for_line(line: str) -> tuple[CommandEntry, str] | None:
    """Match ``line`` against the registry, longest command name first.

    Multi-word commands (``/config model``) must win over their single-word prefix
    (``/config``); ``/models`` must not be read as ``/model`` + ``"s"`` — hence exact-or-
    followed-by-a-space matching rather than ``str.startswith`` alone.
    """
    for entry in sorted(COMMANDS, key=lambda e: -len(e.name)):
        if line == entry.name:
            return entry, ""
        if line.startswith(entry.name + " "):
            return entry, line[len(entry.name) + 1 :].strip()
    return None


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
    match = find_command_for_line(line)
    if match is None:
        from rich.markup import escape

        return CommandResult("handled", f"unknown command {escape(line)}")
    entry, arg = match
    return entry.handler(repl, arg)


def startup_notes(repl) -> list[str]:
    """Return the launch-note strings for the transcript / the plain loop's banner area.

    Every note is markup-escaped: the harness notes quote filesystem paths and MCP/sandbox
    error text, and skill names come off disk.
    """
    from rich.markup import escape

    # `_Repl.__init__` records what `--resume` did here rather than printing it, so it
    # reaches the TUI transcript instead of being swallowed by the alternate screen.
    notes: list[str] = [escape(n) for n in getattr(repl, "resume_notes", ())]
    if repl.harness.memory_note:
        notes.append(f"memory: {escape(repl.harness.memory_note)}")
    # One line per degradation: `mcp_note` joins them with newlines, and several bad servers
    # collapsed into one multi-line note render as a single squashed transcript entry.
    mcp = getattr(repl.harness, "mcp", None)
    mcp_notes = list(getattr(mcp, "notes", None) or [])
    if not mcp_notes and repl.harness.mcp_note:
        mcp_notes = [repl.harness.mcp_note]
    for note in mcp_notes:
        notes.append(f"mcp: {escape(note)}")
    # A tool whose name was already taken is not callable. Dropping it in silence looks
    # exactly like the server failing to connect, so say which names went missing.
    collisions = list(getattr(repl.harness.registry, "collisions", None) or [])
    if collisions:
        joined = ", ".join(escape(n) for n in collisions)
        notes.append(f"tools: name collision, not callable: {joined}")
    if repl.harness.sandbox_note:
        notes.append(f"sandbox: {escape(repl.harness.sandbox_note)}")
    if repl.harness.skills:
        notes.append("skills: " + ", ".join(escape(s) for s in repl.harness.skills))
    notes.append(f"session {escape(repl.state.session_id)}")
    return notes
