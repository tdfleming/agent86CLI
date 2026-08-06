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
from agent86.tui.screens.mode_picker import ModePickerModal
from agent86.tui.screens.model_picker import ModelPickerModal, model_choices
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
    #connection-test-dialog, #save-diff-dialog {
        width: 80%;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #catalog-list, #provider-list {
        max-height: 15;
    }
    #save-diff-scroll {
        max-height: 20;
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
        else:
            self._dispatch_line(entry.name)

    def _on_mode_picked(self, value: str | None) -> None:
        if value is not None:
            self._dispatch_line(f"/mode {value}")

    def _on_model_picked(self, value: str | None) -> None:
        if value is not None:
            self._dispatch_line(f"/model {value}")

    def _open_model_picker(self, extra: list[tuple[str, str]]) -> None:
        choices = model_choices(self.repl.cfg, extra=extra)
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
