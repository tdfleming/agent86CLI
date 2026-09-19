"""REPL core — command dispatch, mode cycling, status — headless via a fake provider.

Since v0.6 ``_Repl.dispatch`` is a thin console renderer over the shared registry in
``agent86.tui.commands``, so these also pin the plain-mode (`agent86 --plain`) behavior of
every command the two surfaces have in common, plus the graceful degradation of the
TUI-only ones.
"""

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


def test_dispatch_uses_the_shared_command_registry(tmp_path, monkeypatch):
    """One implementation, two surfaces: the plain loop must not re-parse commands itself."""
    from agent86.tui import commands as commands_mod

    repl, _ = _repl(tmp_path)
    seen: list[str] = []
    real = commands_mod.handle_command

    def _spy(r, line):  # noqa: ANN001
        seen.append(line)
        return real(r, line)

    monkeypatch.setattr(commands_mod, "handle_command", _spy)
    repl.dispatch("/cost")
    assert seen == ["/cost"]


def test_help_prints_the_registry_table(tmp_path, capsys):
    from agent86.tui.commands import COMMANDS

    repl, _ = _repl(tmp_path)
    assert repl.dispatch("/help") == "handled"
    out = capsys.readouterr().out
    for entry in COMMANDS:
        assert entry.name in out


def test_quit_is_an_alias_for_exit(tmp_path, capsys):
    repl, _ = _repl(tmp_path)
    assert repl.dispatch("/quit") == "exit"
    assert "bye" in capsys.readouterr().out


def test_cost_command_prints_usage(tmp_path, capsys):
    repl, _ = _repl(tmp_path)
    assert repl.dispatch("/cost") == "handled"
    out = capsys.readouterr().out
    assert "steps" in out and "cost" in out


def test_config_model_degrades_gracefully_in_plain_mode(tmp_path, capsys):
    """The model manager is a TUI surface; in plain mode it says so rather than failing."""
    repl, _ = _repl(tmp_path)
    assert repl.dispatch("/config model") == "handled"
    assert "TUI surface" in capsys.readouterr().out


def test_mode_command_sets_and_cycles(tmp_path, capsys):
    repl, harness = _repl(tmp_path)
    assert repl.dispatch("/mode auto") == "handled"
    assert harness.gate.mode is ApprovalMode.AUTO
    assert "approval mode: auto" in capsys.readouterr().out
    assert repl.dispatch("/mode deny") == "handled"
    assert harness.gate.mode is ApprovalMode.DENY
    # bare /mode cycles: deny -> ask
    repl.dispatch("/mode")
    assert harness.gate.mode is ApprovalMode.ASK
    # invalid mode leaves it unchanged
    capsys.readouterr()
    repl.dispatch("/mode nonsense")
    assert harness.gate.mode is ApprovalMode.ASK
    assert "unknown mode" in capsys.readouterr().out


def test_hotkey_cycle_updates_gate_and_status(tmp_path):
    repl, harness = _repl(tmp_path)
    start = harness.gate.mode
    repl._cycle_approval()
    assert harness.gate.mode is not start
    assert repl.status.approval == harness.gate.mode.value


def test_model_command_switches_active_model(tmp_path, monkeypatch, capsys):
    repl, harness = _repl(tmp_path)
    # Switch to a keyless local provider (Ollama needs no API key).
    assert repl.dispatch("/model ollama:llama3.1") == "handled"
    assert harness.provider.name == "ollama"
    assert harness.provider.model == "llama3.1"
    assert repl.status.model == "llama3.1"  # status line updated
    assert "ollama:llama3.1" in capsys.readouterr().out

    # A slash-containing model id on a keyed provider works once its key is set.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    repl.dispatch("/model openrouter:anthropic/claude-3.7-sonnet")
    assert harness.provider.model == "anthropic/claude-3.7-sonnet"


def test_bare_model_command_shows_current_model(tmp_path, capsys):
    repl, harness = _repl(tmp_path)
    assert repl.dispatch("/model") == "handled"
    out = capsys.readouterr().out
    assert "current model" in out and harness.provider.model in out


def test_model_command_rejects_bad_ref_and_missing_key(tmp_path, monkeypatch, capsys):
    repl, harness = _repl(tmp_path)
    repl.dispatch("/model ollama:llama3.1")
    before = harness.provider.model
    # Malformed ref (no colon) -> ValueError -> model unchanged, error surfaced.
    capsys.readouterr()
    repl.dispatch("/model not-a-ref")
    assert harness.provider.model == before
    assert "provider:model" in capsys.readouterr().out
    # Missing API key -> ProviderError -> model unchanged.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    repl.dispatch("/model openai:gpt-4o")
    assert harness.provider.model == before


def test_status_line_reflects_state(tmp_path):
    repl, harness = _repl(tmp_path)
    repl._refresh_status()
    line = repl.status_line()
    assert harness.provider.model in line
    assert "mode:" in line and "sbx" in line
