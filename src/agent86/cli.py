"""The ``agent86`` command surface (Tier 1 entry point, user-facing).

Phase 1 wires the full CLI shape: an interactive REPL (default, no subcommand) plus
one-shot ``run`` and inspection commands (``config``, ``models``, ``skills``, ``mcp``,
``trace``). The cognitive loop that turns a goal into tool-using action lands in Phase 2;
where that plugs in is marked with ``# PHASE 2`` below.
"""

from __future__ import annotations

import os
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from agent86 import __version__
from agent86.config import Config, config_paths, load_config
from agent86.types import ModelRef

# Models routinely emit Unicode/emoji; force UTF-8 (with replacement) so a Windows console's
# legacy code page can't crash streaming output on a character it can't encode.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
        pass

console = Console()
err_console = Console(stderr=True)


def _emit(text: str) -> None:
    """Write streamed model text straight to stdout and flush.

    Raw write + flush is more reliable than a buffered Rich print for incremental,
    partial-line streaming across terminals (notably Git Bash / MinTTY on Windows).
    """
    sys.stdout.write(text)
    sys.stdout.flush()


#: What to do next when a model cannot be built — a bad ref, an unknown provider prefix, a
#: missing key. Every one of those is recoverable, and the recovery is the same two moves, so
#: the message says them rather than leaving the user to guess which of the three went wrong.
MODEL_HELP = (
    "Run `agent86 models` to see the configured providers and which of them has a key, "
    "then pick one with `--model provider:model`."
)


def _load(overrides: dict | None = None) -> Config:
    """``load_config``, but a malformed config file is a message rather than a traceback.

    A stray character in ``config.toml`` broke *every* command with a Rich traceback that
    named the parse error and not the file — including the ``config path`` one would run to
    find out where the file even is.
    """
    try:
        return load_config(overrides)
    except ValueError as exc:
        err_console.print(f"[red]error:[/red] {escape(str(exc))}")
        err_console.print(
            "[dim]Fix the TOML, or move that file aside to fall back to the defaults. "
            "`agent86 config path` lists every layer that is read.[/dim]"
        )
        raise typer.Exit(code=1) from None


app = typer.Typer(
    name="agent86",
    help="An agentic harness on the command line - connect to remote or local models "
    "and let them use tools and skills.",
    add_completion=False,
    no_args_is_help=False,
    # SEC-01 / D-10: Rich renders frame locals by default, which printed a full
    # sk-ant-... key in four traceback frames during UAT. A secret must never be
    # renderable, including on the crash path.
    pretty_exceptions_show_locals=False,
)


# --------------------------------------------------------------------------- #
# Global options + default action (REPL)
# --------------------------------------------------------------------------- #


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"agent86 {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    model: str | None = typer.Option(
        None, "--model", "-m", help="Override model (provider:model)."
    ),
    sandbox: str | None = typer.Option(None, "--sandbox", help="Override sandbox mode."),
    approval: str | None = typer.Option(None, "--approval", help="HITL mode: auto|ask|deny."),
    resume: str | None = typer.Option(
        None, "--resume", "-r", help="Resume a prior session by id (REPL)."
    ),
    plain: bool = typer.Option(
        False, "--plain", help="Force the plain REPL (no status line / spinner / hotkeys)."
    ),
    _version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version."
    ),
) -> None:
    """Launch the interactive REPL when invoked with no subcommand."""
    overrides: dict = {}
    if model:
        overrides.setdefault("model", {})["default"] = model
    if sandbox:
        overrides.setdefault("sandbox", {})["mode"] = sandbox
    if approval:
        overrides.setdefault("guardrails", {})["approval"] = approval

    cfg = _load(overrides or None)
    ctx.obj = cfg

    if ctx.invoked_subcommand is None:
        from agent86.ui.repl import run_repl

        run_repl(cfg, resume=resume, plain=plain)


# --------------------------------------------------------------------------- #
# `agent86 run`  -  one-shot
# --------------------------------------------------------------------------- #


