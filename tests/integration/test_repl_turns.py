"""Plain-loop turn rendering: streaming, tool turns, spacing, error handling.

These drive the actual render path in ``ui/repl.py`` with fake providers, no TTY and no
network. They lock in the v0.4.2/v0.4.3 fixes that still apply to the plain loop: streamed
output prints, tool turns render, turns are blank-line separated, and a provider error is
reported without killing the loop. (The worker-thread streaming path moved to the TUI in
v0.6 — ``tests/tui/`` covers it there.)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent86.cognitive.base import ProviderError
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.types import ApprovalMode, CompletionDelta, ToolCall
from agent86.ui.repl import _Repl
from tests.support import ToolThenTextProvider, make_text_provider


def _repl(tmp_path, reply="the answer is 42", approval=ApprovalMode.AUTO):
    cfg = load_config()
    cfg.guardrails.approval = approval
    harness = Harness(cfg, provider=make_text_provider(reply), memory=None, workspace=tmp_path)
    return _Repl(cfg, resume=None, harness=harness), harness


def _feed(monkeypatch, *lines: str) -> None:
    """Drive ``input()`` with a fixed script; EOF once it runs out."""
    it = iter(lines)

    def fake_input(prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration as exc:  # pragma: no cover - guard
            raise EOFError from exc

    monkeypatch.setattr("builtins.input", fake_input)


def test_plain_loop_streams_response_and_advances_state(tmp_path, capsys, monkeypatch):
    repl, _ = _repl(tmp_path, reply="the answer is 42")
    before = len(repl.state.messages)
    _feed(monkeypatch, "what is it?", "/exit")

    repl.plain_loop()

    out = capsys.readouterr().out
    assert "agent86" in out and "the answer is 42" in out
    # the turn appended the user message + assistant reply
    assert len(repl.state.messages) > before
    assert repl.state.messages[-1].content == "the answer is 42"


def test_plain_loop_executes_tool_turn(tmp_path, capsys, monkeypatch):
    cfg = load_config()
    cfg.guardrails.approval = ApprovalMode.AUTO
    call = ToolCall(id="c1", name="write_file", arguments={"path": "out.txt", "content": "hi"})
    harness = Harness(
        cfg, provider=ToolThenTextProvider(call, reply="done"), memory=None, workspace=tmp_path
    )
    repl = _Repl(cfg, resume=None, harness=harness)
    _feed(monkeypatch, "write a file", "/exit")

    repl.plain_loop()

    out = capsys.readouterr().out
    # the tool announce + result lines render, and the final answer streams
    assert "[tool] write_file" in out and "done" in out
    assert (tmp_path / "out.txt").read_text() == "hi"


def test_plain_loop_end_to_end_with_blank_line_spacing(tmp_path, capsys, monkeypatch):
    repl, _ = _repl(tmp_path, reply="hello world")
    _feed(monkeypatch, "hi there", "/exit")

    repl.plain_loop()

    out = capsys.readouterr().out
    assert "hello world" in out
    # v0.4.3 spacing: a blank line separates the response from the next prompt
    assert "\n\n" in out


def test_plain_loop_reports_provider_error_without_exiting(tmp_path, capsys, monkeypatch):
    repl, harness = _repl(tmp_path)

    def _boom(line, state):  # noqa: ANN001
        raise ProviderError("upstream exploded")
        yield  # pragma: no cover - makes this a generator function

    monkeypatch.setattr(harness, "run_turn", _boom)
    _feed(monkeypatch, "go", "/exit")

    repl.plain_loop()  # must not raise

    out = capsys.readouterr().out
    assert "upstream exploded" in out
    assert "bye" in out  # the loop survived and processed the following /exit


def test_plain_loop_eof_ends_the_session(tmp_path, capsys, monkeypatch):
    repl, _ = _repl(tmp_path)
    _feed(monkeypatch)  # immediate EOF

    repl.plain_loop()

    assert "bye" in capsys.readouterr().out


def test_dispatch_slash_commands_do_not_run_turns(tmp_path, capsys):
    repl, _ = _repl(tmp_path)
    assert repl.dispatch("/tools") == "handled"
    assert repl.dispatch("/cost") == "handled"
    assert repl.dispatch("/memory") == "handled"
    assert repl.dispatch("hello") == "turn"  # non-command routes to a turn


# ---- harness notices (v0.8) --------------------------------------------- #


def test_plain_loop_sets_harness_notices_apart_from_the_answer(tmp_path, capsys, monkeypatch):
    repl, harness = _repl(tmp_path)

    def _run(line, state):  # noqa: ANN001
        yield CompletionDelta(text="\n[compacted 12 messages]\n")
        yield CompletionDelta(text="partial answer")
        yield CompletionDelta(text="\n[continuing after 40 steps]\n")

    monkeypatch.setattr(harness, "run_turn", _run)
    _feed(monkeypatch, "go", "/exit")

    repl.plain_loop()

    out = capsys.readouterr().out
    assert "[compacted 12 messages]" in out
    assert "[continuing after 40 steps]" in out
    # each notice gets its own line: never glued onto the model's sentence
    assert "partial answer[continuing" not in out
    for line in out.splitlines():
        if "compacted 12 messages" in line:
            assert line.strip() == "[compacted 12 messages]"


def test_plain_loop_renders_the_loops_own_compaction_notice(tmp_path, capsys, monkeypatch):
    """End-to-end: the real loop compacts, and the user sees a line saying so.

    The notice above is injected by a fake ``run_turn``; this one comes out of
    ``Harness._compact_if_needed`` itself, so the loop and the renderer are pinned together.
    """
    from agent86.types import Message, Role
    from tests.support import CompactingProvider

    cfg = load_config()
    cfg.limits.max_context_tokens = 60  # make the budget bite without a 200k fixture
    harness = Harness(
        cfg, provider=CompactingProvider(reply="all done"), memory=None, workspace=tmp_path
    )
    repl = _Repl(cfg, resume=None, harness=harness)
    for i in range(6):
        repl.state.messages.append(Message(role=Role.USER, content=f"question {i} " + "x" * 200))
        repl.state.messages.append(
            Message(role=Role.ASSISTANT, content=f"answer {i} " + "y" * 200)
        )
    _feed(monkeypatch, "and now finish", "/exit")

    repl.plain_loop()

    out = capsys.readouterr().out
    assert "all done" in out  # the answer still streamed normally
    lines = [line.strip() for line in out.splitlines() if "compacted" in line]
    assert lines, "the compaction notice never reached the screen"
    # Its own line, whole and unglued — the dim styling is dropped by the capsys console.
    assert lines[0].startswith("[compacted ") and lines[0].endswith("messages into a summary]")


def test_plain_loop_does_not_treat_model_brackets_as_a_notice(tmp_path, capsys, monkeypatch):
    repl, _ = _repl(tmp_path, reply="[see docs/ARCHITECTURE.md] for more")
    _feed(monkeypatch, "where?", "/exit")

    repl.plain_loop()

    out = capsys.readouterr().out
    assert "[see docs/ARCHITECTURE.md] for more" in out


# ---- per-turn cost line (v0.8) ----------------------------------------- #


def _set_last_turn(state, summary) -> None:
    """Attach a ``TurnSummary``-shaped object to ``state`` the way ``run_turn`` will.

    ``object.__setattr__`` so the test still works on a state model that has not grown the
    field yet — the UI reads it with ``getattr`` either way.
    """
    object.__setattr__(state, "last_turn", summary)


def _summary(**over):
    base = dict(
        input_tokens=4100, output_tokens=612, cache_read_tokens=1900, cache_creation_tokens=0,
        cost_usd=0.0123, steps=3, tool_calls=2, duration_s=8.2, compactions=0, continuations=0,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_plain_loop_prints_the_per_turn_cost_line(tmp_path, capsys, monkeypatch):
    repl, harness = _repl(tmp_path, reply="done")
    real = harness.run_turn

    def _run(line, state):  # noqa: ANN001
        yield from real(line, state)
        _set_last_turn(state, _summary())

    monkeypatch.setattr(harness, "run_turn", _run)
    _feed(monkeypatch, "go", "/exit")

    repl.plain_loop()

    out = capsys.readouterr().out
    assert "3 steps" in out and "2 tools" in out
    assert "4.1k in / 612 out (1.9k cached)" in out
    assert "8.2s" in out


def test_plain_loop_prints_nothing_when_there_is_no_summary(tmp_path, capsys, monkeypatch):
    """Older state (or a getattr fallback) must not produce a half-empty line."""
    repl, harness = _repl(tmp_path, reply="done")
    real = harness.run_turn

    def _run(line, state):  # noqa: ANN001
        yield from real(line, state)
        object.__setattr__(state, "last_turn", None)

    monkeypatch.setattr(harness, "run_turn", _run)
    _feed(monkeypatch, "go", "/exit")

    repl.plain_loop()

    out = capsys.readouterr().out
    assert "steps ·" not in out and "—" not in out


def test_plain_loop_prints_the_summary_of_a_failed_turn(tmp_path, capsys, monkeypatch):
    """A turn that died halfway still spent tokens; the loop closes the summary either way."""
    repl, harness = _repl(tmp_path)

    def _boom(line, state):  # noqa: ANN001
        _set_last_turn(state, _summary(steps=1, tool_calls=0))
        raise ProviderError("upstream exploded")
        yield  # pragma: no cover - makes this a generator function

    monkeypatch.setattr(harness, "run_turn", _boom)
    _feed(monkeypatch, "go", "/exit")

    repl.plain_loop()

    out = capsys.readouterr().out
    assert "upstream exploded" in out
    assert "1 step" in out


@pytest.mark.parametrize("command", ["/exit", "/quit"])
def test_plain_loop_exits_on_exit_commands(tmp_path, capsys, monkeypatch, command):
    repl, _ = _repl(tmp_path)
    _feed(monkeypatch, command, "never reached")

    repl.plain_loop()

    assert "bye" in capsys.readouterr().out
