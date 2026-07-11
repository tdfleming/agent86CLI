"""The ``agent86`` command surface (Tier 1 entry point, user-facing).

Phase 1 wires the full CLI shape: an interactive REPL (default, no subcommand) plus
one-shot ``run`` and inspection commands (``config``, ``models``, ``skills``, ``mcp``,
``trace``). The cognitive loop that turns a goal into tool-using action lands in Phase 2;
where that plugs in is marked with ``# PHASE 2`` below.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent86 import __version__
from agent86.config import Config, config_paths, load_config
from agent86.types import ModelRef

console = Console()
err_console = Console(stderr=True)

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
        _repl(cfg)


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


def _repl(cfg: Config) -> None:
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

    state = harness.new_session()

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
        if line == "/cost":
            _show_cost(state)
            continue
        if line == "/clear":
            state = harness.new_session()
            console.print("[dim]conversation cleared[/dim]")
            continue

        console.print("[bold cyan]agent86[/bold cyan] ", end="")
        try:
            for delta in harness.run_turn(line, state):
                if delta.text:
                    console.print(delta.text, end="", markup=False, highlight=False, soft_wrap=True)
        except (ProviderError, HarnessError) as exc:
            console.print(f"\n[red]error:[/red] {exc}")
            continue
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

    state = harness.new_session()
    parts: list[str] = []
    try:
        for delta in harness.run_turn(goal, state):
            if delta.text:
                parts.append(delta.text)
                if not as_json:
                    console.print(delta.text, end="", markup=False, highlight=False, soft_wrap=True)
    except (ProviderError, HarnessError) as exc:
        err_console.print(f"\n[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from None

    if as_json:
        console.print_json(
            _json.dumps(
                {
                    "session_id": state.session_id,
                    "output": "".join(parts),
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
# `agent86 skills` / `mcp` / `trace`  -  scaffolded stubs
# --------------------------------------------------------------------------- #

skills_app = typer.Typer(help="Manage skills (Phase 6).")
app.add_typer(skills_app, name="skills")


@skills_app.command("list")
def skills_list_cmd() -> None:
    """List discovered skills."""
    console.print("[dim]Skills load in Phase 6 (see docs/ARCHITECTURE.md).[/dim]")


mcp_app = typer.Typer(help="Manage MCP servers (Phase 6).")
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


trace_app = typer.Typer(help="Inspect the flight-data recorder (Phase 5).")
app.add_typer(trace_app, name="trace")


@trace_app.command("show")
def trace_show_cmd() -> None:
    """Show recent traces."""
    console.print("[dim]Tracing lands in Phase 5 (see docs/ARCHITECTURE.md).[/dim]")


if __name__ == "__main__":
    app()
