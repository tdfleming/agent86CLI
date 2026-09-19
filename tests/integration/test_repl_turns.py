"""Plain-loop turn rendering: streaming, tool turns, spacing, error handling.

These drive the actual render path in ``ui/repl.py`` with fake providers, no TTY and no
network. They lock in the v0.4.2/v0.4.3 fixes that still apply to the plain loop: streamed
output prints, tool turns render, turns are blank-line separated, and a provider error is
reported without killing the loop. (The worker-thread streaming path moved to the TUI in
v0.6 — ``tests/tui/`` covers it there.)
"""

from __future__ import annotations

import pytest

from agent86.cognitive.base import ProviderError
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.types import ApprovalMode, ToolCall
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


@pytest.mark.parametrize("command", ["/exit", "/quit"])
def test_plain_loop_exits_on_exit_commands(tmp_path, capsys, monkeypatch, command):
    repl, _ = _repl(tmp_path)
    _feed(monkeypatch, command, "never reached")

    repl.plain_loop()

    assert "bye" in capsys.readouterr().out
