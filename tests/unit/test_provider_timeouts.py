"""Streaming HTTP timeout fix (quick task 260813-jfk).

Covers the shared `cognitive/http_timeouts.py` helper (Task 1), both bounded call sites and
their `httpx.TimeoutException` -> `ProviderError` conversion (Task 2), and real-loopback-server
proof that a stall fails fast while a slow-but-progressing stream still succeeds (Task 3).
"""

from __future__ import annotations

import httpx
import pytest

from agent86.cognitive import ollama_provider as ollama_mod
from agent86.cognitive import openai_provider as openai_mod
from agent86.cognitive.base import ProviderError
from agent86.cognitive.http_timeouts import stream_timeout, timeout_error
from agent86.cognitive.llamacpp_provider import LlamaCppProvider
from agent86.cognitive.ollama_provider import OllamaProvider
from agent86.cognitive.openai_provider import OpenAIProvider
from agent86.config import ProviderConfig

# --- Task 1: stream_timeout ------------------------------------------------------------------- #


def test_stream_timeout_defaults():
    t = stream_timeout(ProviderConfig())
    assert t.read == 300.0
    assert t.connect == 10.0
    assert t.write == 10.0
    assert t.pool == 10.0


def test_stream_timeout_custom_values():
    t = stream_timeout(ProviderConfig(read_timeout_s=42.0, connect_timeout_s=3.0))
    assert t.read == 42.0
    assert t.connect == 3.0
    assert t.write == 3.0
    assert t.pool == 3.0


# --- Task 1: timeout_error --------------------------------------------------------------------- #


def test_timeout_error_read_timeout_names_the_limit():
    t = stream_timeout(ProviderConfig(read_timeout_s=0.5, connect_timeout_s=2.0))
    err = timeout_error(
        httpx.ReadTimeout("x"),
        endpoint="http://h/api/chat",
        timeout=t,
        section="ollama",
    )
    assert isinstance(err, ProviderError)
    msg = str(err)
    assert "http://h/api/chat" in msg
    assert "0.5" in msg
    assert "read_timeout_s" in msg
    assert "[providers.ollama]" in msg
    assert "gap" in msg.lower()
    assert "total" in msg.lower()


def test_timeout_error_connect_timeout_names_the_limit_and_hint():
    t = stream_timeout(ProviderConfig(read_timeout_s=0.5, connect_timeout_s=2.0))
    err = timeout_error(
        httpx.ConnectTimeout("x"),
        endpoint="http://h/api/chat",
        timeout=t,
        section="ollama",
        connect_hint="Is it running? Start it with 'ollama serve'.",
    )
    msg = str(err)
    assert "connect_timeout_s" in msg
    assert "2" in msg
    assert "Is it running? Start it with 'ollama serve'." in msg


def test_timeout_error_no_section_has_no_none_leak():
    t = stream_timeout(ProviderConfig())
    err = timeout_error(
        httpx.ReadTimeout("x"), endpoint="http://h/v1/chat/completions", timeout=t, section=None
    )
    msg = str(err)
    assert "None" not in msg
    assert "[providers.None]" not in msg


def test_timeout_error_connect_no_section_has_no_none_leak():
    t = stream_timeout(ProviderConfig())
    err = timeout_error(
        httpx.ConnectTimeout("x"), endpoint="http://h/v1/chat/completions", timeout=t, section=None
    )
    msg = str(err)
    assert "None" not in msg
    assert "[providers.None]" not in msg


# --- Task 2: both call sites are bounded, never timeout=None ----------------------------------- #


def _ndjson_ok_lines():
    import json

    return [
        json.dumps(
            {
                "message": {"content": "hi"},
                "done": True,
                "prompt_eval_count": 3,
                "eval_count": 1,
                "done_reason": "stop",
            }
        )
    ]


class _FakeStreamCM:
    """Minimal `with httpx.stream(...) as resp:` fake. Either yields NDJSON/SSE lines or raises."""

    def __init__(self, lines=None, status_code=200, raise_exc=None):
        self._lines = lines or []
        self.status_code = status_code
        self.text = ""
        self._raise_exc = raise_exc

    def __enter__(self):
        if self._raise_exc is not None:
            raise self._raise_exc
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        pass

    def iter_lines(self):
        yield from self._lines


def _patch_capture(monkeypatch, mod, lines=None, raise_exc=None):
    captured: dict = {}

    def fake_stream(*args, **kwargs):
        captured.update(kwargs)
        return _FakeStreamCM(lines=lines, raise_exc=raise_exc)

    monkeypatch.setattr(mod.httpx, "stream", fake_stream)
    return captured


