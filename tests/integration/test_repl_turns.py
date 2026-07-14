"""v0.5 — REPL turn rendering: worker-thread streaming, tool turns, plain-loop spacing.

These drive the actual render paths in ui/repl.py (previously the least-covered module) with
fake providers, no TTY and no network. They lock in the v0.4.2/v0.4.3 fixes: streamed output
prints, tool turns render, and turns are blank-line separated.
"""

from __future__ import annotations

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


def test_run_turn_rich_streams_response_and_advances_state(tmp_path, capsys):
    repl, _ = _repl(tmp_path, reply="the answer is 42")
    before = len(repl.state.messages)
    repl._run_turn_rich("what is it?")
    out = capsys.readouterr().out
    assert "agent86" in out and "the answer is 42" in out
    # the turn appended the user message + assistant reply
    assert len(repl.state.messages) > before
    assert repl.state.messages[-1].content == "the answer is 42"


def test_run_turn_rich_executes_tool_turn(tmp_path, capsys):
    cfg = load_config()
    cfg.guardrails.approval = ApprovalMode.AUTO
    call = ToolCall(id="c1", name="write_file", arguments={"path": "out.txt", "content": "hi"})
    harness = Harness(
        cfg, provider=ToolThenTextProvider(call, reply="done"), memory=None, workspace=tmp_path
    )
    repl = _Repl(cfg, resume=None, harness=harness)
    repl._run_turn_rich("write a file")
    out = capsys.readouterr().out
    # the tool announce + result lines render, and the final answer streams
    assert "[tool] write_file" in out and "done" in out
    assert (tmp_path / "out.txt").read_text() == "hi"


def test_plain_loop_end_to_end_with_blank_line_spacing(tmp_path, capsys, monkeypatch):
    repl, _ = _repl(tmp_path, reply="hello world")
    lines = iter(["hi there", "/exit"])

    def fake_input(prompt: str = "") -> str:
        try:
            return next(lines)
        except StopIteration as exc:  # pragma: no cover - guard
            raise EOFError from exc

    monkeypatch.setattr("builtins.input", fake_input)
    repl.plain_loop()
    out = capsys.readouterr().out
    assert "hello world" in out
    # v0.4.3 spacing: a blank line separates the response from the next prompt
    assert "\n\n" in out


def test_dispatch_slash_commands_do_not_run_turns(tmp_path, capsys):
    repl, _ = _repl(tmp_path)
    assert repl.dispatch("/tools") == "handled"
    assert repl.dispatch("/cost") == "handled"
    assert repl.dispatch("/memory") == "handled"
    assert repl.dispatch("hello") == "turn"  # non-command routes to a turn
