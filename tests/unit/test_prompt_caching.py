"""Prompt-cache accounting: the shared ``Usage`` fields every provider reports into."""

from __future__ import annotations

from agent86.types import CompletionRequest, Usage


def test_usage_cache_fields_default_to_zero() -> None:
    """A provider with no cache at all must still produce a valid Usage."""
    usage = Usage(input_tokens=10, output_tokens=3)
    assert usage.cache_read_tokens == 0
    assert usage.cache_creation_tokens == 0


def test_usage_add_accumulates_cache_fields() -> None:
    """Accumulation across steps has to carry the cache breakdown, not drop it."""
    a = Usage(
        input_tokens=100,
        output_tokens=10,
        cost_usd=0.5,
        cache_read_tokens=80,
        cache_creation_tokens=20,
    )
    b = Usage(
        input_tokens=200,
        output_tokens=20,
        cost_usd=1.5,
        cache_read_tokens=150,
        cache_creation_tokens=0,
    )
    total = a + b
    assert total.input_tokens == 300
    assert total.output_tokens == 30
    assert total.cost_usd == 2.0
    assert total.cache_read_tokens == 230
    assert total.cache_creation_tokens == 20


def test_usage_sum_starts_from_empty() -> None:
    """``sum(..., Usage())`` is how the loop folds per-step usage — keep it working."""
    steps = [
        Usage(input_tokens=1, cache_read_tokens=1),
        Usage(input_tokens=2, cache_creation_tokens=4),
    ]
    total = Usage()
    for s in steps:
        total = total + s
    assert (total.cache_read_tokens, total.cache_creation_tokens) == (1, 4)


def test_completion_request_exposes_max_tokens() -> None:
    """The loop feature-detects this field by name; it must exist and default to None."""
    assert "max_tokens" in CompletionRequest.model_fields
    req = CompletionRequest(model="m", messages=[])
    assert req.max_tokens is None
    assert CompletionRequest(model="m", messages=[], max_tokens=512).max_tokens == 512