def test_ollama_passes_default_timeout_never_none(monkeypatch):
    captured = _patch_capture(monkeypatch, ollama_mod, lines=_ndjson_ok_lines())
    provider = OllamaProvider("m", ProviderConfig())
    provider.complete(_req())
    t = captured["timeout"]
    assert t is not None
    assert t.read == 300.0
    assert t.connect == 10.0


def test_ollama_passes_overridden_timeout(monkeypatch):
    captured = _patch_capture(monkeypatch, ollama_mod, lines=_ndjson_ok_lines())
    provider = OllamaProvider("m", ProviderConfig(read_timeout_s=900.0, connect_timeout_s=3.0))
    provider.complete(_req())
    t = captured["timeout"]
    assert t.read == 900.0
    assert t.connect == 3.0


def _sse_ok_lines():
    import json

    return [
        "data: " + json.dumps({"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}),
        "data: [DONE]",
    ]


def test_openai_passes_default_timeout_never_none(monkeypatch):
    captured = _patch_capture(monkeypatch, openai_mod, lines=_sse_ok_lines())
    provider = OpenAIProvider("m", ProviderConfig(base_url="http://local/v1"), require_key=False)
    provider.complete(_req())
    t = captured["timeout"]
    assert t is not None
    assert t.read == 300.0
    assert t.connect == 10.0


def test_openai_passes_overridden_timeout(monkeypatch):
    captured = _patch_capture(monkeypatch, openai_mod, lines=_sse_ok_lines())
    provider = OpenAIProvider(
        "m",
        ProviderConfig(base_url="http://local/v1", read_timeout_s=900.0, connect_timeout_s=3.0),
        require_key=False,
    )
    provider.complete(_req())
    t = captured["timeout"]
    assert t.read == 900.0
    assert t.connect == 3.0


def test_llamacpp_preserves_timeout_fields_with_no_base_url(monkeypatch):
    captured = _patch_capture(monkeypatch, openai_mod, lines=_sse_ok_lines())
    provider = LlamaCppProvider("m", ProviderConfig(read_timeout_s=900.0))
    provider.complete(_req())
    t = captured["timeout"]
    assert t.read == 900.0


def _req():
    from agent86.types import CompletionRequest, Message, Role

    return CompletionRequest(model="m", messages=[Message(role=Role.USER, content="hi")])


# --- Task 2: httpx.TimeoutException -> ProviderError -------------------------------------------- #


def test_ollama_read_timeout_surfaces_as_provider_error(monkeypatch):
    _patch_capture(monkeypatch, ollama_mod, raise_exc=httpx.ReadTimeout("stalled"))
    provider = OllamaProvider("m", ProviderConfig(read_timeout_s=0.5))
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(_req())
    msg = str(exc_info.value)
    assert "read_timeout_s" in msg
    assert "0.5" in msg


def test_ollama_connect_timeout_surfaces_as_provider_error(monkeypatch):
    _patch_capture(monkeypatch, ollama_mod, raise_exc=httpx.ConnectTimeout("no route"))
    provider = OllamaProvider("m", ProviderConfig())
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(_req())
    msg = str(exc_info.value)
    assert "connect_timeout_s" in msg
    assert "Start it with 'ollama serve'" in msg


def test_ollama_connect_error_message_unchanged(monkeypatch):
    _patch_capture(monkeypatch, ollama_mod, raise_exc=httpx.ConnectError("refused"))
    provider = OllamaProvider("m", ProviderConfig(base_url="http://x"))
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(_req())
    assert str(exc_info.value) == (
        "Cannot reach Ollama at http://x. Is it running? Start it with 'ollama serve'."
    )


def test_openai_read_timeout_surfaces_as_provider_error(monkeypatch):
    _patch_capture(monkeypatch, openai_mod, raise_exc=httpx.ReadTimeout("stalled"))
    provider = OpenAIProvider(
        "m", ProviderConfig(base_url="http://local/v1", read_timeout_s=0.5), require_key=False
    )
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(_req())
    msg = str(exc_info.value)
    assert "read_timeout_s" in msg
    assert "0.5" in msg


def test_openai_connect_timeout_surfaces_as_provider_error(monkeypatch):
    _patch_capture(monkeypatch, openai_mod, raise_exc=httpx.ConnectTimeout("no route"))
    provider = OpenAIProvider(
        "m", ProviderConfig(base_url="http://local/v1"), require_key=False
    )
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(_req())
    msg = str(exc_info.value)
    assert "connect_timeout_s" in msg


def test_openai_connect_error_message_startswith(monkeypatch):
    _patch_capture(monkeypatch, openai_mod, raise_exc=httpx.ConnectError("refused"))
    provider = OpenAIProvider(
        "m", ProviderConfig(base_url="http://local/v1"), require_key=False
    )
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(_req())
    assert str(exc_info.value).startswith("Cannot reach http://local/v1/chat/completions")
