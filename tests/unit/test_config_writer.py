"""Wave 0 scaffold for MODEL-02: `agent86.config_writer` tomlkit round-trip tests.

Implemented by plan 03-03.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parents[1] / "fixtures" / "config_with_comments.toml"


def test_comments_preserved_roundtrip(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer

    target = tmp_path / "config.toml"
    shutil.copy(FIXTURE, target)
    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", target)

    edit = config_writer.plan_edit(
        "user", [(["providers", "groq", "api_key_env"], "GROQ_API_KEY")]
    )
    config_writer.apply_edit(edit)

    text = target.read_text()
    assert "# hand-written comment: my personal agent86 config" in text
    assert "# do not lose me" in text
    assert "# inline comment on the default model" in text
    assert "# a comment between sections" in text
    assert 'api_key_env = "GROQ_API_KEY"' in text


def test_scope_selection(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer

    user_path = tmp_path / "user_config.toml"
    project_path = tmp_path / "project_config.toml"
    shutil.copy(FIXTURE, user_path)
    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", user_path)
    monkeypatch.setattr(config_writer, "PROJECT_CONFIG_PATH", project_path)

    assert config_writer.scope_path("user") == user_path
    assert config_writer.scope_path("project") == project_path

    edit = config_writer.plan_edit(
        "project", [(["providers", "groq", "api_key_env"], "GROQ_API_KEY")]
    )
    assert edit.path == project_path

    config_writer.apply_edit(edit)
    assert project_path.exists()
    assert not user_path.exists() or user_path.read_text() != project_path.read_text()


def test_no_plaintext_secret_in_output(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer

    target = tmp_path / "config.toml"
    shutil.copy(FIXTURE, target)
    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", target)

    with pytest.raises(ValueError):
        config_writer.plan_edit("user", [(["providers", "groq", "api_key"], "sk-secret")])
    with pytest.raises(ValueError):
        config_writer.plan_edit("user", [(["providers", "groq", "token"], "x")])
    with pytest.raises(ValueError):
        config_writer.plan_edit("user", [(["providers", "groq", "secret"], "x")])

    edit = config_writer.plan_edit(
        "user", [(["providers", "groq", "api_key_env"], "GROQ_API_KEY")]
    )
    assert "sk-" not in edit.after_text


def test_diff_is_unified_and_names_the_path(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer

    target = tmp_path / "config.toml"
    shutil.copy(FIXTURE, target)
    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", target)

    edit = config_writer.plan_edit(
        "user", [(["providers", "groq", "api_key_env"], "GROQ_API_KEY")]
    )
    assert "+++ " in edit.diff
    assert str(edit.path) in edit.diff
    assert '+api_key_env = "GROQ_API_KEY"' in edit.diff


def test_malformed_toml_raises_config_write_error(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer

    target = tmp_path / "config.toml"
    target.write_text("[model\nbroken")
    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", target)

    with pytest.raises(config_writer.ConfigWriteError, match="Malformed config at"):
        config_writer.plan_edit("user", [(["providers", "groq", "api_key_env"], "GROQ_API_KEY")])


def test_creates_missing_file_and_parents(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer

    target = tmp_path / "nested" / "config.toml"
    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", target)

    edit = config_writer.plan_edit(
        "user", [(["providers", "groq", "api_key_env"], "GROQ_API_KEY")]
    )
    config_writer.apply_edit(edit)
    assert target.exists()


def test_multiple_changes_in_one_edit(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer

    target = tmp_path / "config.toml"
    shutil.copy(FIXTURE, target)
    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", target)

    edit = config_writer.plan_edit(
        "user",
        [
            (["providers", "groq", "api_key_env"], "GROQ_API_KEY"),
            (["providers", "groq", "base_url"], "https://api.groq.com/openai/v1"),
            (["model", "default"], "groq:llama-3.3-70b-versatile"),
        ],
    )

    assert 'api_key_env = "GROQ_API_KEY"' in edit.after_text
    assert 'base_url = "https://api.groq.com/openai/v1"' in edit.after_text
    assert 'default = "groq:llama-3.3-70b-versatile"' in edit.after_text
    assert edit.after_text.count("[providers.groq]") == 1
    assert "# inline comment on the default model" in edit.after_text
    assert '"anthropic:claude-opus-4-8"' not in edit.after_text


def test_apply_edit_reloads_config(tmp_path, monkeypatch):
    import agent86.config as config
    import agent86.config_writer as config_writer

    target = tmp_path / "config.toml"
    shutil.copy(FIXTURE, target)
    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", target)
    monkeypatch.setattr(config, "USER_CONFIG_PATH", target)

    edit = config_writer.plan_edit(
        "user", [(["model", "default"], "groq:llama-3.3-70b-versatile")]
    )
    result = config_writer.apply_edit(edit)

    assert result.model.default == "groq:llama-3.3-70b-versatile"


def test_atomic_write_leaves_no_temp_files(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer

    target = tmp_path / "config.toml"
    shutil.copy(FIXTURE, target)
    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", target)

    edit = config_writer.plan_edit(
        "user", [(["providers", "groq", "api_key_env"], "GROQ_API_KEY")]
    )
    config_writer.apply_edit(edit)

    assert list(tmp_path.glob(".config-*")) == []
