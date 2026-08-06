"""Live MCP connection test (MCP-01, D-19/D-20).

This is the MCP twin of `connection_test.py`: same worker-thread + hard-timeout pattern, budget
raised from 15s to 30s because a first-run stdio server may `npx`-download its package before it
can answer. It starts the server on the *live* `MCPManager` passed in, so a passing test leaves
the server already mounted — there is nothing further to adopt (D-13). If the caller abandons the
flow (cancels the add, or the "Save anyway" path is not taken after a failure the caller decides
not to keep), the caller must call `manager.stop_server(name)` itself; otherwise a cancelled add
leaves an orphaned server running for the rest of the session.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, LoadingIndicator, Static


@dataclass(frozen=True)
class MCPTestOutcome:
    """Result of one MCP connection test. `override` is D-13's explicit 'Save anyway'."""

    ok: bool
    tools: tuple[tuple[str, str], ...] = ()  # (tool name, description) — D-19
    error: str | None = None
    override: bool = False


class MCPTestModal(ModalScreen[MCPTestOutcome]):
    """Start `cfg` for real, enumerate its tools, and show them before anything is saved."""

    #: Hard cap (D-20). 30s, not ConnectionTestModal's 15s — a first-run stdio server may
    #: `npx`-download its package, and MCPManager.start() already budgets 30s for that. A 15s
    #: timeout would fail honest first runs and teach the user to distrust the test.
    TIMEOUT_S: float = 30.0

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        manager,  # MCPManager (live; not typed to keep mcp lazy)
        name: str,
        cfg,  # MCPServerConfig
        overrides: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._manager = manager
        self._name = name
        self._cfg = cfg
        self._overrides = overrides
        self._error: str | None = None
        self._tools: tuple[tuple[str, str], ...] = ()

    def compose(self) -> ComposeResult:
        with Container(id="mcp-test-dialog"):
            yield Label(f"Connecting to {self._name} ({self._cfg.transport})…")
            yield LoadingIndicator(id="mcp-test-spinner")
            yield Static("Starting the server and listing its tools…", id="mcp-test-status")
            with VerticalScroll(id="mcp-test-tools-scroll"):
                yield Static("", id="mcp-test-tools", markup=False)
            with Horizontal(id="mcp-test-buttons"):
                yield Button("Continue", id="mcp-test-continue", variant="primary")
                yield Button("Save anyway", id="mcp-save-anyway", variant="warning")
                yield Button("Cancel", id="mcp-test-cancel")

    def on_mount(self) -> None:
        self.query_one("#mcp-test-buttons").display = False
        self._run_test()

    # ---- worker (off the UI thread) ------------------------------------- #

    @work(thread=True, exclusive=True)
    def _run_test(self) -> None:
        holder: dict[str, object] = {}
        done = threading.Event()

        def _call() -> None:
            try:
                holder["tools"] = self._manager.start_server(
                    self._name, self._cfg, timeout=self.TIMEOUT_S, overrides=self._overrides
                )
            except BaseException as exc:  # noqa: BLE001 - surfaced verbatim (D-13 precedent)
                holder["error"] = str(exc) or exc.__class__.__name__
            finally:
                done.set()

        threading.Thread(target=_call, daemon=True).start()
        if not done.wait(timeout=self.TIMEOUT_S):
            self.app.call_from_thread(
                self._timeout, f"Timed out after {self.TIMEOUT_S:.0f}s — no response."
            )
            return
        error = holder.get("error")
        tools = holder.get("tools")
        self.app.call_from_thread(self._finish, tools, str(error) if error else None)

    # ---- main thread ---------------------------------------------------- #

    def _timeout(self, message: str) -> None:
        # A timeout resolves immediately (no cancel button for the in-flight connect, so there is
        # nothing for the user to act on) — mirrors ConnectionTestModal._timeout.
        self._error = message
        self.dismiss(MCPTestOutcome(ok=False, error=message, override=False))

    def _finish(self, tools: list | None, error: str | None) -> None:
        from agent86.secrets import redact

        self.query_one("#mcp-test-spinner").display = False
        buttons = self.query_one("#mcp-test-buttons")
        if error:
            self._error = error
            self.query_one("#mcp-test-status", Static).update(f"Test failed:\n{redact(error)}")
            self.query_one("#mcp-test-continue").display = False
            buttons.display = True
            self.query_one("#mcp-save-anyway", Button).focus()
            return
        pairs = tuple((t.name, t.description) for t in (tools or []))
        self._tools = pairs
        count = len(pairs)
        headline = (
            "Connected. No tools exposed."
            if count == 0
            else f"Connected. {count} tool{'s' if count != 1 else ''}:"
        )
        self.query_one("#mcp-test-status", Static).update(headline)
        tool_lines = "\n".join(f"{name}  —  {desc}" for name, desc in pairs)
        self.query_one("#mcp-test-tools", Static).update(
            redact(f"{headline}\n{tool_lines}" if tool_lines else headline)
        )
        self.query_one("#mcp-save-anyway").display = False
        self.query_one("#mcp-test-cancel").display = False
        buttons.display = True
        self.query_one("#mcp-test-continue", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "mcp-test-continue":
            self.dismiss(MCPTestOutcome(ok=True, tools=self._tools))
            return
        override = event.button.id == "mcp-save-anyway"
        self.dismiss(MCPTestOutcome(ok=False, error=self._error, override=override))

    def action_cancel(self) -> None:  # Escape -> explicit outcome, never hangs
        self.dismiss(MCPTestOutcome(ok=False, error=self._error, override=False))


__all__ = ["MCPTestOutcome", "MCPTestModal"]
