"""v0.9: a finished assistant reply renders as Markdown, and nothing the model writes can crash.

The live `#stream` widget keeps showing plain text while deltas arrive (a half-written fence
renders as garbage, and re-parsing the document per delta is the cost this design avoids); the
completed reply is re-rendered through `rich.markdown.Markdown`, which never parses console
markup — so `[/weird]` in a table cell is literal text, not a `MarkupError` on the main thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

from textual.widgets import Input, RichLog

from agent86.cognitive.base import ModelProvider
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tui.app import Agent86App
from agent86.tui.widgets.transcript import (
    ReplyEntry,
    cap_lines,
    ellipsize,
    looks_like_markdown,
    pretty_json,
    render_reply,
)
from agent86.types import (
    ApprovalMode,
    Completion,
    CompletionDelta,
    CompletionRequest,
    Usage,
)
from agent86.ui.repl import _Repl

MARKDOWN_REPLY = """\
# Heading one

Some prose with `inline code` and a [/weird] closing tag.

## Steps

- first item
- second item

| column | value |
| --- | --- |
| alpha | [/x] |

```python
def hello(name):
    return f"hi {name}"
```
"""

_LONG_LINE = ", ".join(f'"item-{i}"' for i in range(80))
LONG_CODE_REPLY = f"""\
Here is the code:

