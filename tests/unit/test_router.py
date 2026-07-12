"""Phase 7 — dynamic model routing (triage)."""

from __future__ import annotations

import pytest

from agent86.cognitive.base import ProviderError, provider_for_model
from agent86.cognitive.llamacpp_provider import LlamaCppProvider
from agent86.cognitive.openai_provider import OpenAIProvider
from agent86.config import ProviderConfig, load_config
from agent86.orchestration.router import ModelRouter, is_simple


def test_is_simple_heuristic():
    assert is_simple("What is the capital of France?")
    assert is_simple("say hi")
    assert not is_simple("Write code to implement a web scraper")
    assert not is_simple("Please refactor and debug this module")
    assert not is_simple("x" * 300)  # too long


def test_router_off_uses_default():
    cfg = load_config()  # router defaults to "off"
    router = ModelRouter(cfg)
    assert not router.enabled
    assert router.select_model("anything at all") == cfg.model.default


def test_router_triage_selects_cheap_or_frontier():
    cfg = load_config()
    cfg.model.router = "triage"
    cfg.model.route.cheap = "ollama:small"
    cfg.model.route.frontier = "anthropic:big"
    router = ModelRouter(cfg)
    assert router.enabled
    assert router.select_model("hello there") == "ollama:small"
    assert router.select_model("refactor and debug this code") == "anthropic:big"


def test_router_forced_provider_disables_routing():
    class Fake:
        model = "fake:m"

    router = ModelRouter(load_config(), forced_provider=Fake())
    assert not router.enabled
    assert router.select_model("refactor code") == "fake:m"
    assert router.provider_for("whatever") is router.forced


def test_factory_builds_new_providers(monkeypatch):
    cfg = load_config()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert isinstance(provider_for_model("openai:gpt-4o", cfg), OpenAIProvider)
    assert isinstance(provider_for_model("llamacpp:qwen2.5", cfg), LlamaCppProvider)


def test_openrouter_default_provider_is_openai_compatible(monkeypatch):
    cfg = load_config()
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    prov = provider_for_model("openrouter:anthropic/claude-3.7-sonnet", cfg)
    assert isinstance(prov, OpenAIProvider)
    # base_url routed to OpenRouter, and the slash-containing model id is preserved
    assert "openrouter.ai" in prov._url
    assert prov.model == "anthropic/claude-3.7-sonnet"


def test_custom_provider_with_base_url_falls_back_to_openai(monkeypatch):
    cfg = load_config()
    cfg.providers["together"] = ProviderConfig(
        api_key_env="TOGETHER_API_KEY", base_url="https://api.together.xyz/v1"
    )
    monkeypatch.setenv("TOGETHER_API_KEY", "test-key")
    assert isinstance(provider_for_model("together:meta-llama/Llama-3-70b", cfg), OpenAIProvider)


def test_keyless_custom_provider_needs_no_key():
    cfg = load_config()
    cfg.providers["localvllm"] = ProviderConfig(base_url="http://localhost:8000/v1")
    # No api_key_env -> keyless local endpoint, must not raise for a missing key.
    assert isinstance(provider_for_model("localvllm:my-model", cfg), OpenAIProvider)


def test_set_forced_pins_router_over_triage(monkeypatch):
    cfg = load_config()
    cfg.model.router = "triage"
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    router = ModelRouter(cfg)
    assert router.enabled
    prov = provider_for_model("openai:gpt-4o", cfg)
    router.set_forced(prov)
    assert not router.enabled  # forcing disables triage
    # both simple and complex tasks now resolve to the pinned provider
    assert router.provider_for(router.select_model("refactor and debug this code")) is prov
    assert router.provider_for(router.select_model("say hi")) is prov


def test_unknown_provider_without_base_url_raises():
    cfg = load_config()
    with pytest.raises(ProviderError, match="Unknown provider"):
        provider_for_model("bogus:model", cfg)
