"""Phase 1 — configuration resolution."""

from __future__ import annotations

import textwrap

import pytest
from pydantic import ValidationError

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


# --- Streaming HTTP timeouts (quick task 260813-jfk) ------------------------------------------ #


def test_provider_config_default_timeouts():
    from agent86.config import ProviderConfig

    pconf = ProviderConfig()
    assert pconf.read_timeout_s == 300.0
    assert pconf.connect_timeout_s == 10.0


def test_provider_timeout_override_is_per_provider(monkeypatch, tmp_path):
    user = tmp_path / "config.toml"
    user.write_text(
        textwrap.dedent(
            """
            [providers.ollama]
            read_timeout_s = 900.0
            """
        )
    )
    monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", user)
    monkeypatch.setattr(config_mod, "PROJECT_CONFIG_PATH", tmp_path / "none.toml")

    cfg = load_config()
    assert cfg.providers["ollama"].read_timeout_s == 900.0
    # Deep-merge must not smear one provider's override onto another.
    assert cfg.providers["openai"].read_timeout_s == 300.0


# --- Wave 0 scaffolds: MCPServerConfig.enabled + build_mcp filtering (MCP-01) ----------------- #


def test_mcp_server_enabled_defaults_true():
    assert MCPServerConfig(command="npx").enabled is True


def test_mcp_server_enabled_round_trips_false():
    assert MCPServerConfig(command="npx", enabled=False).enabled is False


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


# --- v0.7: mode enums + shared-contract fields ------------------------------------------------ #


def test_mode_fields_are_str_enums():
    """StrEnum keeps every existing `== "string"` comparison working."""
    from agent86.config import EgressMode, IngressMode, RouterMode, SandboxMode

    cfg = Config()
    assert cfg.model.router is RouterMode.OFF
    assert cfg.sandbox.mode is SandboxMode.SUBPROCESS
    assert cfg.guardrails.ingress is IngressMode.WARN
    assert cfg.guardrails.egress is EgressMode.WARN

    # The comparisons scattered through router.py / executor.py / guardrails/*.py
    assert cfg.model.router == "off"
    assert cfg.sandbox.mode == "subprocess"
    assert cfg.guardrails.ingress == "warn"
    assert cfg.guardrails.egress == "warn"
    assert Config(guardrails={"egress": "redact"}).guardrails.egress == "redact"
    # ...and f-string rendering stays the bare value (banner / prompt / status line).
    assert f"{cfg.sandbox.mode}" == "subprocess"
    assert f"{cfg.model.router}" == "off"


def test_legacy_toml_with_mode_keys_still_loads(monkeypatch, tmp_path):
    user = tmp_path / "config.toml"
    user.write_text(
        textwrap.dedent(
            """
            [model]
            router = "triage"
            [sandbox]
            mode = "docker"
            [guardrails]
            ingress = "block"
            egress = "redact"
            """
        )
    )
    monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", user)
    monkeypatch.setattr(config_mod, "PROJECT_CONFIG_PATH", tmp_path / "none.toml")

    cfg = load_config()
    assert cfg.model.router == "triage"
    assert cfg.sandbox.mode == "docker"
    assert cfg.guardrails.ingress == "block"
    assert cfg.guardrails.egress == "redact"
    # Round-trips back out as plain strings (what config_writer writes, what tomllib reads).
    dumped = cfg.model_dump(mode="json")
    assert dumped["sandbox"]["mode"] == "docker"
    assert dumped["guardrails"]["egress"] == "redact"
    assert dumped["model"]["router"] == "triage"


@pytest.mark.parametrize(
    ("section", "field", "bad", "allowed"),
    [
        ("model", "router", "tirage", ["'off'", "'triage'"]),
        ("sandbox", "mode", "dcoker", ["'subprocess'", "'docker'"]),
        ("guardrails", "ingress", "blcok", ["'off'", "'warn'", "'block'"]),
        ("guardrails", "egress", "redcat", ["'off'", "'warn'", "'redact'"]),
    ],
)
def test_bad_mode_value_raises_naming_allowed_values(section, field, bad, allowed):
    """A typo used to silently disable the feature; now it fails loudly and says why."""
    with pytest.raises(ValidationError) as excinfo:
        Config(**{section: {field: bad}})
    message = str(excinfo.value)
    assert field in message
    for value in allowed:
        assert value in message


def test_shared_contract_defaults():
    cfg = Config()
    assert cfg.providers["anthropic"].max_retries == 2
    assert cfg.agents.max_steps == 8
    assert cfg.tools.web_allow_private is False
    assert cfg.sandbox.env_passthrough == []
    assert cfg.pricing.models == {}


def test_shared_contract_fields_load_from_toml(monkeypatch, tmp_path):
    user = tmp_path / "config.toml"
    user.write_text(
        textwrap.dedent(
            """
            [providers.anthropic]
            max_retries = 5
            [agents]
            max_steps = 3
            [tools]
            web_allow_private = true
            [sandbox]
            env_passthrough = ["HTTPS_PROXY", "NO_PROXY"]

            [pricing.models."anthropic:claude-sonnet-5"]
            input_per_mtok = 3.0
            output_per_mtok = 15.0
            """
        )
    )
    monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", user)
    monkeypatch.setattr(config_mod, "PROJECT_CONFIG_PATH", tmp_path / "none.toml")

    cfg = load_config()
    assert cfg.providers["anthropic"].max_retries == 5
    # Deep-merge keeps the other providers on the default retry budget.
    assert cfg.providers["openai"].max_retries == 2
    assert cfg.agents.max_steps == 3
    assert cfg.tools.web_allow_private is True
    assert cfg.sandbox.env_passthrough == ["HTTPS_PROXY", "NO_PROXY"]
    assert cfg.pricing.models["anthropic:claude-sonnet-5"].input_per_mtok == 3.0

    # ...and the loaded overrides reach the cost meter.
    from agent86.cognitive import pricing

    price = pricing.lookup("anthropic:claude-sonnet-5")
    assert price is not None and price.source == "config"
    pricing.set_overrides(None)


def test_limits_tool_timeout_s_defaults_to_60(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", tmp_path / "none.toml")
    monkeypatch.setattr(config_mod, "PROJECT_CONFIG_PATH", tmp_path / "none2.toml")
    cfg = load_config()
    assert cfg.limits.tool_timeout_s == 60
    # It is a per-tool budget, not the whole-run one — they must be independent fields.
    assert cfg.limits.max_wall_clock_s == 900


def test_limits_tool_timeout_s_is_configurable(monkeypatch, tmp_path):
    user = tmp_path / "config.toml"
    user.write_text(
        textwrap.dedent(
            """
            [limits]
            tool_timeout_s = 5
            """
        )
    )
    monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", user)
    monkeypatch.setattr(config_mod, "PROJECT_CONFIG_PATH", tmp_path / "none.toml")
    cfg = load_config()
    assert cfg.limits.tool_timeout_s == 5
    assert cfg.limits.max_wall_clock_s == 900  # untouched by the per-tool budget
