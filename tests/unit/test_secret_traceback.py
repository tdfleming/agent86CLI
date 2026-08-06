"""Regression tests for UAT gap 2 (SEC-01 / D-10): a secret must never reach the terminal via
an unhandled crash below key resolution.

Two independent layers are tested:
1. Rich/Typer must never render frame locals (they held a live `api_key` local).
2. Any exception escaping provider construction must be converted to a redacted
   `ProviderError` with a severed `__cause__` chain, so the original frames (which hold the
   key) are never captured or rendered.
"""

from __future__ import annotations

import traceback

import pytest

from agent86.cognitive.base import ProviderError, provider_for_ref
from agent86.config import ProviderConfig, load_config
from agent86.secrets import redact
from agent86.types import ModelRef

#: Sentinel secret used throughout — a future grep finds every leak assertion.
KEY = "sk-ant-TESTKEY-0001"


# --------------------------------------------------------------------------- #
# Task 1: secrets.redact()
# --------------------------------------------------------------------------- #


def test_redact_removes_explicit_secret():
    out = redact(f"boom: {KEY} failed", KEY)
    assert KEY not in out
    assert "***redacted***" in out


def test_redact_removes_key_shaped_token_without_explicit_secret():
    out = redact("Client got sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAA")
    assert "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAA" not in out
    assert "***redacted***" in out


def test_redact_leaves_plain_text_alone():
    assert redact("nothing secret here") == "nothing secret here"


def test_redact_ignores_none_and_short_secrets():
    assert redact("x", None) == "x"
    assert redact("x", "") == "x"


def test_typer_app_does_not_show_locals():
    import agent86.cli

    assert agent86.cli.app.pretty_exceptions_show_locals is False


# --------------------------------------------------------------------------- #
# Task 2: provider_for_ref construction guard
# --------------------------------------------------------------------------- #


def _cfg_with_anthropic() -> ProviderConfig:
    cfg = load_config()
    cfg.providers["anthropic"] = ProviderConfig()
    return cfg


def test_construction_typeerror_becomes_provider_error(monkeypatch):
    def boom(self, *a, **k):
        raise TypeError("Client.__init__() got an unexpected keyword argument 'proxies'")

    monkeypatch.setattr(
        "agent86.cognitive.anthropic_provider.AnthropicProvider.__init__", boom
    )
    cfg = _cfg_with_anthropic()
    with pytest.raises(ProviderError) as exc_info:
        provider_for_ref(ModelRef.parse("anthropic:claude-opus-5"), cfg, api_key=KEY)
    assert not isinstance(exc_info.value, TypeError)


def test_provider_error_message_has_no_key(monkeypatch):
    def boom(self, *a, **k):
        raise TypeError(f"boom {KEY}")

    monkeypatch.setattr(
        "agent86.cognitive.anthropic_provider.AnthropicProvider.__init__", boom
    )
    cfg = _cfg_with_anthropic()
    with pytest.raises(ProviderError) as exc_info:
        provider_for_ref(ModelRef.parse("anthropic:claude-opus-5"), cfg, api_key=KEY)
    assert KEY not in str(exc_info.value)


def test_provider_error_cause_is_severed(monkeypatch):
    def boom(self, *a, **k):
        raise TypeError(f"boom {KEY}")

    monkeypatch.setattr(
        "agent86.cognitive.anthropic_provider.AnthropicProvider.__init__", boom
    )
    cfg = _cfg_with_anthropic()
    with pytest.raises(ProviderError) as exc_info:
        provider_for_ref(ModelRef.parse("anthropic:claude-opus-5"), cfg, api_key=KEY)
    err = exc_info.value
    assert err.__cause__ is None
    assert err.__suppress_context__ is True


def test_formatted_traceback_has_no_key(monkeypatch):
    def boom(self, *a, **k):
        raise TypeError(f"boom {KEY}")

    monkeypatch.setattr(
        "agent86.cognitive.anthropic_provider.AnthropicProvider.__init__", boom
    )
    cfg = _cfg_with_anthropic()
    try:
        provider_for_ref(ModelRef.parse("anthropic:claude-opus-5"), cfg, api_key=KEY)
    except ProviderError as err:
        formatted = "".join(
            traceback.format_exception(type(err), err, err.__traceback__)
        )
        assert KEY not in formatted
    else:  # pragma: no cover - defensive
        pytest.fail("expected ProviderError")


def test_deliberate_provider_error_passes_through_unchanged(monkeypatch):
    monkeypatch.delenv("SECRET_TRACEBACK_UNSET_VAR", raising=False)
    cfg = load_config()
    cfg.providers["anthropic"] = ProviderConfig(api_key_env="SECRET_TRACEBACK_UNSET_VAR")
    with pytest.raises(ProviderError) as exc_info:
        provider_for_ref(ModelRef.parse("anthropic:claude-opus-5"), cfg, api_key="")
    msg = str(exc_info.value)
    assert msg.startswith("No Anthropic API key found.")
    assert "Could not construct" not in msg
