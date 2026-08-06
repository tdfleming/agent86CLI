"""UAT gap 3 closure: a stale/incompatible `anthropic` SDK must produce a one-line actionable
`ProviderError` naming the fix — never an opaque `TypeError` from inside httpx — and `run_repl`
must degrade to "Cannot start:" instead of dumping a traceback (which is also the vector for the
gap-2 key leak).

Task 1 (tests 1-6): the version guard in `AnthropicProvider.__init__` itself.
Task 2 (tests 7-10): the guard proven end-to-end through `run_repl`.
"""

from __future__ import annotations

import io

import anthropic
import pytest
from rich.console import Console

from agent86.cognitive.anthropic_provider import AnthropicProvider
from agent86.cognitive.base import ProviderError
from agent86.config import ProviderConfig, load_config

_PCONF = ProviderConfig(api_key_env="ANTHROPIC_API_KEY")


class _RecordingClient:
    """Stand-in for `anthropic.Anthropic` that records whether it was ever constructed."""

    calls: list[dict] = []

    def __init__(self, **kwargs):
        _RecordingClient.calls.append(kwargs)


@pytest.fixture(autouse=True)
def _reset_recording():
    _RecordingClient.calls = []
    yield
    _RecordingClient.calls = []


# --------------------------------------------------------------------------- #
# Task 1: the version guard
# --------------------------------------------------------------------------- #


def test_stale_version_raises_actionable_provider_error(monkeypatch):
    monkeypatch.setattr(anthropic, "__version__", "0.25.9", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-TESTKEY-0001")
    with pytest.raises(ProviderError) as exc_info:
        AnthropicProvider(model="claude-opus-5", config=_PCONF)
    msg = str(exc_info.value)
    assert "0.25.9" in msg
    assert "0.40" in msg
    assert 'pip install -U "anthropic>=0.40"' in msg


def test_stale_version_never_constructs_client(monkeypatch):
    monkeypatch.setattr(anthropic, "__version__", "0.25.9", raising=False)
    monkeypatch.setattr(anthropic, "Anthropic", _RecordingClient, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-TESTKEY-0001")
    with pytest.raises(ProviderError):
        AnthropicProvider(model="claude-opus-5", config=_PCONF)
    assert _RecordingClient.calls == []


def test_current_installed_version_constructs_normally(monkeypatch):
    monkeypatch.setattr(anthropic, "__version__", "0.120.2", raising=False)
    monkeypatch.setattr(anthropic, "Anthropic", _RecordingClient, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-TESTKEY-0001")
    provider = AnthropicProvider(model="claude-opus-5", config=_PCONF)
    assert provider.model == "claude-opus-5"
    assert len(_RecordingClient.calls) == 1


def test_missing_version_attribute_does_not_block_startup(monkeypatch):
    monkeypatch.delattr(anthropic, "__version__", raising=False)
    monkeypatch.setattr(anthropic, "Anthropic", _RecordingClient, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-TESTKEY-0001")
    provider = AnthropicProvider(model="claude-opus-5", config=_PCONF)
    assert provider.model == "claude-opus-5"
    assert len(_RecordingClient.calls) == 1


def test_non_numeric_prerelease_suffix_tolerated(monkeypatch):
    monkeypatch.setattr(anthropic, "__version__", "1.0.0b1", raising=False)
    monkeypatch.setattr(anthropic, "Anthropic", _RecordingClient, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-TESTKEY-0001")
    provider = AnthropicProvider(model="claude-opus-5", config=_PCONF)
    assert provider.model == "claude-opus-5"
    assert len(_RecordingClient.calls) == 1


def test_missing_package_path_unchanged(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _failing_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("simulated missing anthropic package")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _failing_import)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-TESTKEY-0001")
    with pytest.raises(ProviderError) as exc_info:
        AnthropicProvider(model="claude-opus-5", config=_PCONF)
    assert str(exc_info.value) == (
        "The 'anthropic' package is not installed. Install it with:\n"
        '    pip install "agent86[anthropic]"'
    )


# --------------------------------------------------------------------------- #
# Task 2: end-to-end through run_repl — fails soft, never a traceback
# --------------------------------------------------------------------------- #


def _cfg():
    cfg = load_config()
    cfg.model.default = "anthropic:claude-opus-5"
    cfg.providers["anthropic"] = ProviderConfig(api_key_env="ANTHROPIC_API_KEY")
    return cfg


def _capture_console(monkeypatch):
    import agent86.ui.repl as repl_mod

    buf = io.StringIO()
    monkeypatch.setattr(repl_mod, "console", Console(file=buf, width=200))
    return repl_mod, buf


def test_run_repl_fails_soft_on_opaque_typeerror(monkeypatch):
    import agent86.ui.repl as repl_mod

    repl_mod, buf = _capture_console(monkeypatch)
    monkeypatch.setenv("AGENT86_PLAIN", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-TESTKEY-0001")

    def _raise_typeerror(self, model, config, api_key=None):  # noqa: ANN001
        raise TypeError("Client.__init__() got an unexpected keyword argument 'proxies'")

    monkeypatch.setattr(AnthropicProvider, "__init__", _raise_typeerror)

    repl_mod.run_repl(_cfg())  # must not raise

    output = buf.getvalue()
    assert "Cannot start:" in output
    # gap-2 cross-check: the resolved key must never reach visible output either.
    assert "sk-ant-TESTKEY-0001" not in output


def test_run_repl_typeerror_output_has_no_traceback(monkeypatch):
    repl_mod, buf = _capture_console(monkeypatch)
    monkeypatch.setenv("AGENT86_PLAIN", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-TESTKEY-0001")

    def _raise_typeerror(self, model, config, api_key=None):  # noqa: ANN001
        raise TypeError("Client.__init__() got an unexpected keyword argument 'proxies'")

    monkeypatch.setattr(AnthropicProvider, "__init__", _raise_typeerror)

    repl_mod.run_repl(_cfg())  # must not raise

    output = buf.getvalue()
    assert "Traceback (most recent call last)" not in output


def test_run_repl_stale_sdk_reports_upgrade_command(monkeypatch):
    repl_mod, buf = _capture_console(monkeypatch)
    monkeypatch.setenv("AGENT86_PLAIN", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-TESTKEY-0001")
    monkeypatch.setattr(anthropic, "__version__", "0.25.9", raising=False)

    repl_mod.run_repl(_cfg())  # must not raise

    output = buf.getvalue()
    assert 'pip install -U "anthropic>=0.40"' in output
    assert "Traceback (most recent call last)" not in output


def test_run_repl_stale_sdk_never_dumps_traceback_or_key(monkeypatch):
    repl_mod, buf = _capture_console(monkeypatch)
    monkeypatch.setenv("AGENT86_PLAIN", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-TESTKEY-0001")
    monkeypatch.setattr(anthropic, "__version__", "0.25.9", raising=False)

    repl_mod.run_repl(_cfg())  # must not raise

    output = buf.getvalue()
    assert "Cannot start:" in output
    assert "sk-ant-TESTKEY-0001" not in output
    assert "Traceback (most recent call last)" not in output
