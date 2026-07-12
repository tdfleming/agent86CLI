"""Phase 7 — dynamic model routing (triage)."""

from __future__ import annotations

from agent86.cognitive.base import provider_for_model
from agent86.cognitive.llamacpp_provider import LlamaCppProvider
from agent86.cognitive.openai_provider import OpenAIProvider
from agent86.config import load_config
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