@app.command()
def run(
    ctx: typer.Context,
    goal: str = typer.Argument(..., help="The goal for the agent to accomplish."),
    as_json: bool = typer.Option(False, "--json", help="Emit structured JSON output."),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Auto-approve side-effecting tools (non-interactive)."
    ),
    resume: str | None = typer.Option(
        None, "--session", "-s", help="Resume/continue a session by id."
    ),
) -> None:
    """Run a single goal non-interactively (scriptable).

    Piped or in CI, side-effecting tools are declined without --yes;
    read-only tools always run. Pass --yes to act autonomously.
    Typed at a terminal, each side-effecting call asks y/N instead.
    """
    import json as _json

    from agent86.cognitive.base import ProviderError
    from agent86.orchestration.loop import Harness, HarnessError
    from agent86.types import ApprovalMode

    cfg: Config = ctx.obj or _load()
    if yes:
        cfg.guardrails.approval = ApprovalMode.AUTO

    try:
        harness = Harness(cfg)
    except (ProviderError, ValueError) as exc:
        # ValueError too: a malformed `--model` ref (no colon, empty half) fails in
        # `ModelRef.parse` before any provider is constructed, and used to reach the user as
        # a Rich traceback instead of a sentence telling them what to type.
        err_console.print(f"[red]error:[/red] {escape(str(exc))}")
        err_console.print(f"[dim]{MODEL_HELP}[/dim]")
        raise typer.Exit(code=1) from None

    # A TTY-attached `agent86 run` can be asked; a piped one cannot, and is left exactly as
    # it was — declining under `ask` unless --yes said otherwise. `ui.repl` imports no
    # Textual, so this costs the one-shot path nothing.
    from agent86.ui.repl import install_approval_prompt

    install_approval_prompt(harness)

    if not as_json:
        if harness.memory_note:
            err_console.print(f"[dim]memory: {escape(harness.memory_note)}[/dim]")
        if harness.sandbox_note:
            err_console.print(f"[yellow]sandbox: {escape(harness.sandbox_note)}[/yellow]")

    state = harness.resume(resume) if resume else None
    if state is None:
        state = harness.new_session()
    parts: list[str] = []
    try:
        for delta in harness.run_turn(goal, state):
            if delta.text:
                parts.append(delta.text)
                if not as_json:
                    _emit(delta.text)
    except (ProviderError, HarnessError) as exc:
        err_console.print(f"\n[red]error:[/red] {escape(str(exc))}")
        if isinstance(exc, ProviderError):
            err_console.print(f"[dim]{MODEL_HELP}[/dim]")
        raise typer.Exit(code=1) from None

    if as_json:
        # Honor the egress guardrail (e.g. redact mode) on the machine-readable output.
        output = harness.egress.inspect("".join(parts)).text
        payload = {
            "session_id": state.session_id,
            "output": output,
            "steps": state.step_count,
            "usage": state.usage.model_dump(),
        }
        # Additive (v0.8): the per-turn summary, or null on a state that has none. Existing
        # keys are untouched — `run --json` is the scripting/CI contract.
        summary = getattr(state, "last_turn", None)
        dump = getattr(summary, "model_dump", None)
        payload["turn"] = dump() if dump is not None else summary
        console.print_json(_json.dumps(payload, default=str))
    else:
        console.print()
        from agent86.ui.status import format_last_turn

        line = format_last_turn(state, harness.provider.config_ref)
        if line:
            # stderr: stdout is the answer, and a scripted `agent86 run ... > out.txt` must
            # keep getting only that.
            err_console.print(f"[dim]{escape(line)}[/dim]")


# --------------------------------------------------------------------------- #
# `agent86 config`
# --------------------------------------------------------------------------- #

config_app = typer.Typer(help="Inspect configuration.")
app.add_typer(config_app, name="config")


@config_app.callback(invoke_without_command=True)
def config_default(ctx: typer.Context) -> None:
    """With no subcommand: show providers, key source, and OS keyring status."""
    if ctx.invoked_subcommand is None:
        _list_models(_load())


@config_app.command("path")
def config_path_cmd() -> None:
    """Show where configuration is read from."""
    paths = config_paths()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Layer")
    table.add_column("Path")
    for layer, path in paths.items():
        table.add_row(layer, path)
    console.print(table)


@config_app.command("show")
def config_show_cmd() -> None:
    """Print the fully-resolved configuration."""
    _show_config(_load())


def _show_config(cfg: Config) -> None:
    console.print_json(cfg.model_dump_json(indent=2))


# --------------------------------------------------------------------------- #
# `agent86 models`
# --------------------------------------------------------------------------- #


@app.command()
def models(ctx: typer.Context) -> None:
    """List configured models and providers."""
    cfg: Config = ctx.obj or _load()
    _list_models(cfg)


