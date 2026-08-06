"""Phase 1 — configuration resolution."""

from __future__ import annotations

import textwrap

import pytest

from agent86 import config as config_mod
from agent86.config import Config, MCPServerConfig, _deep_merge, load_config
from agent86.types import ApprovalMode


def test_defaults_load_without_files(monkeypatch, tmp_path):
    # Point both config layers at nonexistent files.
    monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", tmp_path / "nope.toml")
    monkeypatch.setattr(config_mod, "PROJECT_CONFIG_PATH", tmp_path / "also-nope.toml")
    cfg = load_config()
    assert isinstance(cfg, Config)
    assert cfg.model.default == "anthropic:claude-opus-4-8"
    assert set(cfg.providers) == {
        "anthropic", "openai", "openrouter", "groq", "ollama", "llamacpp"
    }
    assert cfg.guardrails.approval is ApprovalMode.ASK
    assert cfg.sources == []


def test_overrides_win_over_files(monkeypatch, tmp_path):
    user = tmp_path / "config.toml"
    user.write_text(
        textwrap.dedent(
            """
            [model]
            default = "ollama:llama3.1"
            [sandbox]
            mode = "docker"
            """
        )
    )
    monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", user)
    monkeypatch.setattr(config_mod, "PROJECT_CONFIG_PATH", tmp_path / "none.toml")

    cfg = load_config({"model": {"default": "openai:gpt-4o"}})
    assert cfg.model.default == "openai:gpt-4o"  # override beats file
    assert cfg.sandbox.mode == "docker"  # file beats default
    assert str(user) in cfg.sources


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", tmp_path / "none.toml")
    monkeypatch.setattr(config_mod, "PROJECT_CONFIG_PATH", tmp_path / "none2.toml")
    monkeypatch.setenv("AGENT86_MODEL", "ollama:qwen2.5")
    cfg = load_config()
    assert cfg.model.default == "ollama:qwen2.5"


def test_mcp_servers_normalized(monkeypatch, tmp_path):
    user = tmp_path / "config.toml"
    user.write_text(
        textwrap.dedent(
            """
            [mcp.servers.example]
            command = "npx"
            args = ["-y", "some-mcp-server"]
            """
        )
    )
    monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", user)
    monkeypatch.setattr(config_mod, "PROJECT_CONFIG_PATH", tmp_path / "none.toml")
    cfg = load_config()
    assert "example" in cfg.mcp_servers
    assert cfg.mcp_servers["example"].command == "npx"


def test_deep_merge_is_recursive():
    base = {"a": {"x": 1, "y": 2}, "b": 1}
    overlay = {"a": {"y": 3, "z": 4}}
    assert _deep_merge(base, overlay) == {"a": {"x": 1, "y": 3, "z": 4}, "b": 1}


# --- Wave 0 scaffolds: MCPServerConfig.enabled + build_mcp filtering (MCP-01) ----------------- #


@pytest.mark.xfail(reason="Wave 0 scaffold — plan 04-03", strict=False)
def test_mcp_server_enabled_defaults_true():
    assert MCPServerConfig(command="npx").enabled is True


@pytest.mark.xfail(reason="Wave 0 scaffold — plan 04-03", strict=False)
def test_mcp_server_enabled_round_trips_false():
    assert MCPServerConfig(command="npx", enabled=False).enabled is False


@pytest.mark.xfail(reason="Wave 0 scaffold — plan 04-04", strict=False)
def test_build_mcp_filters_disabled_servers(monkeypatch):
    import agent86.tools.mcp_client as mcp_client
    from agent86.tools.mcp_client import build_mcp

    monkeypatch.setattr(mcp_client.MCPManager, "start", lambda self: None)

    cfg = Config(
        mcp_servers={
            "on": MCPServerConfig(command="npx", enabled=True),
            "off": MCPServerConfig(command="npx", enabled=False),
        }
    )
    manager = build_mcp(cfg)
    assert manager is not None
    assert set(manager.servers) == {"on"}


@pytest.mark.xfail(reason="Wave 0 scaffold — plan 04-04", strict=False)
def test_build_mcp_returns_none_when_all_disabled(monkeypatch):
    import agent86.tools.mcp_client as mcp_client
    from agent86.tools.mcp_client import build_mcp

    monkeypatch.setattr(mcp_client.MCPManager, "start", lambda self: None)

    cfg = Config(
        mcp_servers={
            "off1": MCPServerConfig(command="npx", enabled=False),
            "off2": MCPServerConfig(command="npx", enabled=False),
        }
    )
    assert build_mcp(cfg) is None
