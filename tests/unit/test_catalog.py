"""Wave 0 scaffold for MODEL-01: `agent86.cognitive.catalog` normalization tests.

Implemented by plan 03-04. Monkeypatches `httpx.get` — no real network calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures" / "catalog"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def _patch_get(monkeypatch, payload, capture=None):
    import agent86.cognitive.catalog as catalog

    def fake_get(url, headers=None, timeout=None, **kwargs):
        if capture is not None:
            capture["url"] = url
            capture["headers"] = headers or {}
        return _FakeResponse(payload)

    monkeypatch.setattr(catalog.httpx, "get", fake_get)


def test_openai_normalizes_data_ids(monkeypatch):
    from agent86.cognitive.catalog import fetch_openai_compatible

    _patch_get(monkeypatch, _load("openai_models.json"))
    result = fetch_openai_compatible("https://api.openai.com/v1", "sk-test")
    assert result == [("gpt-4o", "gpt-4o"), ("gpt-4o-mini", "gpt-4o-mini")]


def test_groq_normalizes_like_openai(monkeypatch):
    from agent86.cognitive.catalog import fetch_openai_compatible

    _patch_get(monkeypatch, _load("groq_models.json"))
    result = fetch_openai_compatible("https://api.groq.com/openai/v1", "sk-test")
    assert result == [("llama-3.3-70b-versatile", "llama-3.3-70b-versatile")]


def test_openrouter_normalizes_like_openai(monkeypatch):
    from agent86.cognitive.catalog import fetch_openai_compatible

    _patch_get(monkeypatch, _load("openrouter_models.json"))
    result = fetch_openai_compatible("https://openrouter.ai/api/v1", "sk-test")
    assert result[0][0] == "anthropic/claude-3.7-sonnet"


def test_anthropic_uses_display_name_and_x_api_key_header(monkeypatch):
    from agent86.cognitive.catalog import fetch_anthropic

    capture = {}
    _patch_get(monkeypatch, _load("anthropic_models.json"), capture)
    result = fetch_anthropic("sk-ant-test")
    assert capture["headers"]["x-api-key"] == "sk-ant-test"
    assert capture["headers"]["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in capture["headers"]
    assert result == [("claude-opus-4-20250514", "Claude Opus 4")]


def test_openai_compatible_sends_bearer(monkeypatch):
    from agent86.cognitive.catalog import fetch_openai_compatible

    capture = {}
    _patch_get(monkeypatch, _load("openai_models.json"), capture)
    fetch_openai_compatible("https://api.openai.com/v1", "sk-test")
    assert capture["headers"]["Authorization"] == "Bearer sk-test"


def test_openai_compatible_url_tolerates_missing_v1(monkeypatch):
    from agent86.cognitive.catalog import fetch_openai_compatible

    capture = {}
    _patch_get(monkeypatch, _load("groq_models.json"), capture)
    fetch_openai_compatible("https://api.groq.com/openai/v1", "sk-test")
    assert capture["url"] == "https://api.groq.com/openai/v1/models"

    capture2 = {}
    _patch_get(monkeypatch, _load("groq_models.json"), capture2)
    fetch_openai_compatible("https://api.groq.com/openai", "sk-test")
    assert capture2["url"] == "https://api.groq.com/openai/v1/models"


def test_ollama_uses_api_tags(monkeypatch):
    from agent86.cognitive.catalog import fetch_ollama

    capture = {}
    _patch_get(monkeypatch, _load("ollama_tags.json"), capture)
    result = fetch_ollama("http://localhost:11434")
    assert capture["url"].endswith("/api/tags")
    assert "Authorization" not in capture["headers"]
    assert result == [("llama3.1:8b", "llama3.1:8b")]


def test_fetch_failure_falls_back(monkeypatch):
    import httpx

    import agent86.cognitive.catalog as catalog
    from agent86.config import ProviderConfig

    def fake_get(*a, **k):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(catalog.httpx, "get", fake_get)

    with pytest.raises(catalog.CatalogUnavailable) as exc_info:
        catalog.fetch_catalog(
            "openai", ProviderConfig(base_url="https://api.openai.com/v1"), "k"
        )
    assert "boom" in str(exc_info.value)


def test_llamacpp_has_no_catalog():
    from agent86.cognitive.catalog import CatalogUnavailable, fetch_catalog
    from agent86.config import ProviderConfig

    with pytest.raises(CatalogUnavailable):
        fetch_catalog("llamacpp", ProviderConfig(base_url="http://localhost:8080"), None)
