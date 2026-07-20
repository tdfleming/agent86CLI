"""Parity coverage for the Textual command adapter (mirrors tests/integration/test_repl.py)."""

from __future__ import annotations

from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tui.commands import COMMANDS, CommandResult, _help_table, handle_command
from agent86.types import ApprovalMode
from agent86.ui.repl import _Repl
from tests.support import make_text_provider


def _repl(tmp_path):
    cfg = load_config()
    harness = Harness(cfg, provider=make_text_provider("hi there"), memory=None, workspace=tmp_path)
    return _Repl(cfg, resume=None, harness=harness), harness


def test_handle_command_routes_commands_and_turns(tmp_path):
    repl, _ = _repl(tmp_path)

    result = handle_command(repl, "")
    assert isinstance(result, CommandResult)
    assert result.action == "noop"

    result = handle_command(repl, "/help")
    assert result.action == "handled"
    assert result.render is not None

    result = handle_command(repl, "/tools")
    assert result.action == "handled"

    result = handle_command(repl, "/unknowncmd")
    assert result.action == "handled"

    result = handle_command(repl, "hello world")
    assert result.action == "turn"

    result = handle_command(repl, "/exit")
    assert result.action == "exit"


def test_mode_command_sets_and_cycles(tmp_path):
    repl, harness = _repl(tmp_path)

    handle_command(repl, "/mode auto")
    assert harness.gate.mode is ApprovalMode.AUTO

    handle_command(repl, "/mode deny")
    assert harness.gate.mode is ApprovalMode.DENY

    # bare /mode cycles: deny -> ask
    handle_command(repl, "/mode")
    assert harness.gate.mode is ApprovalMode.ASK

    # invalid mode leaves it unchanged
    handle_command(repl, "/mode nonsense")
    assert harness.gate.mode is ApprovalMode.ASK


def test_model_command_switches_active_model(tmp_path, monkeypatch):
    repl, harness = _repl(tmp_path)

    result = handle_command(repl, "/model ollama:llama3.1")
    assert result.action == "handled"
    assert harness.provider.name == "ollama"
    assert harness.provider.model == "llama3.1"
    assert repl.status.model == "llama3.1"

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    handle_command(repl, "/model openrouter:anthropic/claude-3.7-sonnet")
    assert harness.provider.model == "anthropic/claude-3.7-sonnet"


def test_model_command_rejects_bad_ref_and_missing_key(tmp_path, monkeypatch):
    repl, harness = _repl(tmp_path)
    handle_command(repl, "/model ollama:llama3.1")
    before = harness.provider.model

    # Malformed ref (no colon) -> ValueError -> model unchanged.
    result = handle_command(repl, "/model not-a-ref")
    assert harness.provider.model == before
    assert result.action == "handled"

    # Missing API key -> ProviderError -> model unchanged.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    handle_command(repl, "/model openai:gpt-4o")
    assert harness.provider.model == before


def test_clear_command_starts_new_session(tmp_path):
    repl, _ = _repl(tmp_path)
    before_id = repl.state.session_id

    result = handle_command(repl, "/clear")
    assert result.action == "handled"
    assert repl.state.session_id != before_id


def test_help_matches_registry(tmp_path):
    table = _help_table()
    assert len(table.rows) == len(COMMANDS)

    cell_text = "\n".join(
        "\n".join(str(cell) for cell in column._cells) for column in table.columns
    )
    for entry in COMMANDS:
        assert entry.description in cell_text


def test_models_vs_model_routing(tmp_path):
    repl, _ = _repl(tmp_path)

    result = handle_command(repl, "/models")
    assert isinstance(result.render, tuple)
    assert len(result.render) == 2

    result = handle_command(repl, "/model")
    assert isinstance(result.render, str)
    assert "current model" in result.render


def test_trailing_whitespace_arg(tmp_path):
    repl, _ = _repl(tmp_path)

    result_bare = handle_command(repl, "/model")
    result_trailing = handle_command(repl, "/model ")
    assert result_trailing.render == result_bare.render
