"""Headless widget-level test for StatusFooter (TUI-02: live status during a turn).

Proves the "dead" working branch of `format_status_line` is now live: assigning a working
`StatusState` (working=True, phase=...) to the footer flips the rendered text away from the
idle ctx%/tokens/cost form to the "model · phase…" form.
"""

from __future__ import annotations

from textual.app import App, ComposeResult

from agent86.tui.widgets.status_footer import StatusFooter
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
    async with app.run_test() as pilot:
        footer = app.query_one("#status", StatusFooter)
        footer.status = _state()
        await pilot.pause()
        text = _rendered(footer)
        assert "ctx" in text
        assert "qwen2.5:3b" in text


async def test_working_status_shows_phase_and_hides_ctx():
    app = _HostApp()
    async with app.run_test() as pilot:
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
    async with app.run_test() as pilot:
        footer = app.query_one("#status", StatusFooter)
        footer.status = _state(working=True, phase="running write_file")
        await pilot.pause()
        text = _rendered(footer)
        assert "running write_file…" in text
