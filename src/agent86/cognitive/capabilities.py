"""Per-model API capability facts (Tier 3).

Some models REMOVE request parameters rather than defaulting them. Anthropic removed
`temperature`, `top_p`, and `top_k` on Claude Opus 5, Opus 4.8, Opus 4.7, Sonnet 5, and
Fable 5: sending any of them returns HTTP 400, there is no replacement value, and behaviour
is steered by prompting instead. The parameter must be omitted entirely.

This module is the single seam every provider asks, so the fix lives in one place. It has two
mechanisms deliberately:

1. `_NO_SAMPLING_FAMILIES` — the declarative list of model families known to have removed
   them, matched by prefix so dated ids (`claude-opus-5-20260101`) and aliases
   (`claude-opus-5-latest`) are covered.
2. `mark_sampling_unsupported` — a session-scoped learned set a provider populates when the
   API itself rejects a sampling parameter. A model released after this list was written
   therefore self-corrects after one rejected request instead of failing forever.
"""

from __future__ import annotations

from typing import Any

#: The request parameters that were removed together.
SAMPLING_PARAMS: tuple[str, ...] = ("temperature", "top_p", "top_k")

#: Model-id prefixes (provider prefix stripped, lowercased) that reject SAMPLING_PARAMS.
_NO_SAMPLING_FAMILIES: tuple[str, ...] = (
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
    "claude-fable-5",
    "fable-5",
)

#: Learned at runtime from a real 400. Session-scoped: no disk cache, no TTL (mirrors D-04).
_LEARNED_NO_SAMPLING: set[str] = set()

#: Words an API uses when it refuses a parameter outright.
_REJECTION_WORDS: tuple[str, ...] = (
    "deprecat",
    "unsupported",
    "not supported",
    "not permitted",
    "unexpected",
    "removed",
    "cannot be used",
    "no longer",
)


def normalize_model(model: str) -> str:
    """Strip a `provider:` prefix and lowercase. Suffixes are left for prefix matching."""
    ident = model.split(":", 1)[1] if ":" in model else model
    return ident.strip().lower()


def supports_sampling_params(model: str) -> bool:
    """False when `model` rejects temperature/top_p/top_k and they must be omitted."""
    ident = normalize_model(model)
    if ident in _LEARNED_NO_SAMPLING:
        return False
    return not any(ident.startswith(family) for family in _NO_SAMPLING_FAMILIES)


def mark_sampling_unsupported(model: str) -> None:
    """Record, for this session, that `model` rejected a sampling parameter."""
    _LEARNED_NO_SAMPLING.add(normalize_model(model))


def is_sampling_rejection(message: str) -> bool:
    """True when an API error text says a sampling parameter was refused."""
    low = message.lower()
    return any(p in low for p in SAMPLING_PARAMS) and any(
        w in low for w in _REJECTION_WORDS
    )


def apply_sampling_params(
    kwargs: dict[str, Any],
    model: str,
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """Add the sampling params to `kwargs` only if `model` still accepts them.

    Mutates and returns `kwargs`. A `None` value means "the caller has no value"; note that
    `CompletionRequest.temperature` defaults to 0.0, which is a real value that must still be
    sent to providers that accept it — the gate is on the MODEL, never on the value.
    """
    if not supports_sampling_params(model):
        return kwargs
    if temperature is not None:
        kwargs["temperature"] = temperature
    if top_p is not None:
        kwargs["top_p"] = top_p
    if top_k is not None:
        kwargs["top_k"] = top_k
    return kwargs


__all__ = [
    "SAMPLING_PARAMS",
    "apply_sampling_params",
    "is_sampling_rejection",
    "mark_sampling_unsupported",
    "normalize_model",
    "supports_sampling_params",
]
