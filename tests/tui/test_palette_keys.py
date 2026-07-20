"""Wave-0 spike (Plan 02-02): resolves RESEARCH Open Question 1 / Pitfall 2 EMPIRICALLY.

Question: does a permanent App-level `Binding("enter", ..., priority=True)` whose action is a
no-op when a palette-open guard is False still let `Input.Submitted` fire for plain-text turn
submission (no leading `/`)? This is test-only — it does not touch `app.py`.

EMPIRICAL RESULT (see `test_priority_enter_binding_falls_through_when_palette_closed` below):
NO — a permanent priority `enter` binding fully consumes the key event once matched, even when
its action body is a no-op. `Input.Submitted` never fires. This rules out "Approach A" (a
permanent priority `enter` binding with an internal no-op guard).

DECISION FOR PLAN 04: **Approach B** — do not register a permanent priority `enter` Binding on
`Agent86App`. Instead, dynamically add/remove the `enter` binding (via `App.bind` /
`refresh_bindings`, or simplest: only add it to `BINDINGS`-equivalent runtime state while the
palette `OptionList` is visible, and remove/no-op it once the palette closes) so that whenever the
palette is closed, `enter` is not an App-level priority binding at all and `Input`'s own
Enter-submits behavior runs unimpeded. `test_input_submits_without_a_priority_enter_binding`
below proves the fallback path works when no priority `enter` binding is registered.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input


class _PrioritySpikeApp(App):
    """Minimal standalone App: a permanent priority `enter` binding that no-ops while
    `palette_open` is False, plus a single `#prompt` Input — mirrors `Agent86App`'s prompt wiring
    closely enough to answer the key-routing question without depending on the full
    harness/turn-bridge stack.
    """

    BINDINGS = [Binding("enter", "palette_select", show=False, priority=True)]

    def __init__(self) -> None:
        super().__init__()
        self.palette_open = False
        self.submitted: list[str] = []

    def compose(self) -> ComposeResult:
        yield Input(id="prompt", placeholder="agent86> ")

    def action_palette_select(self) -> None:
        if not self.palette_open:
            return  # no-op when palette closed — the case under test

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.submitted.append(event.value)


class _NoPriorityBindingApp(App):
    """Same shell as `_PrioritySpikeApp`, but with NO App-level `enter` binding at all — the
    Approach B fallback shape (palette-open state tracked separately; `enter` only ever becomes
    an App-level binding, if at all, while the palette is actually visible).
    """

    def __init__(self) -> None:
        super().__init__()
        self.submitted: list[str] = []

    def compose(self) -> ComposeResult:
        yield Input(id="prompt", placeholder="agent86> ")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.submitted.append(event.value)


async def test_priority_enter_binding_falls_through_when_palette_closed(tmp_path):
    """RESULT: Approach A REJECTED.

    A permanent App-level `Binding("enter", "palette_select", priority=True)` whose action body
    no-ops when `palette_open` is False does NOT let `Input.Submitted` fire — Textual's priority
    binding fully consumes the `enter` key event once matched, regardless of what the bound
    action does. `on_input_submitted` never runs; `app.submitted` stays empty.
    """
    app = _PrioritySpikeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "hello world"
        assert app.palette_open is False

        await pilot.press("enter")
        await pilot.pause()

        # Empirically: the priority binding consumes the event; Input.Submitted does not fire.
        assert app.submitted == []


async def test_input_submits_without_a_priority_enter_binding(tmp_path):
    """RESULT: Approach B CONFIRMED as the required fallback.

    With no App-level `enter` binding registered at all, `Input`'s native Enter-submits behavior
    fires `Input.Submitted` normally — proving the dynamic/flag-based approach (only bind `enter`
    at the App level while the palette is actually open; leave it unbound otherwise) preserves
    plain-text turn submission (D-11) once the palette feature is built in Plan 04.
    """
    app = _NoPriorityBindingApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "hello world"

        await pilot.press("enter")
        await pilot.pause()

        assert app.submitted == ["hello world"]


async def test_up_down_are_free_keys_on_input(tmp_path):
    """`Input` has no native up/down binding, so priority `up`/`down` bindings for the palette
    (added in Plan 04) will not conflict with or be shadowed by anything `Input` itself does.
    """
    app = _PrioritySpikeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.focus()
        prompt.value = "hello"

        await pilot.press("up")
        await pilot.press("down")
        await pilot.pause()

        # Neither key submitted the input or raised.
        assert app.submitted == []
        assert prompt.value == "hello"
