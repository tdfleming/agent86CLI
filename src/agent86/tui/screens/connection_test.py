"""Live provider connection test (MODEL-01, D-11..D-14).

Sends a *real* ~1-token completion through the real `provider_for_ref` path, so a pass proves the
key, the base_url, the model name, and the actual completion code path together — not just that a
models endpoint answers.

Threading (RESEARCH Open Question 1, resolved): the blocking `complete()` runs on a Textual
thread worker, and inside that worker a second daemon thread is joined with a hard
`Event.wait(TIMEOUT_S)`. The alternative — plumbing a `timeout=` kwarg through
`ModelProvider.stream()`/`complete()` — would touch the cognitive tier, which this phase's
boundary excludes. The extra thread is a known minor inefficiency, not a correctness risk.

`provider_for_ref` is imported at module scope (not lazily inside the worker) so tests can
monkeypatch it directly on this module — see `tests/tui/test_connection_test.py`.

The key under test is passed in and never stored here (D-14); the caller writes it to the keyring
only once this modal reports ok (or the user chooses "Save anyway", D-13).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label, LoadingIndicator, Static

from agent86.cognitive.base import UNRESOLVED, provider_for_ref
from agent86.config import Config
from agent86.types import CompletionRequest, Message, ModelRef, Role


@dataclass(frozen=True)
class TestOutcome:
    """Result of one connection test. `override` is D-13's explicit 'Save anyway'."""

    ok: bool
    error: str | None = None
    override: bool = False


class ConnectionTestModal(ModalScreen[TestOutcome]):
    """Run a tiny live completion against `ref`, showing progress and the verbatim error."""

    #: Hard cap (D-12). Class attribute so tests can shrink it.
    TIMEOUT_S: float = 15.0

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, cfg: Config, ref: ModelRef, api_key: Any = UNRESOLVED) -> None:
        super().__init__()
        self._cfg = cfg
        self._ref = ref
        # `UNRESOLVED` (the default) means "resolve from env then keyring" — see
        # provider_for_ref. A concrete str is a key typed this pass that has not been stored
        # anywhere yet (D-14).
        self._api_key = api_key
        self._error: str | None = None

    def compose(self) -> ComposeResult:
        with Container(id="connection-test-dialog"):
            yield Label(f"Testing {self._ref.provider}:{self._ref.model}")
            yield LoadingIndicator(id="test-spinner")
            yield Static("Sending a 1-token probe…", id="test-status")
            with Horizontal(id="test-buttons"):
                yield Button("Save anyway", id="save-anyway", variant="warning")
                yield Button("Cancel", id="test-cancel")

    def on_mount(self) -> None:
        self.query_one("#test-buttons").display = False
        self._run_test()

    # ---- worker (off the UI thread) ------------------------------------- #

    @work(thread=True, exclusive=True)
    def _run_test(self) -> None:
        holder: dict[str, object] = {}
        done = threading.Event()

        def _call() -> None:
            try:
                provider = provider_for_ref(self._ref, self._cfg, api_key=self._api_key)
                holder["completion"] = provider.complete(
                    CompletionRequest(
                        model=self._ref.model,
                        messages=[Message(role=Role.USER, content="hi")],
                        max_tokens=1,
                    )
                )
            except BaseException as exc:  # noqa: BLE001 - surfaced verbatim per D-13
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
        if error:
            self.app.call_from_thread(self._finish, False, str(error))
        else:
            self.app.call_from_thread(self._finish, True, None)

    # ---- main thread ---------------------------------------------------- #

    def _timeout(self, message: str) -> None:
        # A timeout resolves immediately (D-12: no cancel button for the in-flight request, so
        # there is nothing for the user to act on) rather than waiting on Save-anyway.
        self._error = message
        self.dismiss(TestOutcome(ok=False, error=message, override=False))

    def _finish(self, ok: bool, error: str | None) -> None:
        self.query_one("#test-spinner").display = False
        if ok:
            self.query_one("#test-status", Static).update("Connection ok.")
            self.dismiss(TestOutcome(ok=True))
            return
        self._error = error
        self.query_one("#test-status", Static).update(f"Test failed:\n{error}")
        self.query_one("#test-buttons").display = True
        self.query_one("#save-anyway", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        override = event.button.id == "save-anyway"
        self.dismiss(TestOutcome(ok=False, error=self._error, override=override))

    def action_cancel(self) -> None:  # Escape -> explicit outcome, never hangs
        self.dismiss(TestOutcome(ok=False, error=self._error or "cancelled", override=False))


__all__ = ["TestOutcome", "ConnectionTestModal"]
