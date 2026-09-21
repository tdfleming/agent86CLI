"""The session picker: labels, filtering, and what it dismisses with."""

from __future__ import annotations

import time

from textual.app import App, ComposeResult

from agent86.memory.store import SessionInfo
from agent86.tui.commands import relative_time, session_label
from agent86.tui.screens.session_picker import SessionPickerModal

NOW = 1_700_000_000.0


def _sessions() -> list[SessionInfo]:
    return [
        SessionInfo("aaaaaaaa1111", "fix the sandbox jail", NOW - 120),
        SessionInfo("bbbbbbbb2222", "write the release notes", NOW - 7200),
        SessionInfo("cccccccc3333", None, NOW - 86400 * 3),
    ]


class _PickerHost(App):
    """Minimal host app: pushes the picker on mount, records the dismissed value."""

    def __init__(self, picker) -> None:
        super().__init__()
        self._picker = picker
        self.result: object = "__unset__"

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(self._picker, self._store)

    def _store(self, value) -> None:
        self.result = value


# ---- labels -------------------------------------------------------------- #


def test_relative_time_buckets():
    assert relative_time(NOW - 5, NOW) == "just now"
    assert relative_time(NOW - 300, NOW) == "5m ago"
    assert relative_time(NOW - 7200, NOW) == "2h ago"
    assert relative_time(NOW - 86400 * 3, NOW) == "3d ago"
    assert relative_time(NOW - 86400 * 90, NOW) == "3mo ago"
    assert relative_time(0, NOW) == "unknown"


def test_relative_time_tolerates_a_future_timestamp():
    assert relative_time(NOW + 500, NOW) == "just now"


def test_relative_time_defaults_to_the_current_clock():
    assert relative_time(time.time() - 10) == "just now"


def test_session_label_is_title_id_and_age():
    info = SessionInfo("abcdef123456", "fix the jail", NOW - 3600)
    assert session_label(info, NOW) == "fix the jail · abcdef12 · 1h ago"


def test_session_label_names_an_untitled_session():
    assert session_label(SessionInfo("abcdef123456", None, NOW), NOW).startswith("(untitled) ·")


# ---- the modal ----------------------------------------------------------- #


async def test_picker_dismisses_with_the_selected_session_id():
    host = _PickerHost(SessionPickerModal(_sessions()))
    async with host.run_test() as pilot:
        await pilot.pause()
        option_list = host.screen.query_one("#session-list")
        option_list.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert host.result == "aaaaaaaa1111"


async def test_picker_escape_returns_none():
    host = _PickerHost(SessionPickerModal(_sessions()))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert host.result is None


async def test_picker_lists_every_session_with_its_label():
    host = _PickerHost(SessionPickerModal(_sessions()))
    async with host.run_test() as pilot:
        await pilot.pause()
        option_list = host.screen.query_one("#session-list")
        assert option_list.option_count == 3
        labels = [str(option_list.get_option_at_index(i).prompt) for i in range(3)]
        assert "fix the sandbox jail" in labels[0]
        assert "aaaaaaaa" in labels[0]
        assert "(untitled)" in labels[2]


async def test_filter_narrows_by_title_and_by_id():
    host = _PickerHost(SessionPickerModal(_sessions()))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press(*"release")
        await pilot.pause()
        option_list = host.screen.query_one("#session-list")
        assert option_list.option_count == 1
        assert option_list.get_option_at_index(0).id == "bbbbbbbb2222"


async def test_filter_matches_a_session_id_prefix():
    host = _PickerHost(SessionPickerModal(_sessions()))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press(*"cccc")
        await pilot.pause()
        option_list = host.screen.query_one("#session-list")
        assert option_list.option_count == 1
        assert option_list.get_option_at_index(0).id == "cccccccc3333"


async def test_enter_on_a_single_match_picks_it():
    host = _PickerHost(SessionPickerModal(_sessions()))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press(*"release")
        await pilot.press("enter")
        await pilot.pause()
        assert host.result == "bbbbbbbb2222"


async def test_enter_with_no_match_cancels():
    host = _PickerHost(SessionPickerModal(_sessions()))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press(*"zzzz")
        await pilot.press("enter")
        await pilot.pause()
        assert host.result is None


async def test_empty_session_list_is_survivable():
    host = _PickerHost(SessionPickerModal([]))
    async with host.run_test() as pilot:
        await pilot.pause()
        assert host.screen.query_one("#session-list").option_count == 0
        await pilot.press("escape")
        await pilot.pause()
        assert host.result is None


async def test_a_title_containing_markup_is_not_interpreted():
    """Titles are the user's own prompt text; they must never style the list."""
    sessions = [SessionInfo("dddddddd4444", "check [bold]this[/bold] out", NOW)]
    host = _PickerHost(SessionPickerModal(sessions))
    async with host.run_test() as pilot:
        await pilot.pause()
        option_list = host.screen.query_one("#session-list")
        assert "[bold]" in str(option_list.get_option_at_index(0).prompt)
