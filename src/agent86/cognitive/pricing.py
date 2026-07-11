"""Best-effort cost estimation for the cost meter (Tier 5 operational guardrail input).

Prices are USD per million tokens (input, output). The table is intentionally small and
conservative: when a model is not listed, :func:`estimate_cost` returns ``0.0`` rather than
guessing, so the cost meter never shows a fabricated number. Override or extend
``PRICES`` as needed (a future phase can source this from config).
"""

from __future__ import annotations

from agent86.types import Usage

# model id -> (input $/Mtok, output $/Mtok). Local models (Ollama/llama.cpp) are free.
PRICES: dict[str, tuple[float, float]] = {}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a call, or 0.0 if the model's price is unknown/local."""
    price = PRICES.get(model)
    if price is None:
        return 0.0
    in_rate, out_rate = price
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


def priced_usage(model: str, input_tokens: int, output_tokens: int) -> Usage:
    """Build a :class:`Usage` with cost filled in from the price table."""
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=estimate_cost(model, input_tokens, output_tokens),
    )


__all__ = ["PRICES", "estimate_cost", "priced_usage"]