def _list_models(cfg: Config) -> None:
    from agent86.secrets import has_stored_key, keyring_available

    def _key_source(name: str, prov) -> str:
        """Where this provider's key comes from — never the key itself (D-10)."""
        if not prov.api_key_env:
            return "[dim]n/a[/dim]"  # keyless local endpoint
        if os.getenv(prov.api_key_env):
            return "[green]env[/green]"
        if has_stored_key(name):
            return "[green]keyring[/green]"
        return "[yellow]none[/yellow]"

    table = Table(show_header=True, header_style="bold", title="Providers")
    table.add_column("Provider")
    table.add_column("Base URL")
    table.add_column("API key env")
    table.add_column("Key")
    for name, prov in cfg.providers.items():
        table.add_row(
            name,
            prov.base_url or "[dim]-[/dim]",
            prov.api_key_env or "[dim]-[/dim]",
            _key_source(name, prov),
        )
    console.print(table)
    console.print(
        "OS keyring: [green]available[/green]"
        if keyring_available()
        else "OS keyring: [yellow]unavailable[/yellow] "
        "(keys resolve from environment variables only)"
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
        roles.add_row(role, ref, valid)
    console.print(roles)


# --------------------------------------------------------------------------- #
# `agent86 memory`
# --------------------------------------------------------------------------- #

memory_app = typer.Typer(help="Inspect long-term memory.")
app.add_typer(memory_app, name="memory")


def _open_memory():
    from agent86.memory.store import MemoryStoreError
    from agent86.memory.system import build_memory

    cfg = _load()
    try:
        mem = build_memory(cfg)
    except MemoryStoreError as exc:
        # Already actionable (which file, why, what to change); printed without a traceback
        # because a locked or unwritable db is a configuration problem, not a crash.
        err_console.print(f"[red]error:[/red] {escape(str(exc))}")
        raise typer.Exit(code=1) from None
    if mem is None:
        err_console.print(
            "[yellow]Memory is disabled in config.[/yellow] "
            r"Set `\[memory] enabled = true` to turn it on "
            "(`agent86 config path` shows which file to edit)."
        )
        raise typer.Exit(code=1)
    if mem.note:
        err_console.print(f"[dim]memory: {escape(mem.note)}[/dim]")
    return mem


@memory_app.command("stats")
def memory_stats_cmd() -> None:
    """Show counts of stored sessions, episodes, and facts."""
    mem = _open_memory()
    counts = mem.store.counts()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Kind")
    table.add_column("Count", justify="right")
    for kind, n in counts.items():
        table.add_row(kind, str(n))
    console.print(table)
    console.print(
        f"[dim]db:[/dim] {mem.store.path}  [dim]embedder:[/dim] {mem.store.embedder.spec}"
    )
    mem.close()


@memory_app.command("sessions")
def memory_sessions_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="Max sessions to show."),
) -> None:
    """List recent sessions (most recent first)."""
    mem = _open_memory()
    rows = mem.store.list_sessions(limit)
    if not rows:
        console.print("[dim]no sessions yet[/dim]")
    else:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Session")
        table.add_column("Title")
        for row in rows:
            table.add_row(row["session_id"], row["title"] or "[dim]-[/dim]")
        console.print(table)
    mem.close()


@memory_app.command("search")
def memory_search_cmd(
    query: str = typer.Argument(..., help="What to search episodic + semantic memory for."),
    k: int = typer.Option(5, "--k", "-k", help="Results per store."),
) -> None:
    """Search episodic and semantic memory."""
    mem = _open_memory()
    episodes = mem.store.search_episodes(query, k)
    facts = mem.store.search_memories(query, k)
    console.print("[bold]episodes[/bold]")
    for h in episodes:
        outcome = h.metadata.get("outcome", "")[:80]
        console.print(f"  [{h.score:.2f}] {h.text}  [dim]-> {outcome}[/dim]")
    if not episodes:
        console.print("  [dim](none)[/dim]")
    console.print("[bold]facts[/bold]")
    for h in facts:
        console.print(f"  [{h.score:.2f}] {h.text}")
    if not facts:
        console.print("  [dim](none)[/dim]")
    mem.close()


