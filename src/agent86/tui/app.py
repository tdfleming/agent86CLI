"""The full-screen `Agent86App(App)` — the TUI shell (TUI-01, TUI-02, TUI-05).

Composes a scrollable transcript, a prompt input, and a live status footer; runs turns on a
Textual thread worker (the harness's `run_turn` generator stays synchronous, per CONTEXT.md
lock), streams deltas into the transcript, keeps the footer live during processing, and pops a
modal to resolve tool-approval requests. Textual is only ever imported by this module and by
whatever calls `run_tui` — never at `cli.py` module-import time (RESEARCH Pitfall 1).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from rich.markup import MarkupError, escape
from rich.text import Text
from textual import work
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

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
    TurnNotice,
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
from agent86.tui.screens.model_picker import (
    ModelPickerModal,
    catalog_has_ref,
    model_choices,
    prefix_catalog_refs,
)
from agent86.tui.screens.provider_manager import (
    CatalogPickerModal,
    ProviderManagerModal,
    ProviderRow,
    provider_rows,
)
from agent86.tui.screens.save_diff import SaveDiffModal
from agent86.tui.turn_bridge import run_turn_worker
from agent86.tui.widgets.status_footer import StatusFooter
from agent86.tui.widgets.transcript import (
    DARK_CODE_THEME,
    LIGHT_CODE_THEME,
    RawEntry,
    ReplyEntry,
    TranscriptEntry,
    UserEntry,
    looks_like_markdown,
)

if TYPE_CHECKING:  # `ui.repl` must stay importable without textual — type-only.
    from agent86.ui.repl import _Repl

__all__ = ["Agent86App", "run_tui"]

#: Provider names `cognitive.base._build_provider` resolves without a [providers.X] config block.
#: Used ONLY as a failure-shape heuristic (see _is_bare_ref_candidate). Under-inclusion is safe —
#: a future built-in missing from this set costs one extra catalog lookup whose miss re-emits the
#: same strict error, never a different outcome. Over-inclusion would be the harmful direction
#: (it would wrongly suppress the catalog branch), so keep this an exact mirror of that chain.
_BUILTIN_PROVIDERS = frozenset({"anthropic", "openai", "openai-compatible", "ollama", "llamacpp"})

#: Leads the first chunk of each response written to the transcript (harness-owned markup).
_AGENT_LABEL = "[bold cyan]agent86[/bold cyan] "

#: Hard cap on how much text the live `#stream` widget may hold before a chunk is flushed to
#: the transcript even without a paragraph break. Purely a bound; paragraph breaks do the work.
_STREAM_TAIL_LIMIT = 2000


class Agent86App(App):
    """The default interactive UI: transcript + prompt + live status footer."""

    BINDINGS = [
        Binding("shift+tab", "cycle_mode", "cycle approval mode", priority=True),
        Binding("up", "palette_up", show=False, priority=True),
        Binding("down", "palette_down", show=False, priority=True),
        Binding("escape", "palette_dismiss", show=False, priority=True),
        # Overrides Textual's own `ctrl+c -> help_quit` (and `Input`'s ctrl+c copy binding,
        # which priority=True beats): first press cancels a running turn, second press quits.
        Binding("ctrl+c", "interrupt", show=False, priority=True),
    ]

    CSS = """
    #transcript {
        height: 1fr;
    }
    #stream {
        height: auto;
        /* `height: auto` alone let a long answer grow without bound and push the prompt —
           and the status footer — clean off the screen. The widget only ever holds the tail
           (see _drain_stream_paragraphs); this is the belt-and-braces cap for a tail that is
           still tall on a short terminal. */
        max-height: 40%;
        overflow-y: auto;
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

    def __init__(self, repl: _Repl) -> None:
        super().__init__()
        self.repl = repl
        # v0.9: render finished assistant replies as Markdown. A plain attribute, not a
        # reactive — the wiring pass binds it to config; `config.py` has no `[ui] markdown`
        # key yet, and this module must not grow one (read-only from here).
        _ui = getattr(getattr(repl, "cfg", None), "ui", None)
        self.markdown: bool = bool(getattr(_ui, "markdown", True))
        # The MODEL of the scrollback, beside the RichLog that renders it. An entry can change
        # how it renders after it was written (a reply becoming Markdown, a tool block
        # expanding); when one does, `_rerender` replays the whole list into the log.
        self._entries: list[TranscriptEntry] = []
        self._reply: ReplyEntry | None = None
        self._stream_buf = ""
        # Has this turn's response already been labelled `agent86` in the transcript? The
        # label leads the FIRST chunk only, since a long response is flushed in pieces.
        self._stream_labelled = False
        # Turn/cancellation state. `_shutdown_event` is shared with the turn worker
        # (turn_bridge): once set, a worker parked on an approval stops waiting and denies, so
        # quitting can never hang on a modal nobody is left to answer.
        # NB: do NOT name this `_closing` — `textual.message_pump.MessagePump._closing` is an
        # internal bool, and shadowing it with a (truthy) Event wedges app startup.
        self._turn_running = False
        self._cancel_requested = False
        self._shutdown_event = threading.Event()
        self._pending_approvals: list[tuple[threading.Event, dict]] = []
        # D-04: live model catalogs are cached for this app session only — one fetch per
        # provider per launch, lazily on first use. No on-disk cache, no TTL, no invalidation.
        # RESEARCH Open Question 3: this lives on the App, not on _Repl/Harness — the plain
        # loop never needs a catalog.
        self._catalog_cache: dict[str, list[tuple[str, str]]] = {}
        # /model bare-ref fallback. A LIST of (arg, strict_error, provider) triples, not a slot:
        #  - two /model dispatches inside one fetch window must each still get an answer;
        #  - the provider is captured PER ENTRY because an intervening successful /model switch can
        #    change the active provider between two queued dispatches — an entry must only ever be
        #    validated against the catalog of the provider that was active when it was dispatched.
        self._pending_model: list[tuple[str, Any, str]] = []
        # Providers with a model_fallback catalog fetch outstanding — one fetch per provider
        # per burst.
        self._model_fetch_inflight: set[str] = set()
        self._pending_row: ProviderRow | None = None  # ProviderRow being configured
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
        for note in startup_notes(self.repl):
            # Through `_write`, not `log.write`: a note has to be an ENTRY, or the first
            # re-render (a Markdown reply, an expanded tool block) would drop it.
            self._write(f"[dim]{escape(note)}[/dim]")
        self.query_one("#palette", OptionList).display = False
        self.query_one("#prompt", Input).focus()

    # ---- transcript writing ------------------------------------------------ #

    def _write(self, renderable: Any) -> None:
        """Write a HARNESS-OWNED renderable; intentional markup is preserved.

        Untrusted text must NEVER reach here unescaped — interpolate it through
        ``rich.markup.escape`` (or use :meth:`_write_text`). The ``MarkupError`` guard is a
        last-resort net for renderables built elsewhere (``commands.handle_command`` echoes the
        typed line back, for instance), so a stray ``[`` can never raise on the main thread and
        tear down the app.
        """
        self._append_entry(RawEntry(renderable))

    def _write_text(self, text: str) -> None:
        """Write untrusted text with markup interpretation fully disabled."""
        self._append_entry(RawEntry(Text(text)))

    def _append_entry(self, entry: TranscriptEntry, *, write: bool = True) -> None:
        """Add one entry to the scrollback model and (usually) render it straight away.

        ``write=False`` reserves the entry's PLACE without rendering it yet — a tool block is
        created when its call is announced but only has something worth showing once the
        result lands, and the alternative (write a stub, then re-render the whole log to
        replace it) would pay an O(entries) cost per tool call.
        """
        self._entries.append(entry)
        if write:
            self._render_entry(entry)

    def _render_entry(self, entry: TranscriptEntry) -> None:
        log = self.query_one("#transcript", RichLog)
        try:
            log.write(entry.render())
        except MarkupError:
            log.write(Text(str(entry)))

    def _rerender(self) -> None:
        """Replay every entry into the log — the price of an entry changing its rendering."""
        log = self.query_one("#transcript", RichLog)
        log.clear()
        for entry in self._entries:
            self._render_entry(entry)
        log.scroll_end(animate=False)

    def _code_theme(self) -> str:
        """The Pygments theme for fenced code, following the app's own light/dark theme."""
        theme = getattr(self, "current_theme", None)
        return DARK_CODE_THEME if getattr(theme, "dark", True) else LIGHT_CODE_THEME

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

    # ---- line dispatch ------------------------------------------------------- #

    def _dispatch_line(self, line: str) -> None:
        """Run one command/turn line through the existing execution path.

        Shared by typed Input submission and picker-chained selections (palette / /model /
        /mode) so both paths behave identically.
        """
        # The echoed line is USER text and stays plain: `UserEntry` renders through `Text`,
        # which is never markup-parsed, so `"see [/path]"` can neither raise MarkupError on
        # the main thread nor vanish into a style tag — and it is never Markdown-rendered.
        self._append_entry(UserEntry(line))

        # A bare needs_choice command (no argument) typed directly — not just palette-selected —
        # opens the same picker/chain as picking it from the palette (mirrors _select_palette).
        match = find_command_for_line(line)
        if match is not None:
            entry, arg = match
            if entry.needs_choice and not arg:
                self._run_or_chain(entry)
                return
            if entry.name == "/model" and arg:
                self._dispatch_model(arg)
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
            self._write(result.render)
        self.query_one("#status", StatusFooter).status = self.repl.status

    # ---- /model typed bare-ref catalog fallback ------------------------------ #

    def _is_bare_ref_candidate(self, arg: str, active: str) -> bool:
        """Is this failure PLAUSIBLY ModelRef.parse's first-colon split, and not something else?

        Only a plausible candidate may reach the catalog branch. A ref that names a real provider
        and merely failed to build (missing key, bad base_url, SDK error) must NOT trigger a
        catalog fetch of the *active* provider — that would put a real network call and a
        "fetching … catalog…" line in front of the correct strict error.
        """
        from agent86.types import ModelRef

        try:
            parsed = ModelRef.parse(arg)
        except ValueError:
            return True  # no colon at all (e.g. "gpt-4o") — a bare id is exactly this shape
        if parsed.provider == active:
            return False  # explicitly targets the active provider; the failure is build/auth
        return (
            parsed.provider not in self.repl.cfg.providers
            and parsed.provider not in _BUILTIN_PROVIDERS
        )

    def _dispatch_model(self, arg: str) -> None:
        """Run `/model <arg>`; if the strict path fails, retry as `<active-provider>:<arg>` ONLY
        when the failure looks like a first-colon split AND the active provider's catalog vouches
        for `arg` verbatim (locked user decision). TUI-only — `ui/repl.py` and `run --json` keep
        strict parsing."""
        before = self.repl.harness.provider
        result = handle_command(self.repl, f"/model {arg}")
        # set_model() replaces harness.provider on success and leaves it untouched on failure
        # (loop.py:130-143), so identity is an exact success signal — no dispatch duplication.
        if self.repl.harness.provider is not before:
            if result.render is not None:
                self._write(result.render)
            self.query_one("#status", StatusFooter).status = self.repl.status
            return
        provider = before.name
        if not self._is_bare_ref_candidate(arg, provider):
            if result.render is not None:
                self._write(result.render)        # strict error, immediately, no fetch
            return
        entries = self._catalog_cache.get(provider)
        if entries is not None:
            self._finish_model_fallback(arg, result.render, provider, entries)
            return
        # Cold cache: never block the UI. Queue this dispatch WITH the provider that was active
        # for it, then ensure exactly one fetch is outstanding for that provider.
        self._pending_model.append((arg, result.render, provider))
        self._ensure_catalog_fetch(provider)

    def _ensure_catalog_fetch(self, provider: str) -> None:
        """Start a model_fallback catalog fetch for `provider` unless one is already outstanding.

        Gated on _model_fetch_inflight, NOT on queue length: a queue that is non-empty because of
        ANOTHER provider's pending entry must still start this provider's own fetch, or that entry
        would silently piggyback on an unrelated arrival and never be answered.
        """
        if provider in self._model_fetch_inflight:
            return
        self._model_fetch_inflight.add(provider)
        self._request_catalog(provider, self._provider_key(provider), "model_fallback")

    def _finish_model_fallback(
        self, arg: str, strict_error: Any, provider: str, entries: list[tuple[str, str]]
    ) -> None:
        if not catalog_has_ref(arg, entries):
            # Catalog miss (typo, or a ref belonging to another provider): the strict error is
            # the RIGHT answer — surfacing it unchanged is the point of the locked decision.
            if strict_error is not None:
                self._write(strict_error)
            return
        # Reuse 260813-adr's exact-prefix double-prefix guard so the typed and picker paths of
        # /model can never drift.
        full = prefix_catalog_refs(provider, [(arg, arg)])[0][0]
        if full == arg:                       # defensive: already prefixed, retry would re-fail
            if strict_error is not None:
                self._write(strict_error)
            return
        self._write(f"[dim]resolved to {escape(full)}[/dim]")
        retry = handle_command(self.repl, f"/model {full}")
        if retry.render is not None:
            self._write(retry.render)
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
        if palette.display:
            palette.display = False
            return
        # A modal (approval / picker / manager) owns Escape for as long as it is on top —
        # same SkipAction fall-through as action_palette_up/_down.
        if len(self.screen_stack) > 1:
            raise SkipAction()
        if self._turn_running and not self._cancel_requested:
            self._request_cancel()
            return
        raise SkipAction()

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
        if name is None:  # an Option built without an id is not a command row
            return
        entry = find_command(name)
        if entry is not None:
            self._run_or_chain(entry)

    def _run_or_chain(self, entry) -> None:  # noqa: ANN001
        if entry.needs_choice == "mode":
            self.push_screen(
                ModePickerModal(self.repl.harness.gate.mode.value), self._on_mode_picked
            )
        elif entry.needs_choice == "model":
            # config_name, not name: `[providers.<section>]` is what the catalog fetch and
            # the key lookup below are keyed on, and every OpenAI-compatible gateway's
            # adapter calls itself "openai".
            active = self.repl.harness.provider.config_name
            cached = self._catalog_cache.get(active)
            if cached is None:
                # D-04: one lazy fetch per provider per session; the picker opens from
                # on_catalog_ready(purpose="model_picker").
                self._request_catalog(active, self._provider_key(active), "model_picker")
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

    def _provider_key(self, provider: str) -> str | None:
        from agent86.config import ProviderConfig
        from agent86.secrets import resolve_api_key

        pconf = self.repl.cfg.providers.get(provider, ProviderConfig())
        return resolve_api_key(provider, pconf.api_key_env)

    def _open_model_picker(self, extra: list[tuple[str, str]]) -> None:
        # The catalog yields BARE model ids (catalog.py's documented contract); only a full
        # `provider:model` ref survives ModelRef.parse. Prefix BEFORE model_choices so its
        # role-slot dedupe compares full refs against full refs.
        provider = self.repl.harness.provider.config_name
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
        if self._pending_row is None:
            # No provider row is in flight — the chain was reset (or torn down) while the key
            # modal was open. Dropping the key is the only safe answer: there is no provider to
            # test it against, and keeping it would let it leak into an unrelated later save.
            self._write("[dim]no provider selected; the key was discarded[/dim]")
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
            self._write(f"[red]error:[/red] {escape(str(exc))}")
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

    def _on_test_done(self, outcome: TestOutcome | None) -> None:
        if outcome is None:
            # Textual hands the callback None when the modal is dismissed without a result —
            # e.g. the app is shutting down mid-test. Treat it exactly as a cancel: the typed
            # key stays in memory only and nothing is written.
            self._pending_key = None
            self._write("[dim]connection test cancelled[/dim]")
            return
        if not outcome.ok and not outcome.override:
            self._write(f"[red]connection test failed:[/red] {escape(str(outcome.error))}")
            return
        if not outcome.ok:
            self._write(f"[yellow]saving anyway despite:[/yellow] {escape(str(outcome.error))}")
        # D-14: the key becomes persistent only now.
        if self._pending_key and self._pending_row is not None:
            from agent86.secrets import SecretStoreError, store_api_key

            try:
                store_api_key(self._pending_row.name, self._pending_key)
                self._write(
                    f"[dim]key stored in the OS keyring for "
                    f"{escape(self._pending_row.name)}[/dim]"
                )
            except SecretStoreError as exc:
                self._write(f"[red]could not store the key:[/red] {escape(str(exc))}")
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
        if edit is None:
            self._write("[dim]not saved — the model switch applies to this session only[/dim]")
            return
        from agent86.config_writer import ConfigWriteError, apply_edit

        try:
            self.repl.cfg = apply_edit(edit)
        except ConfigWriteError as exc:
            self._write(f"[red]could not save:[/red] {escape(str(exc))}")
            return
        self._write(f"[dim]saved to {escape(str(edit.path))}[/dim]")

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
            self._write("[dim]mcp: cancelled[/dim]")
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

    def _on_mcp_test_done(self, outcome: MCPTestOutcome | None) -> None:
        draft = self._mcp_draft
        if outcome is None:
            # Dismissed without a result (shutdown / cancel): abandon the add, and drop any
            # secrets typed this pass rather than persisting them untested.
            self._mcp_draft = None
            self._mcp_overrides = {}
            self._write("[dim]mcp: cancelled[/dim]")
            return
        if draft is None:
            return
        if outcome.ok:
            self._mcp_started = draft.name       # the test left it mounted (D-13)
            self._write(
                f"[dim]mcp: {escape(draft.name)} connected, {len(outcome.tools)} tools[/dim]"
            )
        elif outcome.override:
            self._write(f"[yellow]saving anyway despite:[/yellow] {escape(str(outcome.error))}")
        else:
            self._write(
                f"[red]mcp connection test failed:[/red] {escape(str(outcome.error))}"
            )
            self._mcp_draft = None
            return
        # D-14 precedent: a typed secret becomes persistent only once the test has passed
        # (or the user explicitly overrode). Keyed by ${VAR} NAME, not provider name.
        if self._mcp_overrides:
            from agent86.secrets import SecretStoreError, store_api_key

            for var_name, value in self._mcp_overrides.items():
                safe_var = escape(var_name)
                try:
                    store_api_key(var_name, value)
                    self._write(f"[dim]stored ${{{safe_var}}} in the OS keyring[/dim]")
                except SecretStoreError as exc:
                    self._write(
                        f"[red]could not store ${{{safe_var}}}:[/red] {escape(str(exc))}"
                    )
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
        draft, self._mcp_draft = self._mcp_draft, None
        started, self._mcp_started = self._mcp_started, None
        if edit is None:
            self._write("[dim]not saved[/dim]")
            # D-13: a cancelled add must not leave the just-started server running all session.
            if started and self.repl.harness.mcp is not None:
                self.repl.harness.mcp.stop_server(started)
            return
        from agent86.config_writer import ConfigWriteError, apply_edit

        try:
            self.repl.cfg = apply_edit(edit)
        except ConfigWriteError as exc:
            self._write(f"[red]could not save:[/red] {escape(str(exc))}")
            return
        self._write(f"[dim]saved to {escape(str(edit.path))}[/dim]")
        if draft is None:
            return
        if draft.original_name:
            self.repl.harness.remove_mcp_server(draft.original_name)
        if started != draft.name:
            # D-16: the config write succeeded; the live mount did not. Report both, never
            # roll back.
            self._write(
                f"[yellow]saved, but {escape(draft.name)} is not running:[/yellow] "
                "it will be available next launch"
            )
            return
        mounted, collisions = self.repl.harness.add_mcp_server(draft.name, draft.cfg)
        line = f"[dim]mcp: {escape(draft.name)} mounted, {len(mounted)} tools live[/dim]"
        if collisions:
            joined = escape(", ".join(collisions))
            line += f" [yellow](name collisions, not mounted: {joined})[/yellow]"
        self._write(line)

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
            self._mcp_draft = MCPServerDraft(
                name=name, cfg=srv.model_copy(update={"enabled": True})
            )
            self._prompt_next_var()
            return
        self._mcp_action = kind
        self._mcp_unmount = name
        # `object` (not the inferred `_Delete`): config_writer's change list is heterogeneous —
        # the DELETE sentinel and plain scalars share one list shape (see plan_edit's
        # `list[tuple[list[str], Any]]`), and `_persist_changes` already uses this annotation.
        changes: list[tuple[list[str], object]]
        if kind == "remove":
            changes = [(["mcp", "servers", name], DELETE)]
        else:
            changes = [(["mcp", "servers", name, "enabled"], False)]
        self.push_screen(SaveDiffModal(changes), self._on_mcp_unmount_confirmed)

    def _on_mcp_unmount_confirmed(self, edit) -> None:  # noqa: ANN001 - ConfigEdit | None
        name, self._mcp_unmount = self._mcp_unmount, None
        if edit is None or name is None:
            self._write("[dim]not saved[/dim]")
            return
        from agent86.config_writer import ConfigWriteError, apply_edit

        try:
            self.repl.cfg = apply_edit(edit)
        except ConfigWriteError as exc:
            self._write(f"[red]could not save:[/red] {escape(str(exc))}")
            return
        self._write(f"[dim]saved to {escape(str(edit.path))}[/dim]")
        # D-14: unmount immediately — leaving a removed server's tools callable would let the
        # model invoke something the user just deleted.
        self.repl.harness.remove_mcp_server(name)
        verb = "removed" if self._mcp_action == "remove" else "disabled"
        self._write(
            f"[dim]mcp: {escape(name)} {verb}; its tools are no longer available[/dim]"
        )

    # ---- turn worker ------------------------------------------------------ #

    def _start_turn(self, line: str) -> None:
        self.repl.status.working = True
        self.repl.status.phase = "thinking"
        self.query_one("#status", StatusFooter).status = self.repl.status
        self.query_one("#prompt", Input).disabled = True
        self._stream_buf = ""
        self._stream_labelled = False
        self._reply = None
        self._turn_running = True
        self._cancel_requested = False
        self._run_turn(line)

    @work(thread=True, exclusive=True)
    def _run_turn(self, line: str) -> None:
        run_turn_worker(
            self.repl.harness, line, self.repl.state, self.post_message, self._shutdown_event
        )

    # ---- cancellation / shutdown -------------------------------------------- #

    def _request_cancel(self) -> None:
        """Ask the harness to stop the in-flight turn at its next safe point."""
        self._cancel_requested = True
        cancel = getattr(self.repl.harness, "cancel", None)
        if cancel is not None:
            cancel()
        self._write("[dim]cancelling…[/dim]")
        self.repl.status.phase = "cancelling"
        self.query_one("#status", StatusFooter).status = self.repl.status

    def _shutdown_workers(self) -> None:
        """Release every worker thread before the app goes away.

        A thread blocked in `approval_cb` holds a `threading.Event` the app can no longer
        resolve once its screens are unmounting — which used to hang interpreter exit. Set the
        shared closing flag (the polled wait notices it), cancel the turn, and resolve any
        still-pending approval as DENIED: the safe answer when nobody is there to give one.
        """
        self._shutdown_event.set()
        cancel = getattr(self.repl.harness, "cancel", None)
        if cancel is not None:
            cancel()
        pending, self._pending_approvals = self._pending_approvals, []
        for event, box in pending:
            box["ok"] = False
            event.set()

    def action_interrupt(self) -> None:
        """Ctrl+C: cancel a running turn; quit if none is running (or on a second press)."""
        if self._turn_running and not self._cancel_requested:
            self._request_cancel()
            return
        self._shutdown_workers()
        self.exit()

    async def action_quit(self) -> None:
        self._shutdown_workers()
        await super().action_quit()

    def on_unmount(self) -> None:
        self._shutdown_workers()

    # ---- model catalog (session cache) -------------------------------------- #

    def _request_catalog(self, provider: str, api_key: str | None, purpose: str) -> None:
        """Serve the catalog from the session cache, or fetch it on a worker thread."""
        cached = self._catalog_cache.get(provider)
        if cached is not None:
            self.post_message(CatalogReady(provider, cached, None, purpose))
            return
        self._write(f"[dim]fetching {escape(provider)} model catalog…[/dim]")
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
            self._write(
                f"[yellow]catalog unavailable:[/yellow] {escape(str(message.error))} "
                "[dim](enter a model name directly)[/dim]"
            )
        if message.purpose == "model_picker":
            self._open_model_picker(message.entries)
            return
        if message.purpose == "model_fallback":
            self._model_fetch_inflight.discard(message.provider)
            # Resolve ONLY the entries dispatched under this provider (invariant 3); entries queued
            # under a different provider — an intervening successful /model switch can change the
            # active provider mid-flight — are re-queued untouched and answered by their own
            # arrival. A failed/empty fetch leaves entries == [] -> catalog_has_ref False -> the
            # strict error is written. Never a silent retry, never a silent drop.
            pending, self._pending_model = self._pending_model, []
            stranded: list[tuple[str, Any, str]] = []
            for arg, strict_error, provider in pending:
                if provider == message.provider:
                    self._finish_model_fallback(arg, strict_error, provider, message.entries)
                else:
                    stranded.append((arg, strict_error, provider))
            self._pending_model.extend(stranded)
            # Liveness safety net (invariant 1): normally each stranded provider's fetch is still
            # in flight from its own dispatch, so this is a no-op. If one somehow is not, restart
            # it rather than leaving an entry with no outcome forever.
            for _arg, _err, provider in stranded:
                self._ensure_catalog_fetch(provider)
            return
        self.push_screen(
            CatalogPickerModal(message.provider, message.entries), self._on_catalog_picked
        )

    def on_turn_delta(self, message: TurnDelta) -> None:
        self._stream_buf += message.text
        # The reply entry accumulates the EXACT stream (not the chunking `#stream` happens to
        # use), so the finished reply can be re-rendered as one Markdown document.
        self._reply_entry().text += message.text
        self._drain_stream_paragraphs()
        # Model text is untrusted: a `Text` render means `[/path/to/file]` can neither raise
        # MarkupError nor silently vanish into a style tag.
        self.query_one("#stream", Static).update(Text(self._stream_buf))
        self.repl.status.working = True
        self.repl.status.phase = "thinking"
        self.query_one("#status", StatusFooter).status = self.repl.status
        self.query_one("#transcript", RichLog).scroll_end(animate=False)

    def on_tool_announce(self, message: ToolAnnounce) -> None:
        """A tool call started: the reply so far is final, so flush it before the line lands."""
        self._finish_reply()
        # `[tool] name({...})` is literal text, not markup — and the argument preview is
        # model-authored. Rendering it as markup swallowed the `[tool]` label outright.
        self._write_text(message.text.strip())
        self.repl.status.working = True
        self.repl.status.phase = message.label
        self.query_one("#status", StatusFooter).status = self.repl.status

    def on_turn_notice(self, message: TurnNotice) -> None:
        """A `[compacted …]` / `[continuing …]` notice: the harness, not the model.

        Ends the reply in progress so it lands in the transcript in stream order, and renders
        escaped because the notice quotes harness-formatted counts and model names.
        """
        self._finish_reply()
        self._write(f"[dim]{escape(message.text)}[/dim]")
        self.query_one("#transcript", RichLog).scroll_end(animate=False)

    def on_approval_request(self, message: ApprovalRequest) -> None:
        if self._shutdown_event.is_set():
            # Mid-shutdown: never push a modal onto a screen stack that is unmounting.
            message.box["ok"] = False
            message.event.set()
            return
        entry = (message.event, message.box)
        self._pending_approvals.append(entry)

        def _resolve(approved: bool | None) -> None:
            if entry in self._pending_approvals:
                self._pending_approvals.remove(entry)
            message.box["ok"] = bool(approved)
            message.event.set()

        self.push_screen(ApprovalModal(message.tool_name, message.preview), _resolve)

    def on_turn_done(self, message: TurnDone) -> None:
        self._finish_reply()
        self._end_turn()

    def on_turn_error(self, message: TurnError) -> None:
        self._finish_reply()
        self._write(f"[red]error:[/red] {escape(str(message.error))}")
        self._end_turn()

    def _end_turn(self) -> None:
        self._turn_running = False
        self._cancel_requested = False
        self.repl._refresh_status()
        # Written on the error path too: the loop publishes a fresh summary at the START of
        # every turn and closes it on every exit, so this is always THIS turn — and a turn
        # that failed halfway still spent tokens.
        summary = self.repl.turn_summary_line()
        if summary:
            self._write(f"[dim]{escape(summary)}[/dim]")
        self.query_one("#status", StatusFooter).status = self.repl.status
        self._reenable_input()

    def _drain_stream_paragraphs(self) -> None:
        """Move completed paragraphs out of `#stream` and into the scrollback.

        `#stream` is the live tail of the response; the transcript is the scrollback. Keeping
        the whole response in `#stream` made a long answer grow the widget until the prompt
        was off screen, and re-rendered the entire text on every delta. Flushing at paragraph
        boundaries bounds both.
        """
        head, sep, tail = self._stream_buf.rpartition("\n\n")
        if not sep:
            if len(self._stream_buf) <= _STREAM_TAIL_LIMIT:
                return
            # One runaway paragraph with no blank line: break on the last newline, or — if
            # there isn't one either — hard-split, so the tail always stays bounded.
            head, sep, tail = self._stream_buf.rpartition("\n")
            if not sep:
                head, tail = self._stream_buf, ""
        self._write_stream_chunk(head)
        self._stream_buf = tail

    def _write_stream_chunk(self, text: str) -> None:
        """Write one chunk of MODEL text to the transcript, labelled once per reply.

        This is the PROVISIONAL rendering: plain, escaped, append-only, so streaming stays
        cheap and a half-written fence or table never renders as garbage. `_finish_reply`
        replaces the lot with the Markdown document when the reply is complete.
        """
        body = text.rstrip("\n")
        if not body:
            return
        # The label is a harness-owned string (intentional markup) and only leads the first
        # chunk of a response; the body is model text and is always escaped.
        prefix = "" if self._stream_labelled else _AGENT_LABEL
        self._stream_labelled = True
        self._render_entry(RawEntry(f"{prefix}{escape(body)}"))

    def _flush_stream(self) -> None:
        if self._stream_buf:
            self._write_stream_chunk(self._stream_buf)
        self.query_one("#stream", Static).update("")
        self._stream_buf = ""

    def _reply_entry(self) -> ReplyEntry:
        """The reply being streamed, creating (and placing) it on the first delta."""
        if self._reply is None:
            self._reply = ReplyEntry(markdown=self.markdown, code_theme=self._code_theme())
            self._append_entry(self._reply, write=False)  # the stream chunks do the writing
        return self._reply

    def _finish_reply(self) -> None:
        """End the reply in progress: flush its tail, then Markdown-render it if it pays.

        Re-rendering replays every entry into the log, so it is skipped unless the reply
        actually contains Markdown structure — plain prose already looks the same, and a
        turn-per-turn full replay would be the one place this design could get slow.
        """
        self._flush_stream()
        entry, self._reply = self._reply, None
        self._stream_labelled = False
        if entry is None:
            return
        entry.final = True
        if not entry.text.strip():
            # Nothing was written for it either; drop it so a re-render can't resurrect a
            # bare `agent86` label with no answer under it.
            self._entries = [e for e in self._entries if e is not entry]
            return
        if entry.markdown and looks_like_markdown(entry.text):
            self._rerender()

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


def run_tui(repl: _Repl) -> None:
    """Run `Agent86App` against an ALREADY-BUILT `_Repl`.

    `run_repl` constructs the `_Repl` (and therefore the `Harness`) before choosing a loop, so
    building a second one here started every MCP server twice, opened the memory DB twice, and
    left the plain-loop fallback pointing at a different session than the TUI. The harness is
    built exactly once per process; this function only owns the Textual app.
    """
    Agent86App(repl).run()