```python
values = [{_LONG_LINE}]
```
"""


class _MarkdownProvider(ModelProvider):
    """Streams a Markdown document in several deltas, then completes."""

    name = "markdown"

    def __init__(self, reply: str = MARKDOWN_REPLY, chunks: int = 4) -> None:
        self.model = "fake:markdown"
        self._reply = reply
        self._chunks = chunks

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        size = max(1, len(self._reply) // self._chunks)
        for start in range(0, len(self._reply), size):
            yield CompletionDelta(text=self._reply[start : start + size])
        yield CompletionDelta(
            done=True,
            completion=Completion(
                text=self._reply,
                usage=Usage(input_tokens=3, output_tokens=2),
                model=self.model,
            ),
        )


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


def _strips(app):
    return app.query_one("#transcript", RichLog).lines


def _transcript(app) -> str:
    """The transcript as PLAIN text.

    `str(strip)` is a segment-by-segment repr, which syntax highlighting shreds into one
    segment per token — `def hello` would never match. `Strip.text` is what the user sees.
    """
    return "\n".join(line.text for line in _strips(app))


async def _run_turn(app, pilot, repl, line: str = "go") -> None:
    app.query_one("#prompt", Input).value = line
    await pilot.press("enter")
    await _wait_until(lambda: repl.status.working is False)
    await pilot.pause()


# ---- pure rendering helpers ------------------------------------------------- #


def test_looks_like_markdown_spots_structure_and_ignores_prose():
    assert looks_like_markdown("# Heading")
    assert looks_like_markdown("- a bullet")
    assert looks_like_markdown("1. numbered")
    assert looks_like_markdown("```\ncode\n```")
    assert looks_like_markdown("| a | b |")
    assert looks_like_markdown("some `inline` code")
    assert not looks_like_markdown("just a sentence about list[int] and [/paths]")
    assert not looks_like_markdown("   ")


def test_render_reply_never_parses_console_markup():
    """Both branches render through renderables that ignore markup — no MarkupError, ever."""
    import io

    from rich.console import Console

    for markdown in (True, False):
        console = Console(width=60, file=io.StringIO(), record=True)
        console.print(render_reply("see [/path/to/file] now", markdown=markdown))
        assert "[/path/to/file]" in console.export_text()


def test_pretty_json_and_caps():
    assert pretty_json({"a": 1}) == '{\n  "a": 1\n}'
    assert pretty_json(None, "fallback") == "fallback"
    capped = cap_lines("\n".join(str(i) for i in range(300)), 200)
    assert capped.splitlines()[200].startswith("… truncated (100 more lines)")
    assert ellipsize("a" * 50, 10) == "a" * 9 + "…"
    assert ellipsize("short", 10) == "short"


def test_reply_entry_is_plain_until_it_is_final():
    entry = ReplyEntry(text="# Heading", markdown=True)
    from rich.text import Text

    assert isinstance(entry.render(), Text)  # mid-stream: plain
    entry.final = True
    assert not isinstance(entry.render(), Text)  # complete: a Markdown group


# ---- end-to-end through the app --------------------------------------------- #


async def test_markdown_reply_renders_without_exceptions(tmp_path):
    repl = _make_repl(tmp_path, _MarkdownProvider())
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _run_turn(app, pilot, repl)

        assert app.is_running  # no MarkupError reached the main thread
        lines = _transcript(app)
        assert "Heading one" in lines
        assert "first item" in lines
        assert "alpha" in lines  # the table rendered
        assert "def hello" in lines  # the fenced python block rendered
        assert "[/weird]" in lines  # a closing-tag lookalike survived verbatim
        assert "[/x]" in lines  # …including inside a table cell
        # the reply was rendered as ONE Markdown document, labelled once
        assert lines.count("agent86") == 1


async def test_markdown_reply_has_headings_and_bullets_as_structure(tmp_path):
    """Not just the words — Markdown structure (a bullet glyph, a table rule) is visible."""
    repl = _make_repl(tmp_path, _MarkdownProvider())
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _run_turn(app, pilot, repl)

        lines = _transcript(app)
        assert "•" in lines or "┃" in lines or "─" in lines


async def test_wide_code_block_wraps_instead_of_blowing_the_layout(tmp_path):
    """Rich renders fenced code through `Syntax(word_wrap=True)`: no runaway virtual width."""
    repl = _make_repl(tmp_path, _MarkdownProvider(LONG_CODE_REPLY))
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _run_turn(app, pilot, repl)

        log = app.query_one("#transcript", RichLog)
        # Every rendered line fits the widget (min_width is 78, so allow that floor).
        widest = max(strip.cell_length for strip in log.lines)
        assert widest <= max(log.size.width, log.min_width), widest
        # …and the prompt and footer are still on screen.
        assert app.query_one("#prompt", Input).region.height > 0
        assert app.query_one("#status").region.height > 0
        assert "item-79" in _transcript(app)


async def test_markdown_can_be_switched_off(tmp_path):
    """`markdown = False` (the seam config binds to later) keeps the plain escaped rendering."""
    repl = _make_repl(tmp_path, _MarkdownProvider())
    app = Agent86App(repl)
    app.markdown = False
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _run_turn(app, pilot, repl)

        lines = _transcript(app)
        assert "# Heading one" in lines  # the literal source, not a rendered heading
        assert "```python" in lines
        assert app.is_running


async def test_the_user_prompt_echo_stays_plain(tmp_path):
    """The user's own line is never Markdown — a typed `#` is a `#`, and `[/x]` is literal."""
    repl = _make_repl(tmp_path, _MarkdownProvider(reply="ok"))
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _run_turn(app, pilot, repl, "# not a heading [/x]")

        assert "> # not a heading [/x]" in _transcript(app)
        assert app.is_running


async def test_streaming_reply_is_plain_while_it_arrives(tmp_path):
    """Mid-stream the transcript holds provisional plain text; the Markdown lands at the end."""
    from agent86.tui.messages import TurnDelta

    repl = _make_repl(tmp_path, _MarkdownProvider(reply="ok"))
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        app.on_turn_delta(TurnDelta("# Heading one\n\nbody text\n\n"))
        await pilot.pause()

        assert "# Heading one" in _transcript(app)  # literal source, still streaming
        assert app._reply is not None and app._reply.final is False

        app._finish_reply()  # what TurnDone (or the next tool call) does
        await pilot.pause()
        lines = _transcript(app)
        assert "# Heading one" not in lines  # replaced by the rendered heading
        assert "Heading one" in lines
