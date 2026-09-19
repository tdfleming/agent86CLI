"""Model price table and cost estimation (Tier 5 operational guardrail input).

Prices are USD per million tokens (input, output). Three outcomes are deliberately distinct:

* **priced**   — a built-in or configured rate exists; :func:`estimate_cost` returns dollars.
* **local**    — Ollama / llama.cpp run on the user's own hardware, so ``0.0`` is the *correct*
  cost, not a missing one (``Price.source == "local"``).
* **unknown**  — no rate is known; :func:`lookup` returns ``None`` and :func:`estimate_cost`
  returns ``None`` so the UI can say "cost n/a" instead of a fabricated ``$0.00``.

That distinction is what makes ``limits.max_cost_usd`` a real circuit breaker: before this
table existed every call cost ``0.0``, so the cost cap could never trip.

Resolution order in :func:`lookup` (first hit wins):

1. config overrides (``[pricing.models]``, see :class:`agent86.config.PricingConfig`)
2. local providers (``ollama:`` / ``llamacpp:``) -> free
3. the built-in :data:`PRICES` table

Each step tries the full ``provider:model`` ref, then the bare model id, then a dated-snapshot
prefix match so ``claude-sonnet-5-20260101`` resolves to ``claude-sonnet-5``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from agent86.types import Usage


@dataclass(frozen=True)
class Price:
    """USD per million tokens for one model.

    ``source`` records provenance so callers can distinguish a genuinely free local model
    from a configured or built-in rate: ``"builtin"``, ``"local"``, or ``"config"``.
    """

    input_per_mtok: float
    output_per_mtok: float
    source: str = "builtin"

    @property
    def is_local(self) -> bool:
        return self.source == "local"

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens / 1_000_000) * self.input_per_mtok + (
            output_tokens / 1_000_000
        ) * self.output_per_mtok


#: Providers whose models run on the user's own hardware. Zero is the real price.
LOCAL_PROVIDERS = frozenset({"ollama", "llamacpp", "llama.cpp", "local"})

#: The free rate handed out for :data:`LOCAL_PROVIDERS`.
LOCAL_PRICE = Price(0.0, 0.0, source="local")

# --------------------------------------------------------------------------- #
# Built-in price table — keyed by *bare* model id (what providers report as
# ``ModelProvider.model``). Dated snapshots resolve by prefix, so only the base id is listed.
#
# Anthropic: from the bundled ``claude-api`` skill's model table (cached 2026-06-24).
# OpenAI:    https://developers.openai.com/api/docs/pricing, fetched 2026-09-19.
# Groq and OpenRouter are intentionally absent: OpenRouter ids are ``vendor/model`` with
# per-route pricing we cannot verify from the id alone, and Groq publishes per-model rates
# that change often. Unknown beats wrong — an absent model shows "cost n/a".
# --------------------------------------------------------------------------- #
PRICES: dict[str, Price] = {
    # -- Anthropic ---------------------------------------------------------- #
    "claude-fable-5-1": Price(10.00, 50.00),
    "claude-mythos-5-1": Price(10.00, 50.00),
    "claude-fable-5": Price(10.00, 50.00),
    "claude-opus-5": Price(5.00, 25.00),
    "claude-opus-4-8": Price(5.00, 25.00),
    "claude-opus-4-7": Price(5.00, 25.00),
    "claude-opus-4-6": Price(5.00, 25.00),
    "claude-sonnet-5": Price(2.00, 10.00),
    "claude-sonnet-4-6": Price(3.00, 15.00),
    "claude-haiku-4-5": Price(1.00, 5.00),
    # -- OpenAI ------------------------------------------------------------- #
    "gpt-6-astra": Price(10.00, 50.00),
    "gpt-5.6-sol": Price(4.00, 20.00),
    "gpt-5.6-terra": Price(2.00, 12.00),
    "gpt-5.6-luna": Price(0.20, 1.20),
    "gpt-5.5": Price(5.00, 30.00),
    "gpt-5.5-pro": Price(30.00, 180.00),
    "gpt-5.4": Price(2.50, 15.00),
    "gpt-5.4-mini": Price(0.75, 4.50),
    "gpt-5.4-nano": Price(0.20, 1.25),
    "gpt-5.4-pro": Price(30.00, 180.00),
    "gpt-5.2": Price(1.75, 14.00),
    "gpt-5.2-pro": Price(21.00, 168.00),
    "gpt-5.1": Price(1.25, 10.00),
    "gpt-5": Price(1.25, 10.00),
    "gpt-5-mini": Price(0.25, 2.00),
    "gpt-5-nano": Price(0.05, 0.40),
    "gpt-5-pro": Price(15.00, 120.00),
    "gpt-4.1": Price(2.00, 8.00),
    "gpt-4.1-mini": Price(0.40, 1.60),
    "gpt-4.1-nano": Price(0.10, 0.40),
    "gpt-4o": Price(2.50, 10.00),
    "gpt-4o-mini": Price(0.15, 0.60),
    "o1": Price(15.00, 60.00),
    "o1-pro": Price(150.00, 600.00),
    "o3": Price(2.00, 8.00),
    "o3-pro": Price(20.00, 80.00),
    "o3-mini": Price(1.10, 4.40),
    "o4-mini": Price(1.10, 4.40),
    "gpt-3.5-turbo": Price(0.50, 1.50),
}

#: Config-supplied overrides, published by :class:`agent86.config.Config` (see
#: :func:`set_overrides`). Module-level because providers reach :func:`priced_usage`
#: with no access to the resolved ``Config``.
_OVERRIDES: dict[str, Price] = {}

#: A dated snapshot suffix: ``-20260101``, ``@20251101`` (Vertex), ``_20260101``.
#: Prefix matching is restricted to *this* shape on purpose — a loose "longest prefix"
#: would price ``gpt-5.6-sol`` off the ``gpt-5`` entry, which is simply wrong.
_SNAPSHOT_RE = re.compile(r"^[-@_]20\d{6}$")


def set_overrides(overrides: Mapping[str, Price] | None) -> None:
    """Install per-model config overrides (``None`` or ``{}`` clears them).

    Called from :class:`agent86.config.Config`'s post-validation hook so that any resolved
    config — however it was built — is reflected here before the first model call.
    """
    _OVERRIDES.clear()
    if overrides:
        _OVERRIDES.update(overrides)


def _candidates(model: str) -> list[str]:
    """``"anthropic:claude-opus-5"`` -> ``["anthropic:claude-opus-5", "claude-opus-5"]``."""
    ref = (model or "").strip()
    if not ref:
        return []
    out = [ref]
    provider, sep, rest = ref.partition(":")
    if sep and rest and provider:
        out.append(rest)
    return out


def _provider_of(model: str) -> str:
    provider, sep, rest = (model or "").strip().partition(":")
    return provider.lower() if sep and rest else ""


def _match(table: Mapping[str, Price], model: str) -> Price | None:
    candidates = _candidates(model)
    for cand in candidates:
        hit = table.get(cand)
        if hit is not None:
            return hit
    # Dated-snapshot prefix match; longest key wins so "claude-opus-4-8-20260101" cannot be
    # claimed by a shorter key that happens to also match.
    best: tuple[int, Price] | None = None
    for cand in candidates:
        for key, price in table.items():
            if len(key) < len(cand) and cand.startswith(key):
                if _SNAPSHOT_RE.match(cand[len(key) :]) and (best is None or len(key) > best[0]):
                    best = (len(key), price)
    return best[1] if best else None


def lookup(model: str) -> Price | None:
    """Resolve a price for a ``provider:model`` ref or bare model id, or ``None`` if unknown."""
    override = _match(_OVERRIDES, model)
    if override is not None:
        return override
    if _provider_of(model) in LOCAL_PROVIDERS:
        return LOCAL_PRICE
    return _match(PRICES, model)


def is_priced(model: str) -> bool:
    """True when a cost figure for ``model`` is meaningful (including free local models)."""
    return lookup(model) is not None


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate USD cost for a call, or ``None`` when the model's price is unknown.

    ``None`` — not ``0.0`` — is what lets the status line say "cost n/a" instead of
    implying a call was free.
    """
    price = lookup(model)
    return None if price is None else price.cost(input_tokens, output_tokens)


def priced_usage(model: str, input_tokens: int, output_tokens: int) -> Usage:
    """Build a :class:`Usage` with cost filled in from the price table.

    ``Usage.cost_usd`` is a plain float (shared type, provider-agnostic), so an unknown
    model contributes ``0.0`` to the running total; ask :func:`is_priced` before *displaying*
    that total so an unpriced model reads as "n/a" rather than "$0.00".
    """
    cost = estimate_cost(model, input_tokens, output_tokens)
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost if cost is not None else 0.0,
    )


__all__ = [
    "LOCAL_PRICE",
    "LOCAL_PROVIDERS",
    "PRICES",
    "Price",
    "estimate_cost",
    "is_priced",
    "lookup",
    "priced_usage",
    "set_overrides",
]
