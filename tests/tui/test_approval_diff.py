"""v0.9 — the approval modal renders the *detail*, not just the argument JSON.

The gate hands the modal an ``ApprovalPreview`` (a ``str`` carrying ``detail``/``lexer``);
these tests pin that the diff actually reaches the screen, that a plain ``str`` preview from
an older caller still renders, and that y/n/escape all resolve the modal explicitly — a modal
that cannot be dismissed leaves the worker thread blocked forever.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from agent86.guardrails.policy import ApprovalPreview
from agent86.tui.screens.approval import ApprovalModal

DIFF = "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n alpha\n-beta\n+BETA"


class _ModalHost(App):
    def __init__(self, screen) -> None:
        super().__init__()
        self._screen = screen
        self.result: object = "__unset__"

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(self._screen, self._store)

    def _store(self, value) -> None:
        self.result = value


def _widget_text(widget) -> str:
    """The text a widget actually paints — through the real render pipeline, styles dropped."""
    from textual.geometry import Region

    region = Region(0, 0, widget.size.width, widget.size.height)
    return "\n".join(strip.text for strip in widget.render_lines(region))


def _detail_text(host) -> str:
    """The painted text of the highlighted detail panel."""
    return _widget_text(host.screen.query_one("#approval-detail", Static))


async def test_modal_renders_a_diff_with_plus_and_minus_lines():
    preview = ApprovalPreview('{"path": "a.py"}', detail=DIFF, lexer="diff", tool="edit_file")
    host = _ModalHost(ApprovalModal("edit_file", preview))
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        text = _detail_text(host)
        assert "-beta" in text and "+BETA" in text
        assert "--- a/a.py" in text
        # The one-line summary is still there, above the panel.
        summary = host.screen.query_one("#approval-preview", Static)
        assert '{"path": "a.py"}' in _widget_text(summary)


async def test_modal_shows_the_ambiguous_edit_hint():
    detail = "a.py: old_string is ambiguous — 3 matches, and replace_all is off."
    preview = ApprovalPreview('{"path": "a.py"}', detail=detail, lexer="diff")
    host = _ModalHost(ApprovalModal("edit_file", preview))
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert "3 matches" in _detail_text(host)


async def test_modal_highlights_a_command_with_its_own_lexer():
    preview = ApprovalPreview('{"command": "..."}', detail="rm -rf build", lexer="bash")
    host = _ModalHost(ApprovalModal("run_command", preview))
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert "rm -rf build" in _detail_text(host)


async def test_markup_in_the_detail_is_not_interpreted():
    """A diff full of `[` must render, not raise MarkupError on the main thread."""
    detail = "--- a/x\n+++ b/x\n-cfg[red] = 1\n+cfg[/blue] = 2"
    host = _ModalHost(ApprovalModal("edit_file", ApprovalPreview("{}", detail, "diff")))
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        text = _detail_text(host)
        assert "cfg[red] = 1" in text and "cfg[/blue] = 2" in text


async def test_plain_string_preview_still_renders_without_a_detail_panel():
    host = _ModalHost(ApprovalModal("write_file", '{"path": "a"}'))
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert not host.screen.query("#approval-detail")
        summary = host.screen.query_one("#approval-preview", Static)
        assert '{"path": "a"}' in _widget_text(summary)


@pytest.mark.parametrize(
    ("key", "expected"),
    [("y", True), ("n", False), ("escape", False)],
)
async def test_keys_resolve_the_modal(key, expected):
    host = _ModalHost(ApprovalModal("edit_file", ApprovalPreview("{}", DIFF, "diff")))
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()
        assert host.result is expected
