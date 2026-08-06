"""Wave 0 scaffold for SEC-01: `agent86.secrets.resolve_api_key` precedence tests.

Implemented by plan 03-02. Monkeypatches at the `agent86.secrets` module boundary —
never touches a real keyring backend (RESEARCH Pitfall 2).
"""

from __future__ import annotations

import sys
import types

import pytest


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


def test_env_wins_over_keyring(monkeypatch):
    from agent86.secrets import resolve_api_key

    monkeypatch.setenv("MY_KEY", "from-env")
    _fake_keyring(monkeypatch, store={("agent86", "anthropic"): "from-keyring"})
    assert resolve_api_key("anthropic", "MY_KEY") == "from-env"


def test_keyring_fallback(monkeypatch):
    from agent86.secrets import resolve_api_key

    monkeypatch.delenv("MY_KEY", raising=False)
    _fake_keyring(monkeypatch, store={("agent86", "anthropic"): "from-keyring"})
    assert resolve_api_key("anthropic", "MY_KEY") == "from-keyring"


def test_keyring_unavailable_silent(monkeypatch):
    from agent86.secrets import resolve_api_key

    monkeypatch.delenv("MY_KEY", raising=False)
    mod = types.ModuleType("keyring")
    errors = types.ModuleType("keyring.errors")

    class KeyringError(Exception):
        pass

    class NoKeyringError(KeyringError):
        pass

    errors.KeyringError = KeyringError
    errors.NoKeyringError = NoKeyringError

    def get_password(service, account):
        raise NoKeyringError("no backend")

    mod.get_password = get_password
    mod.errors = errors
    monkeypatch.setitem(sys.modules, "keyring", mod)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors)

    assert resolve_api_key("anthropic", "MY_KEY") is None


def test_keyring_missing_module_silent(monkeypatch):
    from agent86.secrets import resolve_api_key

    monkeypatch.delenv("MY_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "keyring", None)
    assert resolve_api_key("anthropic", "MY_KEY") is None


def test_no_api_key_env_never_touches_keyring(monkeypatch):
    from agent86.secrets import resolve_api_key

    def _raise(*a, **k):
        raise AssertionError("must not be called")

    mod = types.ModuleType("keyring")
    mod.get_password = _raise
    monkeypatch.setitem(sys.modules, "keyring", mod)

    assert resolve_api_key("ollama", None) is None


def test_keyring_available_false_for_fail_backend(monkeypatch):
    from agent86.secrets import keyring_available

    _fake_keyring(monkeypatch, backend_module="keyring.backends.fail")
    assert keyring_available() is False

    _fake_keyring(monkeypatch, backend_module="keyring.backends.SecretService")
    assert keyring_available() is True


def test_store_and_clear_roundtrip(monkeypatch):
    from agent86.secrets import clear_api_key, has_stored_key, store_api_key

    _fake_keyring(monkeypatch)
    store_api_key("groq", "sk-x")
    assert has_stored_key("groq") is True
    assert clear_api_key("groq") is True
    assert has_stored_key("groq") is False
    assert clear_api_key("groq") is False
