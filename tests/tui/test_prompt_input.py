"""The multi-line prompt widget, driven headlessly through a tiny host app.

Mirrors `tests/tui/test_pickers.py`: a minimal `App` mounts the widget under test and
records what it posts, so every assertion is about real key handling rather than about a
method called directly.
"""

from __future__ import annotations

from textual.app import App, ComposeResult

from agent86.tui.widgets.prompt_input import MAX_ROWS, PromptInput
from agent86.ui.history import PromptHistory


class _PromptHost(App):
    """Mounts one PromptInput and collects the values it submits."""

    def __init__(self, history: PromptHistory | None = None) -> None:
        super().__init__()
        self._history = history
        self.submitted: list[str] = []

    def compose(self) -> ComposeResult:
        yield PromptInput(history=self._history, id="prompt")

    def on_mount(self) -> None:
        self.query_one("#prompt", PromptInput).focus()

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        self.submitted.append(event.value)


def _prompt(host: _PromptHost) -> PromptInput:
    return host.query_one("#prompt", PromptInput)


async def test_enter_submits_the_typed_value():
    host = _PromptHost()
    async with host.run_test() as pilot:
        await pilot.press(*"hello")
        await pilot.press("enter")
        await pilot.pause()
        assert host.submitted == ["hello"]


async def test_ctrl_j_inserts_a_newline_without_submitting():
    host = _PromptHost()
    async with host.run_test() as pilot:
        await pilot.press(*"one")
        await pilot.press("ctrl+j")
        await pilot.press(*"two")
        await pilot.pause()
        assert host.submitted == []
        assert _prompt(host).value == "one\ntwo"
        await pilot.press("enter")
        await pilot.pause()
        assert host.submitted == ["one\ntwo"]


async def test_shift_enter_also_inserts_a_newline():
    host = _PromptHost()
    async with host.run_test() as pilot:
        await pilot.press(*"a")
        await pilot.press("shift+enter")
        await pilot.press(*"b")
        await pilot.pause()
        assert host.submitted == []
        assert _prompt(host).value == "a\nb"


async def test_escape_clears_the_draft():
    host = _PromptHost()
    async with host.run_test() as pilot:
        await pilot.press(*"draft text")
        await pilot.press("escape")
        await pilot.pause()
        assert _prompt(host).value == ""
        assert host.submitted == []


async def test_submitting_records_history(tmp_path):
    history = PromptHistory(tmp_path / "history")
    host = _PromptHost(history)
    async with host.run_test() as pilot:
        await pilot.press(*"remember me")
        await pilot.press("enter")
        await pilot.pause()
    assert history.entries == ["remember me"]
    # ...and it reached the shared file, not just memory.
    assert PromptHistory(tmp_path / "history").entries == ["remember me"]


async def test_up_and_down_walk_history_then_restore_the_draft(tmp_path):
    history = PromptHistory(tmp_path / "history")
    history.append("oldest")
    history.append("newest")
    host = _PromptHost(history)
    async with host.run_test() as pilot:
        await pilot.press(*"half")
        await pilot.press("up")
        await pilot.pause()
        assert _prompt(host).value == "newest"
        await pilot.press("up")
        await pilot.pause()
        assert _prompt(host).value == "oldest"
        await pilot.press("up")  # already oldest: stays put, no wrap
        await pilot.pause()
        assert _prompt(host).value == "oldest"
        await pilot.press("down")
        await pilot.pause()
        assert _prompt(host).value == "newest"
        await pilot.press("down")
        await pilot.pause()
        assert _prompt(host).value == "half"


async def test_up_moves_the_cursor_inside_a_multi_line_draft(tmp_path):
    history = PromptHistory(tmp_path / "history")
    history.append("recalled")
    host = _PromptHost(history)
    async with host.run_test() as pilot:
        await pilot.press(*"one")
        await pilot.press("ctrl+j")
        await pilot.press(*"two")
        await pilot.pause()
        assert _prompt(host).cursor_location[0] == 1
        await pilot.press("up")  # second line -> first line, NOT history
        await pilot.pause()
        assert _prompt(host).value == "one\ntwo"
        assert _prompt(host).cursor_location[0] == 0
        await pilot.press("up")  # now on the first line -> history
        await pilot.pause()
        assert _prompt(host).value == "recalled"


async def test_down_moves_the_cursor_when_not_on_the_last_line():
    host = _PromptHost()
    async with host.run_test() as pilot:
        await pilot.press(*"one")
        await pilot.press("ctrl+j")
        await pilot.press(*"two")
        await pilot.press("up")
        await pilot.pause()
        assert _prompt(host).cursor_location[0] == 0
        await pilot.press("down")
        await pilot.pause()
        assert _prompt(host).cursor_location[0] == 1
        assert _prompt(host).value == "one\ntwo"


async def test_history_navigation_without_history_is_a_cursor_move():
    host = _PromptHost()  # no history attached at all
    async with host.run_test() as pilot:
        await pilot.press(*"text")
        await pilot.press("up")
        await pilot.press("down")
        await pilot.pause()
        assert _prompt(host).value == "text"
        assert host.submitted == []


async def test_editing_a_recalled_entry_leaves_navigation(tmp_path):
    history = PromptHistory(tmp_path / "history")
    history.append("recalled")
    host = _PromptHost(history)
    async with host.run_test() as pilot:
        await pilot.press("up")
        await pilot.press(*"!")
        await pilot.pause()
        assert _prompt(host).value == "recalled!"
        # The edit ended navigation, so Down is a plain cursor move and keeps the edit.
        await pilot.press("down")
        await pilot.pause()
        assert _prompt(host).value == "recalled!"


async def test_value_and_clear_are_input_compatible():
    host = _PromptHost()
    async with host.run_test() as pilot:
        prompt = _prompt(host)
        prompt.value = "/model "
        await pilot.pause()
        assert prompt.value == "/model "
        prompt.clear()
        await pilot.pause()
        assert prompt.value == ""


async def test_submitted_message_exposes_input_alias():
    """Handlers written against `Input.Submitted` keep working after the swap."""
    seen: list[str] = []

    class _AliasHost(_PromptHost):
        def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
            assert event.input is event.prompt_input is event.control
            assert event.input.id == "prompt"
            seen.append(event.value)
            event.input.value = ""

    host = _AliasHost()
    async with host.run_test() as pilot:
        await pilot.press(*"hi")
        await pilot.press("enter")
        await pilot.pause()
        assert seen == ["hi"]
        assert _prompt(host).value == ""


async def test_grows_with_content_then_stops_at_the_cap():
    host = _PromptHost()
    async with host.run_test(size=(80, 40)) as pilot:
        prompt = _prompt(host)
        await pilot.pause()
        one_row = prompt.size.height
        prompt.value = "a\nb\nc"
        await pilot.pause()
        assert prompt.size.height > one_row
        prompt.value = "\n".join(str(i) for i in range(MAX_ROWS * 3))
        await pilot.pause()
        assert prompt.size.height <= MAX_ROWS
