"""Parity coverage for the Textual command adapter (mirrors tests/integration/test_repl.py)."""

from __future__ import annotations

from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tui.commands import (
    COMMANDS,
    CommandResult,
    _help_table,
    find_command,
    find_command_for_line,
    handle_command,
)
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
    from rich.console import Group

    assert isinstance(result.render, Group)
    assert not isinstance(result.render, tuple)

    result = handle_command(repl, "/model")
    assert isinstance(result.render, str)
    assert "current model" in result.render


def test_trailing_whitespace_arg(tmp_path):
    repl, _ = _repl(tmp_path)

    result_bare = handle_command(repl, "/model")
    result_trailing = handle_command(repl, "/model ")
    assert result_trailing.render == result_bare.render


def test_config_model_routes_to_its_own_entry(tmp_path):
    match = find_command_for_line("/config model")
    assert match is not None
    entry, arg = match
    assert entry.name == "/config model"
    assert arg == ""


def test_config_alone_still_dumps_config(tmp_path):
    match = find_command_for_line("/config")
    assert match is not None
    assert match[0].name == "/config"


def test_models_still_beats_model_prefix(tmp_path):
    match = find_command_for_line("/models")
    assert match is not None
    entry, arg = match
    assert entry.name == "/models"
    assert arg == ""


def test_model_with_arg_still_parses(tmp_path):
    assert find_command_for_line("/model openai:gpt-4o") == (
        find_command("/model"),
        "openai:gpt-4o",
    )


def test_help_lists_config_model(tmp_path):
    from rich.console import Console

    console = Console(record=True, width=120)
    console.print(_help_table())
    text = console.export_text()
    assert "/config model" in text


def test_palette_prefix_matches_both_config_entries(tmp_path):
    names = [c.name for c in COMMANDS if c.name.startswith("/config")]
    assert names == ["/config", "/config model"]


def test_models_table_shows_key_source_not_key(tmp_path, monkeypatch):
    from rich.console import Console

    from agent86.tui import commands as commands_mod

    repl, _ = _repl(tmp_path)
    monkeypatch.setattr("agent86.secrets.has_stored_key", lambda name: name == "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    console = Console(record=True, width=120)
    console.print(commands_mod._models_tables(repl.cfg))
    text = console.export_text()
    assert "keyring" in text
    assert "sk-" not in text


def test_models_table_shows_keyring_availability(tmp_path, monkeypatch):
    from rich.console import Console

    from agent86.tui import commands as commands_mod

    repl, _ = _repl(tmp_path)
    monkeypatch.setattr("agent86.secrets.keyring_available", lambda: False)

    console = Console(record=True, width=120)
    console.print(commands_mod._models_tables(repl.cfg))
    text = console.export_text()
    assert "unavailable" in text
