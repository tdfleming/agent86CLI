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


# ---- cache-aware pricing (v0.8) ---------------------------------------- #


def test_cache_counts_default_to_the_old_arithmetic():
    # Every provider without a prompt cache passes zeros; the result must be unchanged.
    plain = pricing.estimate_cost("claude-opus-5", 1_000_000, 1_000_000)
    explicit = pricing.estimate_cost("claude-opus-5", 1_000_000, 1_000_000, 0, 0)
    assert plain == explicit == pytest.approx(5.00 + 25.00)


def test_cache_reads_are_a_tenth_of_the_input_rate():
    # A fully-cached million-token prompt on a $5/MTok model: $0.50, not $5.00.
    cost = pricing.estimate_cost("claude-opus-5", 1_000_000, 0, 1_000_000, 0)
    assert cost == pytest.approx(0.50)


def test_cache_writes_carry_the_five_minute_premium():
    cost = pricing.estimate_cost("claude-opus-5", 1_000_000, 0, 0, 1_000_000)
    assert cost == pytest.approx(5.00 * 1.25)


def test_uncached_remainder_is_billed_at_the_full_input_rate():
    # 1M prompt = 600k cache read + 200k cache write + 200k uncached, plus 100k output.
    cost = pricing.estimate_cost("claude-opus-5", 1_000_000, 100_000, 600_000, 200_000)
    expected = (
        0.2 * 5.00  # uncached input
        + 0.6 * 0.50  # cache reads at 0.1x
        + 0.2 * 6.25  # cache writes at 1.25x
        + 0.1 * 25.00  # output
    )
    assert cost == pytest.approx(expected)


def test_caching_beats_not_caching_for_the_same_prompt():
    # The whole point: the second identical turn must cost less than the first.
    uncached = pricing.estimate_cost("claude-opus-5", 100_000, 0)
    cached = pricing.estimate_cost("claude-opus-5", 100_000, 0, 100_000, 0)
    assert cached < uncached


def test_fable_5_1_reads_at_its_own_cheaper_rate():
    # $0.25/MTok against a $10 input rate — 0.025x, not the usual 0.1x.
    cost = pricing.estimate_cost("claude-fable-5-1", 1_000_000, 0, 1_000_000, 0)
    assert cost == pytest.approx(0.25)
    # The dated-snapshot form resolves the same way.
    assert pricing.estimate_cost(
        "anthropic:claude-fable-5-1-20260701", 1_000_000, 0, 1_000_000, 0
    ) == pytest.approx(0.25)


def test_mythos_5_1_keeps_the_standard_read_rate():
    # Its cache rate was open at launch; over-charging an estimate beats under-charging a
    # cost circuit breaker.
    cost = pricing.estimate_cost("claude-mythos-5-1", 1_000_000, 0, 1_000_000, 0)
    assert cost == pytest.approx(1.00)


def test_local_models_are_still_free_with_cache_counts():
    assert pricing.estimate_cost("ollama:qwen3.5:4b", 1_000_000, 1_000, 500, 500) == 0.0


def test_unknown_model_is_still_none_with_cache_counts():
    assert pricing.estimate_cost("who-is-this", 1_000, 10, 5, 5) is None


def test_is_priced_and_lookup_are_unaffected():
    assert pricing.is_priced("claude-opus-5")
    assert pricing.is_priced("ollama:anything")
    assert not pricing.is_priced("who-is-this")
    assert pricing.lookup("who-is-this") is None


def test_cache_counts_larger_than_the_prompt_never_go_negative():
    # Defensive: a provider reporting inconsistent counts must not produce a credit.
    assert pricing.estimate_cost("claude-opus-5", 10, 0, 1_000, 0) >= 0.0


def test_priced_usage_carries_the_cache_breakdown():
    usage = pricing.priced_usage("claude-opus-5", 1_000_000, 0, 600_000, 200_000)
    assert usage.input_tokens == 1_000_000
    assert usage.cache_read_tokens == 600_000
    assert usage.cache_creation_tokens == 200_000
    assert usage.cost_usd == pytest.approx(0.2 * 5.00 + 0.6 * 0.50 + 0.2 * 6.25)


def test_priced_usage_without_cache_is_byte_for_byte_the_old_behaviour():
    usage = pricing.priced_usage("gpt-4o", 1000, 100)
    assert usage.cache_read_tokens == 0
    assert usage.cache_creation_tokens == 0
    assert usage.cost_usd == pytest.approx(pricing.estimate_cost("gpt-4o", 1000, 100))


def test_config_override_prices_its_cache_off_the_overridden_input_rate():
    pricing.set_overrides({"my-model": pricing.Price(100.0, 200.0, source="config")})
    cost = pricing.estimate_cost("my-model", 1_000_000, 0, 1_000_000, 0)
    assert cost == pytest.approx(10.0)  # 0.1 x 100


def test_an_explicit_cache_rate_wins_over_the_multiplier():
    pricing.set_overrides(
        {
            "my-model": pricing.Price(
                100.0, 200.0, source="config", cache_read_per_mtok=1.0, cache_write_per_mtok=2.0
            )
        }
    )
    assert pricing.estimate_cost("my-model", 1_000_000, 0, 1_000_000, 0) == pytest.approx(1.0)
    assert pricing.estimate_cost("my-model", 1_000_000, 0, 0, 1_000_000) == pytest.approx(2.0)