@memory_app.command("prune")
def memory_prune_cmd(
    older_than: float | None = typer.Option(
        None, "--older-than", help="Delete log rows older than this many days."
    ),
    keep_last: int | None = typer.Option(
        None, "--keep-last", help="Keep only the most recent N rows per table."
    ),
    memories: bool = typer.Option(
        False, "--memories", help="Also prune curated semantic facts (off by default)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be deleted without deleting."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Trim the flight-recorder log (episodes + sessions) by age and/or count.

    Curated semantic facts are left untouched unless --memories is given. With no limits,
    prints current counts and exits (nothing is deleted).
    """
    if older_than is None and keep_last is None:
        console.print(
            "[yellow]No retention limit given.[/yellow] Pass --older-than and/or --keep-last."
        )
        mem = _open_memory()
        console.print({k: v for k, v in mem.store.counts().items()})
        mem.close()
        return

    mem = _open_memory()
    if dry_run:
        # Count without mutating by reusing prune on a would-be basis is awkward; report intent.
        console.print(
            f"[dim]dry run — would prune episodes+sessions"
            f"{' + memories' if memories else ''} "
            f"(older_than={older_than}, keep_last={keep_last}). Current counts:[/dim]"
        )
        console.print({k: v for k, v in mem.store.counts().items()})
        mem.close()
        return

    if not yes:
        target = "episodes, sessions" + (", memories" if memories else "")
        confirm = typer.confirm(f"Prune {target} (older_than={older_than}, keep_last={keep_last})?")
        if not confirm:
            console.print("[dim]aborted[/dim]")
            mem.close()
            return

    removed = mem.store.prune(
        older_than_days=older_than, keep_last=keep_last, memories=memories
    )
    total = sum(removed.values())
    console.print(f"[green]Pruned {total} row(s):[/green] {removed}")
    console.print({k: v for k, v in mem.store.counts().items()})
    mem.close()


@memory_app.command("forget")
def memory_forget_cmd(
    mem_id: int = typer.Argument(..., help="Id of the semantic memory to delete (see search)."),
) -> None:
    """Delete a single semantic fact by id."""
    mem = _open_memory()
    ok = mem.store.delete_memory(mem_id)
    if ok:
        console.print(f"[green]Deleted memory {mem_id}.[/green]")
    else:
        console.print(f"[yellow]No memory with id {mem_id}.[/yellow]")
    mem.close()


# --------------------------------------------------------------------------- #
# `agent86 skills` / `mcp` / `trace`  -  scaffolded stubs
# --------------------------------------------------------------------------- #

skills_app = typer.Typer(help="Manage skills.")
app.add_typer(skills_app, name="skills")


@skills_app.command("list")
def skills_list_cmd() -> None:
    """List discovered skills."""
    from agent86.skills.loader import default_skill_paths, discover_skills

    cfg = _load()
    skills = discover_skills(cfg)
    if not skills:
        paths = ", ".join(str(p) for p in default_skill_paths(cfg))
        console.print(f"[dim]No skills found. Searched: {paths}[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Skill")
    table.add_column("Description", overflow="fold")
    for skill in skills.values():
        table.add_row(skill.name, skill.description)
    console.print(table)


@skills_app.command("show")
def skills_show_cmd(name: str = typer.Argument(..., help="Skill name.")) -> None:
    """Show a skill's full instructions."""
    from agent86.skills.loader import discover_skills

    skills = discover_skills(_load())
    skill = skills.get(name)
    if skill is None:
        known = ", ".join(skills) or "(none)"
        err_console.print(
            f"[red]No skill named '{escape(name)}'.[/red] Known: {escape(known)}. "
            "Run `agent86 skills list` to see where they were discovered from."
        )
        raise typer.Exit(code=1)
    console.print(f"[bold]{skill.name}[/bold] - {skill.description}\n")
    console.print(skill.instructions())
    if skill.resources():
        console.print(f"\n[dim]resources: {', '.join(skill.resources())}[/dim]")


mcp_app = typer.Typer(help="Manage MCP servers.")
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("list")
def mcp_list_cmd(ctx: typer.Context) -> None:
    """List configured MCP servers."""
    cfg: Config = _load()
    if not cfg.mcp_servers:
        console.print(
            "[dim]No MCP servers configured.[/dim] Add one with `/config mcp` in the REPL, "
            r"or an `\[mcp_servers.<name>]` block in the file `agent86 config path` names."
        )
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Transport")
    table.add_column("Enabled")
    table.add_column("Endpoint", overflow="fold")
    for name, srv in cfg.mcp_servers.items():
        endpoint = srv.url or " ".join([srv.command or "", *srv.args]).strip()
        table.add_row(name, srv.transport or "?", "yes" if srv.enabled else "no", endpoint)
    console.print(table)


@mcp_app.command("tools")
def mcp_tools_cmd() -> None:
    """Start configured MCP servers and list the tools they expose."""
    from agent86.tools.mcp_client import build_mcp

    cfg = _load()
    manager = build_mcp(cfg)
    if manager is None:
        console.print(
            "[dim]No MCP servers configured (or MCP disabled).[/dim] "
            "`agent86 mcp list` shows what is configured and whether each is enabled."
        )
        return
    # One line per degradation, not one joined blob: with several bad servers a single
    # newline-joined note is easy to skim past, and only the last one reads as the failure.
    for note in manager.notes or ([manager.note] if manager.note else []):
        err_console.print(f"[yellow]{escape(note)}[/yellow]")
    tools = manager.tools()
    if not tools:
        console.print("[dim]No MCP tools discovered.[/dim]")
    else:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Tool")
        table.add_column("Description", overflow="fold")
        for tool in tools:
            table.add_row(tool.name, tool.description)
        console.print(table)
    manager.close()


trace_app = typer.Typer(help="Inspect the flight-data recorder.")
app.add_typer(trace_app, name="trace")

#: Event kinds the OTLP reconstruction understands. Everything else (guardrail hits,
#: compactions, routing decisions) stays in the JSONL views, where it is greppable.
_SPAN_KINDS = ("turn_start", "turn_end", "model_call", "tool_call")


def _trace_path(cfg: Config):
    return cfg.observability.resolved_path() / "trace.jsonl"


def _parse_since(since: str) -> float:
    """``30s`` / ``15m`` / ``2h`` / ``7d`` → seconds. A bare number means seconds."""
    import re

    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhdw]?)\s*", since, re.I)
    if not match:
        raise typer.BadParameter(f"{since!r} is not a duration (try 30s, 15m, 2h, 7d)")
    scale = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return float(match.group(1)) * scale[match.group(2).lower()]


