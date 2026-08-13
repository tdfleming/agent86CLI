"""The full-screen `Agent86App(App)` — the TUI shell (TUI-01, TUI-02, TUI-05).

Composes a scrollable transcript, a prompt input, and a live status footer; runs turns on a
Textual thread worker (the harness's `run_turn` generator stays synchronous, per CONTEXT.md
lock), streams deltas into the transcript, keeps the footer live during processing, and pops a
modal to resolve tool-approval requests. Textual is only ever imported by this module and by
whatever calls `run_tui` — never at `cli.py` module-import time (RESEARCH Pitfall 1).
"""

from __future__ import annotations

from textual import work
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from agent86.config import Config
from agent86.tui.commands import (
    COMMANDS,
    find_command,
    find_command_for_line,
    handle_command,
    startup_notes,
)
from agent86.tui.messages import (
    ApprovalRequest,
    CatalogReady,
    ToolAnnounce,
    TurnDelta,
    TurnDone,
    TurnError,
)
from agent86.tui.screens.approval import ApprovalModal
from agent86.tui.screens.connection_test import ConnectionTestModal, TestOutcome
from agent86.tui.screens.key_entry import KeyEntryModal
from agent86.tui.screens.mcp_manager import (
    MCPManagerModal,
    MCPServerDraft,
    MCPServerFormModal,
    mcp_server_rows,
)
from agent86.tui.screens.mcp_test import MCPTestModal, MCPTestOutcome
from agent86.tui.screens.mode_picker import ModePickerModal
from agent86.tui.screens.model_picker import ModelPickerModal, model_choices, prefix_catalog_refs
from agent86.tui.screens.provider_manager import (
    CatalogPickerModal,
    ProviderManagerModal,
    provider_rows,
)
from agent86.tui.screens.save_diff import SaveDiffModal
from agent86.tui.turn_bridge import run_turn_worker
from agent86.tui.widgets.status_footer import StatusFooter

__all__ = ["Agent86App", "run_tui"]


