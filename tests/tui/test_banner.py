"""The startup banner: one definition (``ui.repl.banner``), rendered by both surfaces.

Quick task 260922-bnr. Covers:

- ``banner(cfg, compact=True)`` is the identity core only (name, version, model); ``compact=
  False`` appends router/sandbox/approval/hint — the plain loop's only status surface.
- **The drift test** — the point of the whole task: the TUI's first transcript entry and the
  plain loop's printed banner agree on name, version and model, from the one function.
- The TUI: the banner survives ``_rerender()`` (a tool-block expand/collapse), ``/clear``
  wipes the scrollback down to exactly the banner, and resuming a session re-prepends it.
"""

from __future__ import annotations

import asyncio

from rich.console import Console
from textual.widgets import RichLog

from agent86 import __version__
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tui.app import Agent86App
from agent86.tui.widgets.prompt_input import PromptInput
from agent86.tui.widgets.transcript import RawEntry
from agent86.types import ApprovalMode, ToolCall
from agent86.ui.repl import banner, console as plain_console
from agent86.ui.repl import _Repl
from tests.support import ToolThenTextProvider, make_text_provider


def _make_repl(tmp_path, provider, approval=ApprovalMode.AUTO):
    cfg = load_config()
    cfg.guardrails.approval = approval
    harness = Harness(cfg, provider=provider, memory=None, workspace=tmp_path)
    return _Repl(cfg, resume=None, harness=harness)


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met within timeout")


def _transcript(app) -> str:
    return "\n".join(line.text for line in app.query_one("#transcript", RichLog).lines)


def _render(renderable) -> str:
    console = Console(record=True, width=120)
    console.print(renderable)
    return console.export_text()


def _tool_provider(content: str = "hi"):
    call = ToolCall(id="c1", name="write_file", arguments={"path": "out.txt", "content": content})
    return ToolThenTextProvider(call, reply="done")


async def _run_tool_turn(app, pilot, repl, line: str = "write it") -> None:
    app.query_one("#prompt", PromptInput).value = line
    await pilot.press("enter")
    await _wait_until(lambda: repl.status.working is False)
    await pilot.pause()


# ---- banner(), without a surface -------------------------------------------- #


def test_compact_banner_is_the_identity_core_only():
    cfg = load_config()
    text = _render(banner(cfg, compact=True))

    assert f"agent86 v{__version__}" in text
    assert cfg.model.default in text
    for absent in ("router", "sandbox", "approval", "/help"):
        assert absent not in text


def test_full_banner_appends_router_sandbox_approval_and_hint():
    cfg = load_config()
    text = _render(banner(cfg, compact=False))

    assert f"agent86 v{__version__}" in text
    assert cfg.model.default in text
    assert cfg.model.router in text
    assert cfg.sandbox.mode in text
    assert cfg.guardrails.approval.value in text
    assert "/help" in text


def test_banner_defaults_to_compact():
    cfg = load_config()
    assert _render(banner(cfg)) == _render(banner(cfg, compact=True))


# ---- the drift test ----------------------------------------------------------- #


async def test_tui_entry_and_plain_banner_agree_on_name_version_and_model(tmp_path, capsys):
    """The point of the whole task: one call, both surfaces, no independent copies to drift."""
    repl = _make_repl(tmp_path, make_text_provider("hi"))
    app = Agent86App(repl)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        tui_text = _transcript(app)

    plain_console.print(banner(repl.cfg, compact=False))
    plain_text = capsys.readouterr().out

    for token in (f"agent86 v{__version__}", repl.cfg.model.default):
        assert token in tui_text
        assert token in plain_text


# ---- the TUI: survives rerender, /clear, resume -------------------------------- #


async def test_banner_is_entry_zero_on_mount(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hi"))
    app = Agent86App(repl)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        assert isinstance(app._entries[0], RawEntry)
        assert "agentic harness" in _transcript(app)


async def test_banner_survives_rerender_on_tool_block_expand(tmp_path):
    repl = _make_repl(tmp_path, _tool_provider())
    app = Agent86App(repl)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await _run_tool_turn(app, pilot, repl)

        # ctrl+o expands the last tool block, which forces `_rerender()` — a bare
        # `log.write()` banner would vanish here; an entry survives by construction.
        await pilot.press("ctrl+o")
        await pilot.pause()

        assert isinstance(app._entries[0], RawEntry)
        assert "agentic harness" in _transcript(app)


async def test_clear_wipes_the_transcript_to_exactly_the_banner(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        app.submit_prompt("hi there")
        await _wait_until(lambda: repl.status.working is False)
        await pilot.pause()
        assert len(app._entries) > 1  # the banner plus the exchange that just ran

        app._dispatch_line("/clear")
        await pilot.pause()

        assert len(app._entries) == 1
        assert isinstance(app._entries[0], RawEntry)
        lines = _transcript(app)
        assert "agentic harness" in lines
        assert "hello world" not in lines
        assert "hi there" not in lines


async def test_resume_re_prepends_the_banner(tmp_path):
    from agent86.types import Message, Role

    repl = _make_repl(tmp_path, make_text_provider("hi"))
    app = Agent86App(repl)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        saved = repl.harness.new_session()
        saved.add_message(Message(role=Role.USER, content="what happened earlier?"))
        saved.add_message(Message(role=Role.ASSISTANT, content="a plain reply"))

        app.load_session(saved)
        await pilot.pause()

        assert isinstance(app._entries[0], RawEntry)
        lines = _transcript(app)
        assert "agentic harness" in lines
        assert "what happened earlier?" in lines