def _read_trace(
    path,
    *,
    session: str | None = None,
    kinds: tuple[str, ...] | None = None,
    after_ts: float | None = None,
    limit: int = 50,
    keep: int = 5,
) -> list[dict]:
    """The tail of the trace matching every filter, in chronological order.

    Filtering happens *before* the limit is applied and streams generation by generation,
    so ``--kind tool_call -n 50`` really shows fifty tool calls rather than whatever few
    survive the last fifty events of any kind.
    """
    from collections import deque

    from agent86.observability.recorder import iter_events, trace_generations

    if limit <= 0:
        return []
    events: list[dict] = []
    for generation in trace_generations(path, keep):
        remaining = limit - len(events)
        if remaining <= 0:
            break
        chunk: deque = deque(maxlen=remaining)
        for record in iter_events(generation):
            if session and record.get("session") != session:
                continue
            if kinds and record.get("kind") not in kinds:
                continue
            if after_ts is not None:
                try:
                    if float(record.get("ts", 0)) < after_ts:
                        continue
                except (TypeError, ValueError):
                    continue
            chunk.append(record)
        events = list(chunk) + events
    return events


def _clock(ts) -> str:
    import time as _time

    try:
        return _time.strftime("%H:%M:%S", _time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return ""


def _money(value) -> str:
    try:
        return f"${float(value):.4f}"
    except (TypeError, ValueError):
        return ""


@trace_app.command("path")
def trace_path_cmd() -> None:
    """Show the trace file location."""
    from agent86.observability.recorder import trace_generations

    cfg = _load()
    path = _trace_path(cfg)
    exists = "exists" if path.exists() else "not found"
    console.print(f"{path} ({exists})")
    rotated = [p for p in trace_generations(path, cfg.observability.keep_traces) if p != path]
    for older in rotated:
        console.print(f"[dim]{older} ({older.stat().st_size:,} bytes)[/dim]")


@trace_app.command("show")
def trace_show_cmd(
    session: str | None = typer.Option(None, "--session", "-s", help="Filter to one session."),
    limit: int = typer.Option(50, "--limit", "-n", help="Max events to show."),
    kind: Annotated[
        list[str] | None,
        typer.Option("--kind", "-k", help="Only this event kind (repeatable), e.g. -k tool_call."),
    ] = None,
    since: str | None = typer.Option(
        None, "--since", help="Only events newer than this duration, e.g. 30m, 2h, 7d."
    ),
) -> None:
    """Show recent events from the flight recorder."""
    import time as _time

    cfg = _load()
    after_ts = _time.time() - _parse_since(since) if since else None
    events = _read_trace(
        _trace_path(cfg),
        session=session,
        kinds=tuple(kind) if kind else None,
        after_ts=after_ts,
        limit=limit,
        keep=cfg.observability.keep_traces,
    )
    if not events:
        console.print("[dim]no trace events[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("time")
    table.add_column("session")
    table.add_column("kind")
    table.add_column("in", justify="right")
    table.add_column("out", justify="right")
    table.add_column("cost", justify="right")
    table.add_column("detail", overflow="fold")
    # Token and cost columns are only meaningful on a model_call; leaving them blank
    # elsewhere keeps the table readable and the totals honest.
    spent = 0.0
    tokens_in = tokens_out = 0
    for ev in events:
        is_call = ev.get("kind") == "model_call"
        cost = ev.get("cost_usd") if is_call else None
        if is_call:
            spent += float(cost or 0.0)
            tokens_in += int(ev.get("input_tokens") or 0)
            tokens_out += int(ev.get("output_tokens") or 0)
        skip = ("ts", "session", "kind", "input_tokens", "output_tokens", "cost_usd")
        detail = {k: v for k, v in ev.items() if k not in skip}
        table.add_row(
            _clock(ev.get("ts")),
            str(ev.get("session", ""))[:12],
            str(ev.get("kind", "")),
            str(ev.get("input_tokens", "")) if is_call else "",
            str(ev.get("output_tokens", "")) if is_call else "",
            _money(cost) if is_call and cost is not None else "",
            escape(str(detail)[:100]),
        )
    console.print(table)
    if tokens_in or tokens_out or spent:
        console.print(
            f"[dim]{tokens_in:,} in / {tokens_out:,} out tokens, {_money(spent)} "
            f"across {len(events)} event(s)[/dim]"
        )


@trace_app.command("export")
def trace_export_cmd(
    session: str | None = typer.Option(
        None, "--session", "-s", help="Export one session (default: every session in the trace)."
    ),
    fmt: str = typer.Option(
        "jsonl", "--format", "-f", help="jsonl (filtered events) | json (one array) | otlp-json."
    ),
    out: str | None = typer.Option(
        None, "--out", "-o", help="Write here instead of stdout."
    ),
    limit: int = typer.Option(100_000, "--limit", "-n", help="Max events to consider."),
    since: str | None = typer.Option(
        None, "--since", help="Only events newer than this duration, e.g. 2h."
    ),
) -> None:
    """Export the trace: raw events, or spans reconstructed into the OTLP JSON shape.

    otlp-json rebuilds a span tree from the recorder's own turn_start / turn_end /
    model_call / tool_call events, so a trace captured with no collector running can
    still be handed to one afterwards.
    """
    import json
    import time as _time

    choice = fmt.lower().replace("_", "-")
    if choice not in ("jsonl", "json", "otlp-json"):
        raise typer.BadParameter(f"unknown format {fmt!r} (jsonl | json | otlp-json)")

    cfg = _load()
    events = _read_trace(
        _trace_path(cfg),
        session=session,
        kinds=_SPAN_KINDS if choice == "otlp-json" else None,
        after_ts=(_time.time() - _parse_since(since)) if since else None,
        limit=limit,
        keep=cfg.observability.keep_traces,
    )

    if choice == "jsonl":
        text = "".join(json.dumps(ev, ensure_ascii=False) + "\n" for ev in events)
    elif choice == "json":
        text = json.dumps(events, ensure_ascii=False, indent=2) + "\n"
    else:
        text = json.dumps(otlp_document(events), ensure_ascii=False, indent=2) + "\n"

    if out is None:
        sys.stdout.write(text)
        return
    from pathlib import Path

    target = Path(out).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    console.print(f"Wrote {len(events)} event(s) to {target} ({choice}).")


# --------------------------------------------------------------------------- #
# OTLP JSON reconstruction
# --------------------------------------------------------------------------- #


def _otlp_id(*parts: object, width: int = 16) -> str:
    """A stable hex id derived from the event's own identity.

    The recorder never wrote span ids — it predates the tracer — so they are *derived*:
    the same trace exported twice produces the same ids, which is what makes re-exporting
    into a collector idempotent.
    """
    import hashlib

    digest = hashlib.sha1(":".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return digest[:width]


def _otlp_value(value: object) -> dict:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}  # OTLP JSON carries 64-bit ints as strings
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_otlp_value(v) for v in value]}}
    return {"stringValue": str(value)}


