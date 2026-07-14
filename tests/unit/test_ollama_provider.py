"""Ollama provider — payload options, especially num_ctx (no network)."""

from __future__ import annotations

import json

from agent86.cognitive import ollama_provider as mod
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
