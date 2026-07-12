"""The ``agent86`` command surface (Tier 1 entry point, user-facing).

Phase 1 wires the full CLI shape: an interactive REPL (default, no subcommand) plus
one-shot ``run`` and inspection commands (``config``, ``models``, ``skills``, ``mcp``,
``trace``). The cognitive loop that turns a goal into tool-using action lands in Phase 2;
where that plugs in is marked with ``# PHASE 2`` below.
"""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
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

app = typer.Typer(
    name="agent86",
    help="An agentic harness on the command line - connect to remote or local models "
    "and let them use tools and skills.",
    add_completion=False,
    no_args_is_help=False,
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

    cfg = load_config(overrides or None)
    ctx.obj = cfg

    if ctx.invoked_subcommand is None:
        _repl(cfg, resume=resume)


# --------------------------------------------------------------------------- #
# REPL (interactive)
# --------------------------------------------------------------------------- #


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


def _repl(cfg: Config, resume: str | None = None) -> None:
    """Interactive Reason -> Act -> Observe loop against the configured model."""
    from prompt_toolkit import PromptSession

    from agent86.cognitive.base import ProviderError
    from agent86.orchestration.loop import Harness, HarnessError

    console.print(_banner(cfg))

    session: PromptSession = PromptSession()

    def approval_prompt(tool_name: str, preview: str) -> bool:
        console.print(
            f"[yellow]approve[/yellow] [bold]{tool_name}[/bold] "
            f"[dim]{preview}[/dim]"
        )
        try:
            answer = session.prompt("  run it? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("y", "yes")

    try:
        harness = Harness(cfg, approval_prompt=approval_prompt)
    except ProviderError as exc:
        console.print(f"[red]Cannot start:[/red] {exc}")
        console.print(
            "[dim]Fix the key/config or choose another model with "
            "`agent86 --model provider:model`, then retry.[/dim]"
        )
        return

    if harness.memory_note:
        console.print(f"[dim]memory: {escape(harness.memory_note)}[/dim]")
    if harness.mcp_note:
        console.print(f"[dim]mcp: {escape(harness.mcp_note)}[/dim]")
    if harness.sandbox_note:
        console.print(f"[yellow]sandbox: {escape(harness.sandbox_note)}[/yellow]")
    if harness.skills:
        console.print(f"[dim]skills: {', '.join(harness.skills)}[/dim]")

    state = None
    if resume:
        state = harness.resume(resume)
        if state is None:
            console.print(f"[yellow]No session '{resume}' found; starting fresh.[/yellow]")
        else:
            console.print(
                f"[dim]resumed session {state.session_id} "
                f"({len(state.messages)} messages)[/dim]"
            )
    if state is None:
        state = harness.new_session()
    console.print(f"[dim]session {state.session_id}[/dim]")

    while True:
        try:
            line = session.prompt("agent86> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/dim]")
            return

        if not line:
            continue
        if line in ("/exit", "/quit"):
            console.print("[dim]bye[/dim]")
            return
        if line == "/help":
            _print_repl_help()
            continue
        if line == "/config":
            _show_config(cfg)
            continue
        if line == "/models":
            _list_models(cfg)
            continue
        if line == "/tools":
            console.print("[dim]tools:[/dim] " + ", ".join(harness.registry.names()))
            continue
        if line == "/skills":
            if harness.skills:
                for s in harness.skills.values():
                    console.print(f"  [cyan]{s.name}[/cyan] - {s.description}")
            else:
                console.print("[dim]no skills discovered[/dim]")
            continue
        if line == "/memory":
            if harness.memory:
                c = harness.memory.store.counts()
                console.print(
                    f"[dim]memory[/dim] sessions {c['sessions']}  "
                    f"episodes {c['episodes']}  facts {c['memories']}  "
                    f"[dim]session[/dim] {state.session_id}"
                )
            else:
                console.print("[dim]memory is disabled[/dim]")
            continue
        if line == "/cost":
            _show_cost(state)
            continue
        if line == "/clear":
            state = harness.new_session()
            console.print("[dim]conversation cleared[/dim]")
            continue

        console.print("[bold cyan]agent86[/bold cyan] ", end="")
        printed_any = False
        try:
            for delta in harness.run_turn(line, state):
                if delta.text:
                    _emit(delta.text)
                    printed_any = True
        except (ProviderError, HarnessError) as exc:
            console.print(f"\n[red]error:[/red] {exc}")
            continue
        if not printed_any:
            console.print("[dim](no response)[/dim]", end="")
        console.print()  # end the streamed line


def _show_cost(state) -> None:
    u = state.usage
    console.print(
        f"[dim]steps[/dim] {state.step_count}  "
        f"[dim]in[/dim] {u.input_tokens}  [dim]out[/dim] {u.output_tokens} tok  "
        f"[dim]cost[/dim] ${u.cost_usd:.4f}"
    )


def _print_repl_help() -> None:
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_row("[cyan]/help[/cyan]", "Show this help")
    table.add_row("[cyan]/config[/cyan]", "Show the resolved configuration")
    table.add_row("[cyan]/models[/cyan]", "List configured models")
    table.add_row("[cyan]/tools[/cyan]", "List available tools")
    table.add_row("[cyan]/skills[/cyan]", "List available skills")
    table.add_row("[cyan]/memory[/cyan]", "Show memory stats and session id")
    table.add_row("[cyan]/cost[/cyan]", "Show token usage and cost this session")
    table.add_row("[cyan]/clear[/cyan]", "Start a fresh conversation")
    table.add_row("[cyan]/exit[/cyan]", "Quit")
    console.print(table)


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

    Without --yes, side-effecting tools are declined (no TTY to approve them); read-only
    tools always run. Pass --yes to let the agent act autonomously.
    """
    import json as _json

    from agent86.cognitive.base import ProviderError
    from agent86.orchestration.loop import Harness, HarnessError
    from agent86.types import ApprovalMode

    cfg: Config = ctx.obj or load_config()
    if yes:
        cfg.guardrails.approval = ApprovalMode.AUTO

    try:
        harness = Harness(cfg)
    except ProviderError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from None

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
        err_console.print(f"\n[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from None

    if as_json:
        # Honor the egress guardrail (e.g. redact mode) on the machine-readable output.
        output = harness.egress.inspect("".join(parts)).text
        console.print_json(
            _json.dumps(
                {
                    "session_id": state.session_id,
                    "output": output,
                    "steps": state.step_count,
                    "usage": state.usage.model_dump(),
                }
            )
        )
    else:
        console.print()


# --------------------------------------------------------------------------- #
# `agent86 config`
# --------------------------------------------------------------------------- #

config_app = typer.Typer(help="Inspect configuration.")
app.add_typer(config_app, name="config")


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
    _show_config(load_config())


def _show_config(cfg: Config) -> None:
    console.print_json(cfg.model_dump_json(indent=2))


# --------------------------------------------------------------------------- #
# `agent86 models`
# --------------------------------------------------------------------------- #


@app.command()
def models(ctx: typer.Context) -> None:
    """List configured models and providers."""
    cfg: Config = ctx.obj or load_config()
    _list_models(cfg)


def _list_models(cfg: Config) -> None:
    table = Table(show_header=True, header_style="bold", title="Providers")
    table.add_column("Provider")
    table.add_column("Base URL")
    table.add_column("API key env")
    for name, prov in cfg.providers.items():
        table.add_row(name, prov.base_url or "[dim]-[/dim]", prov.api_key_env or "[dim]-[/dim]")
    console.print(table)

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
    from agent86.memory.system import build_memory

    cfg = load_config()
    mem = build_memory(cfg)
    if mem is None:
        err_console.print("[yellow]Memory is disabled in config.[/yellow]")
        raise typer.Exit(code=1)
    if mem.note:
        err_console.print(f"[dim]memory: {mem.note}[/dim]")
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


# --------------------------------------------------------------------------- #
# `agent86 skills` / `mcp` / `trace`  -  scaffolded stubs
# --------------------------------------------------------------------------- #

skills_app = typer.Typer(help="Manage skills.")
app.add_typer(skills_app, name="skills")


@skills_app.command("list")
def skills_list_cmd() -> None:
    """List discovered skills."""
    from agent86.skills.loader import default_skill_paths, discover_skills

    cfg = load_config()
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

    skills = discover_skills(load_config())
    skill = skills.get(name)
    if skill is None:
        known = ", ".join(skills) or "(none)"
        err_console.print(f"[red]No skill named '{name}'.[/red] Known: {known}")
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
    cfg: Config = load_config()
    if not cfg.mcp_servers:
        console.print("[dim]No MCP servers configured.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Command")
    for name, srv in cfg.mcp_servers.items():
        table.add_row(name, " ".join([srv.command, *srv.args]))
    console.print(table)


@mcp_app.command("tools")
def mcp_tools_cmd() -> None:
    """Start configured MCP servers and list the tools they expose."""
    from agent86.tools.mcp_client import build_mcp

    cfg = load_config()
    manager = build_mcp(cfg)
    if manager is None:
        console.print("[dim]No MCP servers configured (or MCP disabled).[/dim]")
        return
    if manager.note:
        err_console.print(f"[yellow]{manager.note}[/yellow]")
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


@trace_app.command("path")
def trace_path_cmd() -> None:
    """Show the trace file location."""
    cfg = load_config()
    path = cfg.observability.resolved_path() / "trace.jsonl"
    exists = "exists" if path.exists() else "not found"
    console.print(f"{path} ({exists})")


@trace_app.command("show")
def trace_show_cmd(
    session: str | None = typer.Option(None, "--session", "-s", help="Filter to one session."),
    limit: int = typer.Option(50, "--limit", "-n", help="Max events to show."),
) -> None:
    """Show recent events from the flight recorder."""
    from agent86.observability.recorder import read_events

    cfg = load_config()
    path = cfg.observability.resolved_path() / "trace.jsonl"
    events = read_events(path, session_id=session, limit=limit)
    if not events:
        console.print("[dim]no trace events[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("session")
    table.add_column("kind")
    table.add_column("detail", overflow="fold")
    for ev in events:
        detail = {k: v for k, v in ev.items() if k not in ("ts", "session", "kind")}
        table.add_row(str(ev.get("session", ""))[:12], str(ev.get("kind", "")), str(detail)[:100])
    console.print(table)


if __name__ == "__main__":
    app()