def _otlp_attributes(attributes: dict) -> list[dict]:
    return [
        {"key": key, "value": _otlp_value(value)}
        for key, value in attributes.items()
        if value is not None
    ]


def _nanos(ts) -> str:
    try:
        return str(int(float(ts) * 1_000_000_000))
    except (TypeError, ValueError):
        return "0"


def _span(
    *, name, trace_id, span_id, parent, start, end, attributes, status=0
) -> dict:
    span = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": 1,  # SPAN_KIND_INTERNAL
        "startTimeUnixNano": _nanos(start),
        "endTimeUnixNano": _nanos(end),
        "attributes": _otlp_attributes(attributes),
        "status": {"code": status},
    }
    if parent:
        span["parentSpanId"] = parent
    return span


def _session_spans(session: str, events: list[dict]) -> list[dict]:
    """Rebuild one session's span tree from its chronological events."""
    trace_id = _otlp_id(session, width=32)
    spans: list[dict] = []
    turn_id: str | None = None
    turn_start: float = 0.0
    turn_attrs: dict = {}
    turns = 0
    previous = events[0].get("ts", 0.0) if events else 0.0

    def close_turn(ts, extra: dict, status: int) -> None:
        nonlocal turn_id
        if turn_id is None:
            return
        spans.append(
            _span(
                name="turn", trace_id=trace_id, span_id=turn_id, parent=None,
                start=turn_start, end=ts,
                attributes={"session.id": session, **turn_attrs, **extra},
                status=status,
            )
        )
        turn_id = None

    for index, event in enumerate(events):
        kind = event.get("kind")
        ts = event.get("ts", previous)
        if kind == "turn_start":
            close_turn(ts, {}, 0)  # a turn with no turn_end (a crash) still gets a span
            turns += 1
            turn_id = _otlp_id(session, "turn", turns)
            turn_start = ts
            turn_attrs = {"agent86.task": event.get("task")}
        elif kind == "turn_end":
            status = 2 if event.get("status") in ("error", "blocked") else 1
            close_turn(
                ts,
                {
                    "agent86.status": event.get("status"),
                    "agent86.steps": event.get("steps"),
                    "agent86.reason": event.get("reason"),
                },
                status,
            )
        elif kind == "model_call":
            spans.append(
                _span(
                    name="model_call", trace_id=trace_id,
                    span_id=_otlp_id(session, "model", index), parent=turn_id,
                    start=previous, end=ts,
                    attributes={
                        "gen_ai.request.model": event.get("model"),
                        "gen_ai.usage.input_tokens": event.get("input_tokens"),
                        "gen_ai.usage.output_tokens": event.get("output_tokens"),
                        "gen_ai.response.finish_reasons": (
                            [event["stop_reason"]] if event.get("stop_reason") else None
                        ),
                        "agent86.cost_usd": event.get("cost_usd"),
                        "agent86.step": event.get("step"),
                    },
                    status=1,
                )
            )
        elif kind == "tool_call":
            ok = bool(event.get("ok"))
            spans.append(
                _span(
                    name="tool_call", trace_id=trace_id,
                    span_id=_otlp_id(session, "tool", index), parent=turn_id,
                    start=previous, end=ts,
                    attributes={
                        "tool.name": event.get("tool"),
                        "gen_ai.tool.name": event.get("tool"),
                        "tool.ok": ok,
                        "agent86.error": event.get("error"),
                    },
                    status=1 if ok else 2,
                )
            )
        previous = ts

    close_turn(previous, {"agent86.status": "unfinished"}, 0)
    return spans


def otlp_document(events: list[dict]) -> dict:
    """Wrap reconstructed spans in the OTLP/JSON envelope a collector accepts."""
    from agent86 import __version__

    by_session: dict[str, list[dict]] = {}
    for event in events:
        by_session.setdefault(str(event.get("session", "unknown")), []).append(event)

    spans: list[dict] = []
    for session, session_events in by_session.items():
        spans.extend(_session_spans(session, session_events))

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": _otlp_attributes(
                        {"service.name": "agent86", "service.version": __version__}
                    )
                },
                "scopeSpans": [
                    {"scope": {"name": "agent86", "version": __version__}, "spans": spans}
                ],
            }
        ]
    }


if __name__ == "__main__":
    app()
