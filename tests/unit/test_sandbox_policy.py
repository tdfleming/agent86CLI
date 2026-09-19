"""v0.7 — sandbox environment scrubbing across platforms, and honest timeout derivation."""

from __future__ import annotations

import logging

from agent86.config import load_config
from agent86.tools.sandbox import policy as policy_mod
from agent86.tools.sandbox.policy import (
    SandboxPolicy,
    default_policy,
    env_allowlist,
    is_secret_name,
)

POSIX_ESSENTIALS = ("HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TERM")
CA_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")


def _set_flag(model, name: str, value) -> None:
    """Set a config field that may not exist yet (the config agent adds it concurrently)."""
    try:
        setattr(model, name, value)
    except (ValueError, AttributeError):
        object.__setattr__(model, name, value)


def test_posix_allowlist_covers_what_git_pip_npm_need(monkeypatch):
    monkeypatch.setattr(policy_mod.os, "name", "posix")
    allowed = env_allowlist()
    for name in (*POSIX_ESSENTIALS, *CA_VARS, "PATH", "LANG"):
        assert name in allowed, f"{name} must survive scrubbing on POSIX"


def test_windows_allowlist_still_covers_console_vars(monkeypatch):
    monkeypatch.setattr(policy_mod.os, "name", "nt")
    allowed = env_allowlist()
    for name in ("PATH", "PATHEXT", "SYSTEMROOT", "COMSPEC", "TEMP", "USERPROFILE"):
        assert name in allowed


def test_posix_vars_are_forwarded(monkeypatch, tmp_path):
    monkeypatch.setattr(policy_mod.os, "name", "posix")
    monkeypatch.setenv("HOME", "/home/tester")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("SSL_CERT_FILE", "/etc/ssl/cert.pem")
    env = SandboxPolicy(workspace=tmp_path).scrubbed_env()
    assert env["HOME"] == "/home/tester"
    assert env["SHELL"] == "/bin/zsh"
    assert env["SSL_CERT_FILE"] == "/etc/ssl/cert.pem"


def test_locale_and_xdg_families_are_forwarded(monkeypatch, tmp_path):
    monkeypatch.setenv("LC_TIME", "en_GB.UTF-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/tester/.config")
    env = SandboxPolicy(workspace=tmp_path).scrubbed_env()
    assert env["LC_TIME"] == "en_GB.UTF-8"
    assert env["XDG_CONFIG_HOME"] == "/home/tester/.config"


def test_secrets_never_reach_a_subprocess(monkeypatch, tmp_path):
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "MY_SECRET", "SIGNING_KEY"):
        monkeypatch.setenv(name, "s3cr3t")
    env = SandboxPolicy(workspace=tmp_path).scrubbed_env()
    assert not [k for k in env if "s3cr3t" == env[k]]


def test_env_passthrough_forwards_an_opted_in_var(monkeypatch, tmp_path):
    monkeypatch.setenv("MY_BUILD_FLAVOUR", "debug")
    env = SandboxPolicy(workspace=tmp_path, env_passthrough=["MY_BUILD_FLAVOUR"]).scrubbed_env()
    assert env["MY_BUILD_FLAVOUR"] == "debug"


def test_env_passthrough_cannot_smuggle_a_secret(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-nope")
    monkeypatch.setenv("SOME_TOKEN", "nope")
    monkeypatch.setenv("APP_SECRET", "nope")
    policy = SandboxPolicy(
        workspace=tmp_path,
        env_passthrough=["ANTHROPIC_API_KEY", "SOME_TOKEN", "APP_SECRET"],
    )
    with caplog.at_level(logging.WARNING, logger="agent86.tools.sandbox.policy"):
        env = policy.scrubbed_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "SOME_TOKEN" not in env
    assert "APP_SECRET" not in env
    assert caplog.text.count("looks like a credential") == 3


def test_is_secret_name_patterns():
    for name in ("ANTHROPIC_API_KEY", "gh_token", "MySecretThing", "DB_PASSWORD", "SIGNING_KEY"):
        assert is_secret_name(name), name
    for name in ("PATH", "HOME", "LANG", "MY_BUILD_FLAVOUR", "KEYBOARD_LAYOUT"):
        assert not is_secret_name(name), name


def test_unlisted_vars_are_still_scrubbed(monkeypatch, tmp_path):
    monkeypatch.setenv("SOMETHING_RANDOM", "value")
    env = SandboxPolicy(workspace=tmp_path).scrubbed_env()
    assert "SOMETHING_RANDOM" not in env


# ---- timeout derivation -------------------------------------------------- #


def test_default_policy_timeout_uses_tool_timeout_s(tmp_path):
    cfg = load_config()
    _set_flag(cfg.limits, "tool_timeout_s", 17)
    assert default_policy(cfg, tmp_path).timeout_s == 17


def test_default_policy_timeout_is_independent_of_wall_clock(tmp_path):
    """A short run budget must not silently shorten every tool's timeout (the old behaviour)."""
    cfg = load_config()
    cfg.limits.max_wall_clock_s = 10
    assert default_policy(cfg, tmp_path).timeout_s >= 60


def test_default_policy_reads_env_passthrough(tmp_path):
    cfg = load_config()
    _set_flag(cfg.sandbox, "env_passthrough", ["MY_BUILD_FLAVOUR"])
    assert default_policy(cfg, tmp_path).env_passthrough == ["MY_BUILD_FLAVOUR"]


def test_tool_timeout_s_flows_from_config_into_the_policy(tmp_path):
    """The field is a real `LimitsConfig` attribute now — no getattr shim on either side."""
    cfg = load_config()
    assert cfg.limits.tool_timeout_s == 60
    assert default_policy(cfg, tmp_path).timeout_s == 60

    cfg.limits.tool_timeout_s = 5
    assert default_policy(cfg, tmp_path).timeout_s == 5
