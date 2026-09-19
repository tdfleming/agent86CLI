"""v0.7 — the cost meter is real: price lookup, overrides, and unknown-vs-free.

Before this, ``PRICES`` was an empty dict, so every call cost ``$0.00`` and
``limits.max_cost_usd`` could never trip. These tests pin the three outcomes the rest of the
harness depends on: a known price, a *free* local price, and an *unknown* price (``None``).
"""

from __future__ import annotations

import pytest

from agent86.cognitive import pricing


@pytest.fixture(autouse=True)
def _clean_overrides():
    """Config overrides live in module state; don't let one test leak into the next."""
    pricing.set_overrides(None)
    yield
    pricing.set_overrides(None)


# ---- lookup ------------------------------------------------------------ #


def test_lookup_exact_bare_model_id():
    price = pricing.lookup("claude-opus-4-8")
    assert price is not None
    assert (price.input_per_mtok, price.output_per_mtok) == (5.00, 25.00)
    assert price.source == "builtin"


def test_lookup_exact_provider_qualified_ref():
    assert pricing.lookup("anthropic:claude-sonnet-5") == pricing.lookup("claude-sonnet-5")


def test_lookup_dated_snapshot_resolves_by_prefix():
    base = pricing.lookup("claude-sonnet-5")
    assert pricing.lookup("claude-sonnet-5-20260101") == base
    assert pricing.lookup("anthropic:claude-sonnet-5-20260101") == base
    # Vertex spells the snapshot with '@'.
    assert pricing.lookup("claude-sonnet-5@20260101") == base


def test_prefix_match_does_not_leak_across_version_families():
    """``gpt-5.6-sol`` must not be priced off the ``gpt-5`` entry."""
    assert pricing.lookup("gpt-5.6-sol") != pricing.lookup("gpt-5")
    # A hypothetical unlisted point release stays unknown rather than borrowing gpt-5's price.
    assert pricing.lookup("gpt-5.9-nova") is None


def test_lookup_unknown_model_is_none():
    assert pricing.lookup("mystery:model-x") is None
    assert pricing.lookup("") is None
    # Groq / OpenRouter are deliberately unpriced.
    assert pricing.lookup("openrouter:anthropic/claude-3.7-sonnet") is None


def test_local_providers_are_free_not_unknown():
    for ref in ("ollama:qwen2.5:3b", "llamacpp:some-gguf", "ollama:anything-at-all"):
        price = pricing.lookup(ref)
        assert price is not None, ref
        assert price.is_local
        assert price.cost(1_000_000, 1_000_000) == 0.0
    # ...but the bare model id, with no provider, is genuinely unknown.
    assert pricing.lookup("qwen2.5:3b") is None


def test_is_priced():
    assert pricing.is_priced("anthropic:claude-opus-5")
    assert pricing.is_priced("ollama:llama3.1")  # free counts as priced
    assert not pricing.is_priced("groq:llama-3.3-70b-versatile")


# ---- estimate_cost / priced_usage -------------------------------------- #


def test_estimate_cost_known_model():
    # claude-opus-5 is $5/$25 per Mtok.
    assert pricing.estimate_cost("claude-opus-5", 1_000_000, 1_000_000) == pytest.approx(30.0)
    assert pricing.estimate_cost("claude-opus-5", 500_000, 0) == pytest.approx(2.5)


def test_estimate_cost_unknown_is_none_not_zero():
    assert pricing.estimate_cost("mystery-model", 1_000_000, 1_000_000) is None


def test_estimate_cost_local_is_zero():
    assert pricing.estimate_cost("ollama:llama3.1", 1_000_000, 1_000_000) == 0.0


def test_priced_usage_keeps_cost_usd_a_float():
    known = pricing.priced_usage("claude-sonnet-5", 1_000_000, 0)
    assert isinstance(known.cost_usd, float)
    assert known.cost_usd == pytest.approx(2.0)

    unknown = pricing.priced_usage("mystery-model", 1_000_000, 1_000_000)
    assert unknown.cost_usd == 0.0  # Usage stays a plain float...
    assert not pricing.is_priced("mystery-model")  # ...ask is_priced before believing it


def test_price_table_is_populated():
    """Regression guard: an empty table silently disables limits.max_cost_usd."""
    assert len(pricing.PRICES) > 10
    assert all(p.input_per_mtok > 0 and p.output_per_mtok > 0 for p in pricing.PRICES.values())
