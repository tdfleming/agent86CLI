"""`/resume` in the TUI: the picker opens, and picking rebuilds the transcript.

`tests/tui/test_session_picker.py` owns the modal itself; this file is about the wiring —
that the bare command reaches `open_session_picker`, that the id it dismisses with is
resolved through `harness.resume`, and that `load_session` puts the stored conversation
back on screen.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from textual.widgets import RichLog

from agent86.config import load_config
from agent86.memory.store import SessionInfo
from agent86.orchestration.loop import Harness
from agent86.orchestration.state import AgentState
from agent86.tui.app import Agent86App
from agent86.tui.screens.session_picker import SessionPickerModal
from agent86.types import ApprovalMode, Message, Role
from agent86.ui.repl import _Repl
from tests.support import make_text_provider

NOW = 1_700_000_000.0


class _FakeStore:
    """The slice of ``SessionStore`` the picker path actually touches."""

    def __init__(self, states: dict[str, AgentState], titles: dict[str, str]) -> None:
        self._states = states
        self._titles = titles

    def recent_sessions(self, limit: int = 20) -> list[SessionInfo]:
        return [
            SessionInfo(sid, self._titles.get(sid), NOW - i * 3600)
            for i, sid in enumerate(self._states)
        ][:limit]

    def session_title(self, session_id: str) -> str | None:
        return self._titles.get(session_id)

    def load_session(self, session_id: str) -> str | None:
        state = self._states.get(session_id)
        return state.model_dump_json() if state is not None else None


def _state(session_id: str, *pairs: tuple[str, str]) -> AgentState:
    state = AgentState(session_id=session_id)
    for user, assistant in pairs:
        state.add_message(Message(role=Role.USER, content=user))
        state.add_message(Message(role=Role.ASSISTANT, content=assistant))
    return state


def _make_repl(tmp_path, *, with_memory: bool = True):
    cfg = load_config()
    cfg.guardrails.approval = ApprovalMode.AUTO
    cfg.ui.history_file = str(tmp_path / "history")
    harness = Harness(cfg, provider=make_text_provider("hi"), memory=None, workspace=tmp_path)
    repl = _Repl(cfg, resume=None, harness=harness)
    if with_memory:
        states = {
            "aaaaaaaa1111": _state("aaaaaaaa1111", ("fix the jail", "jail fixed")),
            "bbbbbbbb2222": _state("bbbbbbbb2222", ("write the notes", "notes written")),
        }
        titles = {"aaaaaaaa1111": "fix the jail", "bbbbbbbb2222": "write the notes"}
        # `note=None` because `startup_notes` reads `harness.memory_note` on every mount.
        harness.memory = SimpleNamespace(store=_FakeStore(states, titles), note=None)
    return repl


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met within timeout")


def _lines(app: Agent86App) -> str:
    return "\n".join(str(line) for line in app.query_one("#transcript", RichLog).lines)


async def test_bare_resume_opens_the_picker_and_rebuilds_the_transcript(tmp_path):
    repl = _make_repl(tmp_path)
    app = Agent86App(repl)
    async with app.run_test(size=(140, 32)) as pilot:
        await pilot.pause()
        assert repl.state.session_id not in ("aaaaaaaa1111", "bbbbbbbb2222")

        app._dispatch_line("/resume")
        await _wait_until(lambda: isinstance(app.screen, SessionPickerModal))
        await pilot.pause()

        # Both sessions are offered, newest first.
        picker = app.screen
        assert isinstance(picker, SessionPickerModal)
        picker.dismiss("bbbbbbbb2222")
        await _wait_until(lambda: repl.state.session_id == "bbbbbbbb2222")
        await pilot.pause()

        lines = _lines(app)
        assert "write the notes" in lines and "notes written" in lines
        # ...and the session it replaced is gone from the rebuilt scrollback.
        assert "fix the jail" not in lines
        assert "resumed session bbbbbbbb2222" in lines


async def test_cancelling_the_picker_leaves_the_session_alone(tmp_path):
    repl = _make_repl(tmp_path)
    app = Agent86App(repl)
    async with app.run_test(size=(140, 32)) as pilot:
        await pilot.pause()
        before = repl.state.session_id

        app._dispatch_line("/resume")
        await _wait_until(lambda: isinstance(app.screen, SessionPickerModal))
        await pilot.press("escape")
        await pilot.pause()

        assert repl.state.session_id == before


async def test_resume_without_memory_is_a_note_not_a_picker(tmp_path):
    repl = _make_repl(tmp_path, with_memory=False)
    app = Agent86App(repl)
    async with app.run_test(size=(140, 32)) as pilot:
        await pilot.pause()
        app._dispatch_line("/resume")
        await pilot.pause()

        assert not isinstance(app.screen, SessionPickerModal)
        assert "memory is disabled" in _lines(app)
