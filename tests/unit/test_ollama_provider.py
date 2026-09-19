"""Ollama provider — payload options, especially num_ctx (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from agent86.cognitive import ollama_provider as mod
from agent86.cognitive.base import ProviderError
from agent86.cognitive.ollama_provider import OllamaProvider
from agent86.config import ProviderConfig, load_config
from agent86.types import CompletionRequest, Message, Role


def _patch_stream(monkeypatch, captured: dict) -> None:
    class Resp:
        status_code = 200
        text = ""

        def iter_lines(self):
            yield json.dumps(
                {"message": {"content": "hi"}, "done": True,
                 "prompt_eval_count": 3, "eval_count": 1, "done_reason": "stop"}
            )

    class CM:
        def __enter__(self):
            return Resp()

        def __exit__(self, *a):
            return False

    def fake_stream(*args, **kwargs):
        captured.update(kwargs)
        return CM()

    monkeypatch.setattr(mod.httpx, "stream", fake_stream)


def _run(provider: OllamaProvider, monkeypatch) -> dict:
    captured: dict = {}
    _patch_stream(monkeypatch, captured)
    provider.complete(
        CompletionRequest(model=provider.model, messages=[Message(role=Role.USER, content="hi")])
    )
    return captured["json"]


def test_num_ctx_is_sent_when_configured(monkeypatch):
    provider = OllamaProvider("qwen3.5:4b", ProviderConfig(num_ctx=8192))
    payload = _run(provider, monkeypatch)
    # Without this, Ollama's small default window truncates responses mid-sentence.
    assert payload["options"]["num_ctx"] == 8192


def test_num_ctx_omitted_when_unset(monkeypatch):
    provider = OllamaProvider("qwen3.5:4b", ProviderConfig())  # no num_ctx
    payload = _run(provider, monkeypatch)
    assert "num_ctx" not in payload["options"]


def test_default_config_gives_ollama_a_context_window():
    # The shipped default sets a generous num_ctx so tool observations don't crowd out output.
    assert load_config().providers["ollama"].num_ctx == 8192


# --------------------------------------------------------------------------- #
# v0.8 — max_tokens (num_predict), usage, and the normalized stop_reason
# --------------------------------------------------------------------------- #


def test_request_max_tokens_becomes_num_predict(monkeypatch):
    provider = OllamaProvider("qwen3.5:4b", ProviderConfig())
    captured: dict = {}
    _patch_stream(monkeypatch, captured)
    provider.complete(
        CompletionRequest(model=provider.model, messages=[], max_tokens=256)
    )
    assert captured["json"]["options"]["num_predict"] == 256


def test_provider_config_max_tokens_used_when_request_is_silent(monkeypatch):
    config = ProviderConfig(max_tokens=999)
    provider = OllamaProvider("qwen3.5:4b", config)
    payload = _run(provider, monkeypatch)
    assert payload["options"]["num_predict"] == 999


def test_request_max_tokens_beats_provider_config(monkeypatch):
    config = ProviderConfig(max_tokens=999)
    provider = OllamaProvider("qwen3.5:4b", config)
    captured: dict = {}
    _patch_stream(monkeypatch, captured)
    provider.complete(CompletionRequest(model=provider.model, messages=[], max_tokens=32))
    assert captured["json"]["options"]["num_predict"] == 32


def test_num_predict_omitted_when_no_cap_is_asked_for(monkeypatch):
    # Ollama's own default is "generate until the model stops"; inventing a ceiling for
    # someone's local hardware would truncate answers that run free today.
    provider = OllamaProvider("qwen3.5:4b", ProviderConfig())
    payload = _run(provider, monkeypatch)
    assert "num_predict" not in payload["options"]


def test_token_counts_land_in_usage(monkeypatch):
    provider = OllamaProvider("qwen3.5:4b", ProviderConfig())
    _patch_stream(monkeypatch, {})
    completion = provider.complete(
        CompletionRequest(model=provider.model, messages=[Message(role=Role.USER, content="hi")])
    )
    assert completion.usage.input_tokens == 3  # prompt_eval_count
    assert completion.usage.output_tokens == 1  # eval_count
    assert completion.usage.cost_usd == 0.0  # local inference really is free
    assert completion.usage.cache_read_tokens == 0
    assert completion.usage.cache_creation_tokens == 0


def test_done_reason_stop_normalizes_to_end_turn(monkeypatch):
    provider = OllamaProvider("qwen3.5:4b", ProviderConfig())
    _patch_stream(monkeypatch, {})
    completion = provider.complete(CompletionRequest(model=provider.model, messages=[]))
    assert completion.stop_reason == "end_turn"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stop", "end_turn"),
        ("length", "max_tokens"),
        ("load", "other"),
        ("something-new", "other"),
        (None, None),
    ],
)
def test_done_reason_normalization_table(raw, expected):
    assert mod.normalize_stop_reason(raw) == expected


def test_tool_calls_override_a_plain_stop():
    # Ollama says "stop" even when it emitted tool calls; the turn is not over.
    assert mod.normalize_stop_reason("stop", has_tool_calls=True) == "tool_use"
    assert mod.normalize_stop_reason(None, has_tool_calls=True) == "tool_use"
    # ...but a truncated turn is still truncated, whatever it emitted.
    assert mod.normalize_stop_reason("length", has_tool_calls=True) == "max_tokens"


def _patch_lines(monkeypatch, lines, error=None):
    class Resp:
        status_code = 200
        text = ""

        def iter_lines(self):
            yield from lines
            if error is not None:
                raise error

    class CM:
        def __enter__(self):
            return Resp()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mod.httpx, "stream", lambda *a, **k: CM())


def test_malformed_ndjson_line_becomes_provider_error(monkeypatch):
    # A truncated NDJSON line used to escape as a bare json.JSONDecodeError.
    _patch_lines(monkeypatch, [json.dumps({"message": {"content": "hi"}}), "{oops"])
    provider = OllamaProvider("qwen3.5:4b", ProviderConfig())
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(CompletionRequest(model=provider.model, messages=[]))
    message = str(excinfo.value)
    assert "malformed NDJSON" in message
    assert "qwen3.5:4b" in message


def test_transport_failure_mid_stream_becomes_provider_error(monkeypatch):
    _patch_lines(
        monkeypatch,
        [json.dumps({"message": {"content": "hi"}})],
        error=httpx.RemoteProtocolError("peer closed connection"),
    )
    provider = OllamaProvider("qwen3.5:4b", ProviderConfig())
    with pytest.raises(ProviderError, match="RemoteProtocolError"):
        provider.complete(CompletionRequest(model=provider.model, messages=[]))
