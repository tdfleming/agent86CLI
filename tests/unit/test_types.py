"""Phase 1 — shared types."""

from __future__ import annotations

import pytest

from agent86.types import ModelRef, Usage


@pytest.mark.parametrize(
    "ref,provider,model",
    [
        ("anthropic:claude-opus-4-8", "anthropic", "claude-opus-4-8"),
        ("ollama:llama3.1", "ollama", "llama3.1"),
        ("openai: gpt-4o ", "openai", "gpt-4o"),
    ],
)
def test_modelref_parse(ref, provider, model):
    parsed = ModelRef.parse(ref)
    assert parsed.provider == provider
    assert parsed.model == model
    assert str(parsed) == f"{provider}:{model}"


@pytest.mark.parametrize("bad", ["noseparator", ":model", "provider:", "  :  "])
def test_modelref_rejects_bad(bad):
    with pytest.raises(ValueError):
        ModelRef.parse(bad)


def test_usage_adds():
    total = Usage(input_tokens=10, output_tokens=5, cost_usd=0.1) + Usage(
        input_tokens=3, output_tokens=2, cost_usd=0.05
    )
    assert total.input_tokens == 13
    assert total.output_tokens == 7
    assert round(total.cost_usd, 2) == 0.15
