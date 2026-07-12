"""v0.2 — REPL core (command dispatch, mode cycling, status) headless via a fake provider."""

from __future__ import annotations

from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.types import ApprovalMode
from agent86.ui.repl import _Repl
from tests.support import make_text_provider


def _repl(tmp_path):
    cfg = load_config()
    harness = Harness(cfg, provider=make_text_provider("hi there"), memory=None, workspace=tmp_path)
    return _Repl(cfg, resume=None, harness=harness), harness


def test_dispatch_routes_commands_and_turns(tmp_path):
    repl, _ = _repl(tmp_path)
    assert repl.dispatch("") == "handled"
    assert repl.dispatch("/help") == "handled"
    assert repl.dispatch("/tools") == "handled"
    assert repl.dispatch("/unknowncmd") == "handled"  # unknown slash cmd is swallowed
    assert repl.dispatch("hello world") == "turn"
    assert repl.dispatch("/exit") == "exit"


def test_mode_command_sets_and_cycles(tmp_path):
    repl, harness = _repl(tmp_path)
    assert repl.dispatch("/mode auto") == "handled"
    assert harness.gate.mode is ApprovalMode.AUTO
    assert repl.dispatch("/mode deny") == "handled"
    assert harness.gate.mode is ApprovalMode.DENY
    # bare /mode cycles: deny -> ask
    repl.dispatch("/mode")
    assert harness.gate.mode is ApprovalMode.ASK
    # invalid mode leaves it unchanged
    repl.dispatch("/mode nonsense")
    assert harness.gate.mode is ApprovalMode.ASK


def test_hotkey_cycle_updates_gate_and_status(tmp_path):
    repl, harness = _repl(tmp_path)
    start = harness.gate.mode
    repl._cycle_approval()
    assert harness.gate.mode is not start
    assert repl.status.approval == harness.gate.mode.value


def test_status_line_reflects_state(tmp_path):
    repl, harness = _repl(tmp_path)
    repl._refresh_status()
    line = repl.status_line()
    assert harness.provider.model in line
    assert "mode:" in line and "sbx" in line
