"""The wired prompt: multi-line submission, shared history, and `@file` mentions.

`tests/tui/test_prompt_input.py` owns the widget in isolation; this file is about the widget
*as the app's prompt* — that Enter reaches `submit_prompt`, that Up walks the same history
the plain loop appends to, and that a mention is expanded into the text the provider
actually receives (never into the line the transcript echoes).
"""

from __future__ import annotations

import asyncio

from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tui.app import Agent86App
from agent86.tui.widgets.prompt_input import PromptInput
from agent86.types import ApprovalMode, Completion, Usage
from agent86.ui.repl import _Repl
from tests.support import ScriptedProvider, make_text_provider


def _make_repl(tmp_path, provider, approval=ApprovalMode.AUTO):
    cfg = load_config()
    cfg.guardrails.approval = approval
    # Never the real ~/.agent86/history: the prompt records into this on every submit.
    cfg.ui.history_file = str(tmp_path / "history")
    harness = Harness(cfg, provider=provider, memory=None, workspace=tmp_path)
    return _Repl(cfg, resume=None, harness=harness)


def _scripted(reply: str = "done") -> ScriptedProvider:
    return ScriptedProvider(
        [Completion(text=reply, usage=Usage(input_tokens=3, output_tokens=2))]
    )


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met within timeout")


def _lines(app: Agent86App) -> str:
    from textual.widgets import RichLog

    return "\n".join(str(line) for line in app.query_one("#transcript", RichLog).lines)


# ---- submission --------------------------------------------------------- #


async def test_enter_submits_and_shift_enter_inserts_a_newline(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hi"))
    app = Agent86App(repl)
    async with app.run_test(size=(140, 24)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptInput)

        await pilot.press(*"one")
        await pilot.press("shift+enter")
        await pilot.press(*"two")
        await pilot.pause()
        # Shift+Enter is a newline, not a submission: the draft is still in the box.
        assert prompt.value == "one\ntwo"
        assert repl.status.working is False

        await pilot.press("enter")
        await _wait_until(lambda: repl.status.working is False and prompt.value == "")
        await pilot.pause()
        assert "one" in _lines(app)


async def test_up_recalls_the_previous_prompt(tmp_path):
    repl = _make_repl(tmp_path, make_text_provider("hi"))
    app = Agent86App(repl)
    async with app.run_test(size=(140, 24)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptInput)

        await pilot.press(*"hello")
        await pilot.press("enter")
        await _wait_until(lambda: repl.status.working is False)
        await pilot.pause()
        assert prompt.value == ""

        # The App's priority `up` binding no-ops (SkipAction) while the palette is hidden,
        # so the key falls through to the prompt's own history navigation.
        await pilot.press("up")
        await pilot.pause()
        assert prompt.value == "hello"
        # ...and it went into the file both surfaces share.
        assert repl.history.entries[-1] == "hello"


# ---- @file mentions ------------------------------------------------------ #


async def test_mention_is_expanded_into_the_request_but_not_the_echo(tmp_path):
    (tmp_path / "README.md").write_text("# the readme\nmention me\n", encoding="utf-8")
    provider = _scripted("read it")
    repl = _make_repl(tmp_path, provider)
    app = Agent86App(repl)
    async with app.run_test(size=(140, 24)) as pilot:
        await pilot.pause()
        app.query_one("#prompt", PromptInput).value = "look at @README.md please"
        await pilot.press("enter")
        await _wait_until(lambda: repl.status.working is False)
        await pilot.pause()

        assert provider.requests, "the turn never reached the provider"
        sent = provider.requests[-1].messages[-1].content
        assert "mention me" in sent            # the file's content was inlined
        assert "look at @README.md please" in sent

        # The transcript echoes what was TYPED, not the inlined block.
        echoed = next(
            (line for line in _lines(app).splitlines() if "look at" in line), ""
        )
        assert "mention me" not in echoed


async def test_at_token_offers_path_completions_in_the_palette(tmp_path):
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    repl = _make_repl(tmp_path, make_text_provider("ok"))
    app = Agent86App(repl)
    async with app.run_test(size=(140, 24)) as pilot:
        from textual.widgets import OptionList

        await pilot.pause()
        palette = app.query_one("#palette", OptionList)
        await pilot.press(*"look at @RE")
        await pilot.pause()
        assert palette.display is True
        assert palette.get_option_at_index(0).id == "README.md"

        await pilot.press("enter")
        await pilot.pause()
        # The completion replaced the token in place; the rest of the line survived, and
        # Enter completed rather than submitting.
        assert app.query_one("#prompt", PromptInput).value == "look at @README.md"
        assert repl.status.working is False


async def test_mention_outside_the_jail_is_reported_as_a_notice(tmp_path):
    provider = _scripted("nothing to read")
    repl = _make_repl(tmp_path, provider)
    app = Agent86App(repl)
    async with app.run_test(size=(140, 24)) as pilot:
        await pilot.pause()
        app.query_one("#prompt", PromptInput).value = "read @../../secrets.txt"
        await pilot.press("enter")
        await _wait_until(lambda: repl.status.working is False)
        await pilot.pause()

        notice = next(
            (
                line
                for line in _lines(app).splitlines()
                if "secrets.txt" in line and "refused" in line
            ),
            "",
        )
        assert notice, "the refused mention never reached the transcript"
        assert "dim" in notice and "yellow" in notice
        # Nothing outside the workspace was read, and the model was told so too.
        assert "not attached" in provider.requests[-1].messages[-1].content