class Agent86App(App):
    """The default interactive UI: transcript + prompt + live status footer."""

    BINDINGS = [
        Binding("shift+tab", "cycle_mode", "cycle approval mode", priority=True),
        Binding("up", "palette_up", show=False, priority=True),
        Binding("down", "palette_down", show=False, priority=True),
        Binding("escape", "palette_dismiss", show=False, priority=True),
    ]

    CSS = """
    #transcript {
        height: 1fr;
    }
    #stream {
        height: auto;
    }
    #palette {
        display: none;
        max-height: 10;
        border: round $accent;
    }
    #status {
        dock: bottom;
    }
    #provider-manager-dialog, #catalog-picker-dialog, #key-entry-dialog,
    #connection-test-dialog, #save-diff-dialog, #mcp-manager-dialog,
    #mcp-form-dialog, #mcp-test-dialog {
        width: 80%;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #catalog-list, #provider-list, #mcp-server-list {
        max-height: 15;
    }
    #save-diff-scroll, #mcp-test-tools-scroll {
        max-height: 20;
    }
    #mcp-json {
        height: 10;
    }
    """

    def __init__(self, repl) -> None:  # noqa: ANN001
        super().__init__()
        self.repl = repl
        self._stream_buf = ""
        # D-04: live model catalogs are cached for this app session only — one fetch per
        # provider per launch, lazily on first use. No on-disk cache, no TTL, no invalidation.
        # RESEARCH Open Question 3: this lives on the App, not on _Repl/Harness — the plain
        # loop never needs a catalog.
        self._catalog_cache: dict[str, list[tuple[str, str]]] = {}
        self._pending_row = None  # ProviderRow being configured
        self._pending_key: str | None = None  # entered key, in memory only until the test passes
        self._pending_ref: str | None = None  # chosen provider:model ref
        # /config mcp chain state — reset by _open_mcp_manager on every entry.
        self._mcp_draft: MCPServerDraft | None = None
        self._mcp_overrides: dict[str, str] = {}   # ${VAR} name -> value typed this pass
        self._mcp_pending_vars: list[str] = []     # names still to prompt for
        self._mcp_started: str | None = None       # server left running by a passing test
        self._mcp_action: str | None = None        # "add" | "edit" | "remove" | "toggle"
        self._mcp_unmount: str | None = None       # name pending remove/disable confirmation

    # ---- composition ---------------------------------------------------- #

    def compose(self) -> ComposeResult:
        yield RichLog(id="transcript", markup=True, wrap=True, highlight=False)
        yield Static(id="stream")
        yield OptionList(id="palette")
        yield Input(id="prompt", placeholder="agent86> ")
        yield StatusFooter(id="status")

    def on_mount(self) -> None:
        self.query_one("#status", StatusFooter).status = self.repl.status
        log = self.query_one("#transcript", RichLog)
        for note in startup_notes(self.repl):
            log.write(f"[dim]{note}[/dim]")
        self.query_one("#palette", OptionList).display = False
        self.query_one("#prompt", Input).focus()

    # ---- palette ----------------------------------------------------------- #

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "prompt":
            return
        self._sync_palette(event.value)

    def _sync_palette(self, text: str) -> None:
        palette = self.query_one("#palette", OptionList)
        if not text.startswith("/") or " " in text:
            palette.display = False
            return
        matches = [c for c in COMMANDS if c.name.startswith(text)]
        palette.display = bool(matches)
        if matches:
            palette.clear_options()
            palette.add_options(
                Option(f"{c.name}  [dim]{c.description}[/dim]", id=c.name) for c in matches
            )
            palette.highlighted = 0

    # ---- input submission ------------------------------------------------ #

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Only the prompt Input dispatches lines. A modal's Input (key entry, catalog filter)
        # must never reach _dispatch_line — see UAT gap 1; mirrors the on_input_changed guard.
        if event.input.id != "prompt":
            return
        # Approach B (02-02-SUMMARY.md): no permanent priority `enter` Binding is registered at
        # the App level, so Input.Submitted still fires normally when the palette is closed. An
        # open palette consumes this Enter itself, before the typed-line dispatch below.
        palette = self.query_one("#palette", OptionList)
        if palette.display:
            self._select_palette()
            return
        line = event.value.strip()
        event.input.value = ""
        if not line:
            return
        self._dispatch_line(line)

    def _dispatch_line(self, line: str) -> None:
        """Run one command/turn line through the existing execution path.

        Shared by typed Input submission and picker-chained selections (palette / /model /
        /mode) so both paths behave identically.
        """
        log = self.query_one("#transcript", RichLog)
        log.write(f"[bold]> {line}[/bold]")

        # A bare needs_choice command (no argument) typed directly — not just palette-selected —
        # opens the same picker/chain as picking it from the palette (mirrors _select_palette).
        match = find_command_for_line(line)
        if match is not None:
            entry, arg = match
            if entry.needs_choice and not arg:
                self._run_or_chain(entry)
                return

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

    # ---- palette selection + picker chaining -------------------------------- #

    def action_palette_up(self) -> None:
        # These bindings are registered with priority=True (App-level, checked before the
        # focused widget's own bindings — see RESEARCH/02-02-SUMMARY.md). When the palette is
        # hidden — e.g. while a ModePickerModal/ModelPickerModal is on top and its RadioSet /
        # OptionList owns up/down/escape — raising SkipAction lets the key event fall through to
        # that widget's own binding instead of being silently swallowed here.
        palette = self.query_one("#palette", OptionList)
        if not palette.display:
            raise SkipAction()
        palette.action_cursor_up()

    def action_palette_down(self) -> None:
        palette = self.query_one("#palette", OptionList)
        if not palette.display:
            raise SkipAction()
        palette.action_cursor_down()

    def action_palette_dismiss(self) -> None:
        palette = self.query_one("#palette", OptionList)
        if not palette.display:
            raise SkipAction()
        palette.display = False

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "palette":
            self._select_palette()

    def _select_palette(self) -> None:
        palette = self.query_one("#palette", OptionList)
        highlighted = palette.highlighted
        if highlighted is None:
            palette.display = False
            return
        option = palette.get_option_at_index(highlighted)
        name = option.id
        palette.display = False
        prompt = self.query_one("#prompt", Input)
        prompt.value = ""
        entry = find_command(name)
        if entry is not None:
            self._run_or_chain(entry)

    def _run_or_chain(self, entry) -> None:  # noqa: ANN001
        if entry.needs_choice == "mode":
            self.push_screen(
                ModePickerModal(self.repl.harness.gate.mode.value), self._on_mode_picked
            )
        elif entry.needs_choice == "model":
            active = self.repl.harness.provider.name
            cached = self._catalog_cache.get(active)
            if cached is None:
                # D-04: one lazy fetch per provider per session; the picker opens from
                # on_catalog_ready(purpose="model_picker").
                from agent86.config import ProviderConfig
                from agent86.secrets import resolve_api_key

                pconf = self.repl.cfg.providers.get(active, ProviderConfig())
                self._request_catalog(
                    active, resolve_api_key(active, pconf.api_key_env), "model_picker"
                )
                return
            self._open_model_picker(cached)
        elif entry.needs_choice == "config_model":
            self._open_provider_manager()
        elif entry.needs_choice == "config_mcp":
            self._open_mcp_manager()
        else:
            self._dispatch_line(entry.name)

    def _on_mode_picked(self, value: str | None) -> None:
        if value is not None:
            self._dispatch_line(f"/mode {value}")

    def _on_model_picked(self, value: str | None) -> None:
        if value is not None:
            self._dispatch_line(f"/model {value}")

    def _open_model_picker(self, extra: list[tuple[str, str]]) -> None:
        # The catalog yields BARE model ids (catalog.py's documented contract); only a full
        # `provider:model` ref survives ModelRef.parse. Prefix BEFORE model_choices so its
        # role-slot dedupe compares full refs against full refs.
        provider = self.repl.harness.provider.name
        choices = model_choices(self.repl.cfg, extra=prefix_catalog_refs(provider, extra))
        if not choices:
            prompt = self.query_one("#prompt", Input)
            prompt.value = "/model "
            prompt.focus()
            return
        self.push_screen(ModelPickerModal(choices), self._on_model_picked)

    # ---- /config model chain ------------------------------------------------ #

    def _open_provider_manager(self) -> None:
        self._pending_row = None
        self._pending_key = None
        self._pending_ref = None
        self.push_screen(ProviderManagerModal(provider_rows(self.repl.cfg)), self._on_provider_row)

    def _on_provider_row(self, row) -> None:  # noqa: ANN001 - ProviderRow | None
        if row is None:
            return
        self._pending_row = row
        if row.keyless or row.has_key:
            self._request_catalog(row.name, self._resolved_key(row), "manager")
            return
        # D-05: a provider with no key is not a dead end — chain straight into key entry.
        from agent86.secrets import keyring_available

        self.push_screen(KeyEntryModal(row.name, keyring_available()), self._on_key_entered)

    def _resolved_key(self, row) -> str | None:  # noqa: ANN001
        from agent86.secrets import resolve_api_key

        return resolve_api_key(row.name, row.api_key_env)

    def _on_key_entered(self, key: str | None) -> None:
        if not key:
            return
        # D-14: held in memory only; written to the keyring after the test passes.
        self._pending_key = key
        self._request_catalog(self._pending_row.name, key, "manager")

    def _on_catalog_picked(self, ref: str | None) -> None:
        if ref is None:
            return
        from agent86.cognitive.base import UNRESOLVED
        from agent86.types import ModelRef

        try:
            parsed = ModelRef.parse(ref)
        except ValueError as exc:
            self.query_one("#transcript", RichLog).write(f"[red]error:[/red] {exc}")
            return
        self._pending_ref = ref
        # UAT gap 4: `None` means "the user explicitly supplied an empty key" to
        # provider_for_ref, which then SKIPS env/keyring resolution. When no key was typed
        # this pass, hand over the UNRESOLVED sentinel so the already-stored keyring entry
        # (D-07) is resolved instead of erroring with "No Anthropic API key found".
        api_key = self._pending_key if self._pending_key is not None else UNRESOLVED
        self.push_screen(
            ConnectionTestModal(self.repl.cfg, parsed, api_key), self._on_test_done
        )

    def _on_test_done(self, outcome: TestOutcome) -> None:
        log = self.query_one("#transcript", RichLog)
        if not outcome.ok and not outcome.override:
            log.write(f"[red]connection test failed:[/red] {outcome.error}")
            return
        if not outcome.ok:
            log.write(f"[yellow]saving anyway despite:[/yellow] {outcome.error}")
        # D-14: the key becomes persistent only now.
        if self._pending_key and self._pending_row is not None:
            from agent86.secrets import SecretStoreError, store_api_key

            try:
                store_api_key(self._pending_row.name, self._pending_key)
                log.write(f"[dim]key stored in the OS keyring for {self._pending_row.name}[/dim]")
            except SecretStoreError as exc:
                log.write(f"[red]could not store the key:[/red] {exc}")
            finally:
                self._pending_key = None
        # D-18 / success criterion 4: the switch applies to the next turn immediately.
        if outcome.ok:
            self._dispatch_line(f"/model {self._pending_ref}")
        self.push_screen(SaveDiffModal(self._persist_changes()), self._on_save_confirmed)

    def _persist_changes(self) -> list[tuple[list[str], object]]:
        """What a save would write. Never includes a secret — only the env var NAME (D-06)."""
        changes: list[tuple[list[str], object]] = [(["model", "default"], self._pending_ref)]
        row = self._pending_row
        if row is not None and not row.keyless and not row.api_key_env:
            changes.append(
                (["providers", row.name, "api_key_env"], f"{row.name.upper()}_API_KEY")
            )
        if row is not None and row.base_url:
            changes.append((["providers", row.name, "base_url"], row.base_url))
        return changes

    def _on_save_confirmed(self, edit) -> None:  # noqa: ANN001 - ConfigEdit | None
        log = self.query_one("#transcript", RichLog)
        if edit is None:
            log.write("[dim]not saved — the model switch applies to this session only[/dim]")
            return
        from agent86.config_writer import ConfigWriteError, apply_edit

        try:
            self.repl.cfg = apply_edit(edit)
        except ConfigWriteError as exc:
            log.write(f"[red]could not save:[/red] {exc}")
            return
        log.write(f"[dim]saved to {edit.path}[/dim]")

    # ---- /config mcp chain -------------------------------------------------- #

    def _open_mcp_manager(self) -> None:
        self._mcp_draft = None
        self._mcp_overrides = {}
        self._mcp_pending_vars = []
        self._mcp_started = None
        self._mcp_action = None
        self.push_screen(MCPManagerModal(mcp_server_rows(self.repl.cfg)), self._on_mcp_action)

    def _on_mcp_action(self, action) -> None:  # noqa: ANN001 - MCPManagerAction | None
        if action is None:
            return
        names = set(self.repl.cfg.mcp_servers)
        if action.kind in ("add_json", "add_manual"):
            self._mcp_action = "add"
            mode = "json" if action.kind == "add_json" else "manual"
            self.push_screen(MCPServerFormModal(mode=mode, existing_names=names), self._on_mcp_form)
            return
        srv = self.repl.cfg.mcp_servers.get(action.name or "")
        if srv is None:
            return
        if action.kind == "edit":
            self._mcp_action = "edit"
            draft = MCPServerDraft(name=action.name, cfg=srv, original_name=action.name)
            mode = "manual" if srv.command else "manual"   # edit always uses the field form
            self.push_screen(
                MCPServerFormModal(mode=mode, existing_names=names, draft=draft),
                self._on_mcp_form,
            )
            return
        # remove / toggle
        self._on_mcp_destructive(action.kind, action.name, srv)

    def _on_mcp_form(self, draft) -> None:  # noqa: ANN001 - MCPServerDraft | None
        if draft is None:
            return
        self._mcp_draft = draft
        self._prompt_next_var()

    def _prompt_next_var(self) -> None:
        """D-18: resolve every unresolved ${VAR} through the ONE masked entry modal, then test."""
        from agent86.secrets import keyring_available
        from agent86.tools.mcp_client import unresolved_var_refs

        assert self._mcp_draft is not None
        missing = unresolved_var_refs(self._mcp_draft.cfg, self._mcp_overrides)
        if missing:
            self.push_screen(KeyEntryModal(missing[0], keyring_available()), self._on_var_entered)
            return
        self._start_mcp_test()

    def _on_var_entered(self, value: str | None) -> None:
        if not value or self._mcp_draft is None:
            # Cancelling a required secret aborts the whole add — connecting with an empty
            # credential would produce a misleading auth failure.
            self.query_one("#transcript", RichLog).write("[dim]mcp: cancelled[/dim]")
            self._mcp_draft = None
            return
        from agent86.tools.mcp_client import unresolved_var_refs

        missing = unresolved_var_refs(self._mcp_draft.cfg, self._mcp_overrides)
        if missing:
            self._mcp_overrides[missing[0]] = value
        self._prompt_next_var()

    def _start_mcp_test(self) -> None:
        assert self._mcp_draft is not None
        manager = self.repl.harness.ensure_mcp()
        self.push_screen(
            MCPTestModal(
                manager, self._mcp_draft.name, self._mcp_draft.cfg, dict(self._mcp_overrides)
            ),
            self._on_mcp_test_done,
        )

    def _on_mcp_test_done(self, outcome: MCPTestOutcome) -> None:
        log = self.query_one("#transcript", RichLog)
        draft = self._mcp_draft
        if draft is None:
            return
        if outcome.ok:
            self._mcp_started = draft.name       # the test left it mounted (D-13)
            log.write(f"[dim]mcp: {draft.name} connected, {len(outcome.tools)} tools[/dim]")
        elif outcome.override:
            log.write(f"[yellow]saving anyway despite:[/yellow] {outcome.error}")
        else:
            log.write(f"[red]mcp connection test failed:[/red] {outcome.error}")
            self._mcp_draft = None
            return
        # D-14 precedent: a typed secret becomes persistent only once the test has passed
        # (or the user explicitly overrode). Keyed by ${VAR} NAME, not provider name.
        if self._mcp_overrides:
            from agent86.secrets import SecretStoreError, store_api_key

            for var_name, value in self._mcp_overrides.items():
                try:
                    store_api_key(var_name, value)
                    log.write(f"[dim]stored ${{{var_name}}} in the OS keyring[/dim]")
                except SecretStoreError as exc:
                    log.write(f"[red]could not store ${{{var_name}}}:[/red] {exc}")
            self._mcp_overrides = {}
        self.push_screen(SaveDiffModal(self._mcp_changes(draft)), self._on_mcp_save_confirmed)

    def _mcp_changes(self, draft) -> list[tuple[list[str], object]]:  # noqa: ANN001
        """The TOML this add/edit would write. Secrets stay as ${VAR} references (D-17).

        Every header and env value is written as its OWN key path — writing the whole `headers`
        dict under one leaf key would slip straight past config_writer's leaf-key secret guard,
        which is exactly the SEC-01 hole this phase closes.
        """
        base = ["mcp", "servers", draft.name]
        cfg = draft.cfg
        changes: list[tuple[list[str], object]] = []
        if cfg.command:
            changes.append(([*base, "command"], cfg.command))
            changes.append(([*base, "args"], list(cfg.args)))
        if cfg.url:
            changes.append(([*base, "url"], cfg.url))
            changes.append(([*base, "transport"], cfg.transport))
        for key, value in cfg.env.items():
            changes.append(([*base, "env", key], value))
        for key, value in cfg.headers.items():
            changes.append(([*base, "headers", key], value))
        changes.append(([*base, "enabled"], cfg.enabled))
        if draft.original_name and draft.original_name != draft.name:
            from agent86.config_writer import DELETE

            changes.append((["mcp", "servers", draft.original_name], DELETE))
        return changes

    def _on_mcp_save_confirmed(self, edit) -> None:  # noqa: ANN001 - ConfigEdit | None
        log = self.query_one("#transcript", RichLog)
        draft, self._mcp_draft = self._mcp_draft, None
        started, self._mcp_started = self._mcp_started, None
        if edit is None:
            log.write("[dim]not saved[/dim]")
            # D-13: a cancelled add must not leave the just-started server running all session.
            if started and self.repl.harness.mcp is not None:
                self.repl.harness.mcp.stop_server(started)
            return
        from agent86.config_writer import ConfigWriteError, apply_edit

        try:
            self.repl.cfg = apply_edit(edit)
        except ConfigWriteError as exc:
            log.write(f"[red]could not save:[/red] {exc}")
            return
        log.write(f"[dim]saved to {edit.path}[/dim]")
        if draft is None:
            return
        if draft.original_name:
            self.repl.harness.remove_mcp_server(draft.original_name)
        if started != draft.name:
            # D-16: the config write succeeded; the live mount did not. Report both, never roll back.
            log.write(
                f"[yellow]saved, but {draft.name} is not running:[/yellow] "
                "it will be available next launch"
            )
            return
        mounted, collisions = self.repl.harness.add_mcp_server(draft.name, draft.cfg)
        line = f"[dim]mcp: {draft.name} mounted, {len(mounted)} tools live[/dim]"
        if collisions:
            line += f" [yellow](name collisions, not mounted: {', '.join(collisions)})[/yellow]"
        log.write(line)

    def _on_mcp_destructive(self, kind: str, name: str, srv) -> None:  # noqa: ANN001
        """Remove (D-10/D-11) and enable/disable (D-09/D-12) — both via the normal diff flow.

        There is deliberately no extra confirmation dialog and no silent fast-path toggle: the
        diff preview already shows the exact block being removed or the exact one-line change,
        and requires an explicit confirm. Phase 3's guarantee is that the user always knows which
        file changed; the first write that skips the diff would break it.
        """
        from agent86.config_writer import DELETE

        if kind == "toggle" and not srv.enabled:
            # Re-enabling is an add: test the server before mounting it, reusing the whole
            # form-free part of the add chain.
            self._mcp_action = "add"
            self._mcp_draft = MCPServerDraft(name=name, cfg=srv.model_copy(update={"enabled": True}))
            self._prompt_next_var()
            return
        self._mcp_action = kind
        self._mcp_unmount = name
        if kind == "remove":
            changes = [(["mcp", "servers", name], DELETE)]
        else:
            changes = [(["mcp", "servers", name, "enabled"], False)]
        self.push_screen(SaveDiffModal(changes), self._on_mcp_unmount_confirmed)

    def _on_mcp_unmount_confirmed(self, edit) -> None:  # noqa: ANN001 - ConfigEdit | None
        log = self.query_one("#transcript", RichLog)
        name, self._mcp_unmount = self._mcp_unmount, None
        if edit is None or name is None:
            log.write("[dim]not saved[/dim]")
            return
        from agent86.config_writer import ConfigWriteError, apply_edit

        try:
            self.repl.cfg = apply_edit(edit)
        except ConfigWriteError as exc:
            log.write(f"[red]could not save:[/red] {exc}")
            return
        log.write(f"[dim]saved to {edit.path}[/dim]")
        # D-14: unmount immediately — leaving a removed server's tools callable would let the
        # model invoke something the user just deleted.
        self.repl.harness.remove_mcp_server(name)
        verb = "removed" if self._mcp_action == "remove" else "disabled"
        log.write(f"[dim]mcp: {name} {verb}; its tools are no longer available[/dim]")

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

    # ---- model catalog (session cache) -------------------------------------- #

    def _request_catalog(self, provider: str, api_key: str | None, purpose: str) -> None:
        """Serve the catalog from the session cache, or fetch it on a worker thread."""
        cached = self._catalog_cache.get(provider)
        if cached is not None:
            self.post_message(CatalogReady(provider, cached, None, purpose))
            return
        self.query_one("#transcript", RichLog).write(
            f"[dim]fetching {provider} model catalog…[/dim]"
        )
        self._fetch_catalog(provider, api_key, purpose)

    @work(thread=True)
    def _fetch_catalog(self, provider: str, api_key: str | None, purpose: str) -> None:
        from agent86.cognitive.catalog import CatalogUnavailable, fetch_catalog
        from agent86.config import ProviderConfig

        pconf = self.repl.cfg.providers.get(provider, ProviderConfig())
        try:
            entries = fetch_catalog(provider, pconf, api_key)
        except CatalogUnavailable as exc:
            self.post_message(CatalogReady(provider, [], str(exc), purpose))
            return
        except Exception as exc:  # noqa: BLE001 - any failure falls back to free text (D-01)
            self.post_message(CatalogReady(provider, [], str(exc), purpose))
            return
        self.post_message(CatalogReady(provider, entries, None, purpose))

    # ---- message handlers (main thread) ------------------------------------ #

    def on_catalog_ready(self, message: CatalogReady) -> None:
        if message.error is None:
            self._catalog_cache[message.provider] = message.entries
        else:
            self.query_one("#transcript", RichLog).write(
                f"[yellow]catalog unavailable:[/yellow] {message.error} "
                "[dim](enter a model name directly)[/dim]"
            )
        if message.purpose == "model_picker":
            self._open_model_picker(message.entries)
            return
        self.push_screen(
            CatalogPickerModal(message.provider, message.entries), self._on_catalog_picked
        )

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
        # `shift+tab` is a priority binding (App-level, checked before focus-traversal and the
        # focused widget's own bindings — see RESEARCH/02-02-SUMMARY.md). While a modal
        # (ApprovalModal / ModePickerModal / ModelPickerModal) is pushed, Shift+Tab must fall
        # through to that screen's own focus/traversal handling instead of cycling the approval
        # mode underneath it — mirrors the `action_palette_up`/`_down`/`_dismiss` SkipAction
        # pattern above.
        if len(self.screen_stack) > 1:
            raise SkipAction()
        self.repl._cycle_approval()
        self.query_one("#status", StatusFooter).status = self.repl.status


def run_tui(cfg: Config, resume: str | None = None) -> None:
    """Build the harness/state/status (reusing `_Repl`) and run `Agent86App`."""
    from agent86.ui.repl import _Repl

    repl = _Repl(cfg, resume)
    Agent86App(repl).run()
