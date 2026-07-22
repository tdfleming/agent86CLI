"""Wave 0 scaffold for SEC-01: provider construction / keyring seam regression tests.

Implemented by plan 03-02. Monkeypatches at the `agent86.secrets` module boundary.
"""

from __future__ import annotations

import sys
import types

import pytest

from agent86.cognitive.base import ProviderError, provider_for_model, provider_for_ref
from agent86.config import ProviderConfig, load_config
from agent86.types import ModelRef

pytestmark = pytest.mark.xfail(reason="Wave 0 scaffold — implemented in plan 03-02", strict=False)


def _fake_keyring(monkeypatch, *, store=None, raises=None, backend_module="keyring.backends.SecretService"):
    store = store if store is not None else {}
    mod = types.ModuleType("keyring")
    errors = types.ModuleType("keyring.errors")

    class KeyringError(Exception):
        pass

    class NoKeyringError(KeyringError):
        pass

    class PasswordSetError(KeyringError):
        pass

    class PasswordDeleteError(KeyringError):
        pass

    errors.KeyringError = KeyringError
    errors.NoKeyringError = NoKeyringError
    errors.PasswordSetError = PasswordSetError
    errors.PasswordDeleteError = PasswordDeleteError

    def get_password(service, account):
        if raises:
            raise raises
        return store.get((service, account))

    def set_password(service, account, password):
        store[(service, account)] = password

    def delete_password(service, account):
        if (service, account) not in store:
            raise PasswordDeleteError("not found")
        del store[(service, account)]

    class _Backend:
        pass

    _Backend.__module__ = backend_module

    mod.get_password = get_password
    mod.set_password = set_password
    mod.delete_password = delete_password
    mod.get_keyring = lambda: _Backend()
    mod.errors = errors
    monkeypatch.setitem(sys.modules, "keyring", mod)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors)
    return store


def test_provider_error_message_preserved(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _fake_keyring(monkeypatch)
    with pytest.raises(ProviderError) as exc_info:
        provider_for_model("openai:gpt-4o", load_config())
    assert str(exc_info.value).startswith(
        "No API key found. Set the OPENAI_API_KEY environment variable"
    )


def test_anthropic_error_message_preserved(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _fake_keyring(monkeypatch)
    with pytest.raises(ProviderError) as exc_info:
        provider_for_model("anthropic:claude-opus-4-8", load_config())
    msg = str(exc_info.value)
    if "API key" in msg:
        assert msg.startswith(
            "No Anthropic API key found. Set the ANTHROPIC_API_KEY environment variable"
        )


def test_keyless_provider_ignores_keyring(monkeypatch):
    _fake_keyring(monkeypatch, store={("agent86", "localvllm"): "stray-key"})
    cfg = load_config()
    cfg.providers["localvllm"] = ProviderConfig(base_url="http://localhost:8000/v1")
    provider = provider_for_model("localvllm:m", cfg)
    assert provider._api_key is None


def test_keyring_supplies_key_when_env_absent(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _fake_keyring(monkeypatch, store={("agent86", "openai"): "sk-from-keyring"})
    provider = provider_for_model("openai:gpt-4o", load_config())
    assert provider._api_key == "sk-from-keyring"


def test_custom_section_name_is_the_keyring_account(monkeypatch):
    monkeypatch.delenv("MYVLLM_KEY", raising=False)
    _fake_keyring(
        monkeypatch,
        store={("agent86", "myvllm"): "sk-myvllm", ("agent86", "openai"): "sk-wrong"},
    )
    cfg = load_config()
    cfg.providers["myvllm"] = ProviderConfig(
        api_key_env="MYVLLM_KEY", base_url="https://vllm.example/v1"
    )
    provider = provider_for_model("myvllm:m", cfg)
    assert provider._api_key == "sk-myvllm"


def test_explicit_api_key_argument_wins(monkeypatch):
    def _raise(*a, **k):
        raise AssertionError("must not be called")

    mod = types.ModuleType("keyring")
    mod.get_password = _raise
    monkeypatch.setitem(sys.modules, "keyring", mod)

    provider = provider_for_ref(
        ModelRef.parse("openai:gpt-4o"), load_config(), api_key="sk-injected"
    )
    assert provider._api_key == "sk-injected"
