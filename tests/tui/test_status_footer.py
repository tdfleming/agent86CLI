"""Headless widget-level tests for StatusFooter (TUI-02 live status, v0.8 width policy).

Two things are pinned here:

* the "dead" working branch of the status line is live — assigning a working `StatusState`
  flips the footer from the idle ctx/tokens/cost form to "model · phase…";
* the footer occupies exactly ONE row at 80, 100, 120 and 140 columns, shedding the key
  hint, then the token counts, then the ctx gauge — and never the model, cost, mode or
  the working indicator.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from agent86.tui.widgets.status_footer import StatusFooter, fit_status_line
from agent86.ui.status import StatusState


def _state(**over) -> StatusState:
    base = dict(
        model="qwen2.5:3b",
        used_tokens=1100,
        window=8192,
        output_tokens=320,
        cost_usd=0.0,
        sandbox="subprocess",
        approval="ask",
        model_ref="ollama:qwen2.5:3b",
    )
    base.update(over)
    return StatusState(**base)


class _HostApp(App):
    def compose(self) -> ComposeResult:
        yield StatusFooter(id="status")


def _rendered(footer: StatusFooter) -> str:
    return str(footer.render())


async def test_idle_status_renders_ctx_and_model():
    app = _HostApp()
    async with app.run_test(size=(140, 24)) as pilot:
        footer = app.query_one("#status", StatusFooter)
        footer.status = _state()
        await pilot.pause()
        text = _rendered(footer)
        assert "ctx" in text
        assert "qwen2.5:3b" in text


async def test_working_status_shows_phase_and_hides_ctx():
    app = _HostApp()
    async with app.run_test(size=(140, 24)) as pilot:
        footer = app.query_one("#status", StatusFooter)
        footer.status = _state()
        await pilot.pause()
        idle_text = _rendered(footer)

        footer.status = _state(working=True, phase="thinking")
        await pilot.pause()
        working_text = _rendered(footer)

        assert "thinking…" in working_text
        assert "ctx" not in working_text
        assert working_text != idle_text


async def test_working_status_shows_tool_phase():
    app = _HostApp()
    async with app.run_test(size=(140, 24)) as pilot:
        footer = app.query_one("#status", StatusFooter)
        footer.status = _state(working=True, phase="running write_file")
        await pilot.pause()
        text = _rendered(footer)
        assert "running write_file…" in text


# ---- width policy (v0.8) ------------------------------------------------ #


@pytest.mark.parametrize("width", [80, 100, 120, 140])
async def test_footer_is_one_row_at_every_common_width(width):
    """The measured failure: the idle line wrapped to two rows at 80 and 100 columns."""
    app = _HostApp()
    async with app.run_test(size=(width, 24)) as pilot:
        footer = app.query_one("#status", StatusFooter)
        # an unpriced model: the longest cost segment there is, i.e. the worst case
        footer.status = _state(
            model="llama-3.3-70b-versatile",
            model_ref="groq:llama-3.3-70b-versatile",
            cache_read_tokens=1900,
        )
        await pilot.pause()
        assert footer.size.height == 1
        assert len(_rendered(footer)) <= width


@pytest.mark.parametrize("width", [80, 100, 120, 140])
async def test_footer_never_sheds_model_cost_or_mode(width):
    app = _HostApp()
    async with app.run_test(size=(width, 24)) as pilot:
        footer = app.query_one("#status", StatusFooter)
        footer.status = _state()
        await pilot.pause()
        text = _rendered(footer)
        assert "qwen2.5:3b" in text  # what is running
        assert "$0.0000" in text  # what it is costing
        assert "mode: ask" in text  # whether it can act without asking


@pytest.mark.parametrize("width", [80, 100, 120, 140])
async def test_footer_keeps_the_working_indicator_at_every_width(width):
    app = _HostApp()
    async with app.run_test(size=(width, 24)) as pilot:
        footer = app.query_one("#status", StatusFooter)
        footer.status = _state(working=True, phase="running write_file")
        await pilot.pause()
        assert footer.size.height == 1
        assert "running write_file…" in _rendered(footer)


async def test_footer_refits_on_resize():
    """Widening the terminal brings shed segments back without touching `status`."""
    app = _HostApp()
    async with app.run_test(size=(80, 24)) as pilot:
        footer = app.query_one("#status", StatusFooter)
        footer.status = _state()
        await pilot.pause()
        narrow = _rendered(footer)

        await pilot.resize_terminal(140, 24)
        await pilot.pause()
        wide = _rendered(footer)

        assert len(narrow) < len(wide)
        assert "[Shift+Tab]" in wide
        assert footer.size.height == 1


# ---- the shedding order itself (pure) ----------------------------------- #


def test_shed_order_is_hint_then_tokens_then_ctx():
    state = _state()
    full = fit_status_line(state, 0)  # 0 = unlimited
    assert "[Shift+Tab]" in full and "tok " in full and "ctx " in full

    no_hint = fit_status_line(state, len(full) - 1)
    assert "[Shift+Tab]" not in no_hint and "tok " in no_hint and "ctx " in no_hint

    no_tokens = fit_status_line(state, len(no_hint) - 1)
    assert "tok " not in no_tokens and "ctx " in no_tokens

    no_ctx = fit_status_line(state, len(no_tokens) - 1)
    assert "ctx " not in no_ctx
    assert "qwen2.5:3b" in no_ctx and "$0.0000" in no_ctx and "mode: ask" in no_ctx


def test_fit_keeps_the_protected_segments_even_when_nothing_fits():
    """A terminal too narrow for the protected core still gets the protected core."""
    line = fit_status_line(_state(), 10)
    assert "qwen2.5:3b" in line and "mode: ask" in line
