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

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agent86.config import Config

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


# --------------------------------------------------------------------------- #
# Context windows
#
# The other per-model fact the harness cannot guess. Before v0.8 the conversation budget was
# a flat `limits.max_context_tokens = 8000` regardless of model, which wasted ~96% of a 200k
# Claude window and *overspent* a 4k local one. This is the single lookup everything asks.
# --------------------------------------------------------------------------- #

#: Used when nothing else knows: the smallest window any modern model ships with.
DEFAULT_CONTEXT_WINDOW = 8_192

#: Model-id substring -> context window (tokens), matched against the model id with its
#: `provider:` prefix stripped and lowercased. Ordered: the FIRST match wins, so more
#: specific ids must come before the families that contain them as a substring.
_CONTEXT_WINDOWS: tuple[tuple[str, int], ...] = (
    # Anthropic — every Claude 4.x / 5.x model is 200k.
    ("claude", 200_000),
    # OpenAI. gpt-4.1 advertises 1,047,576 input tokens; gpt-5 advertises 400,000.
    ("gpt-5", 400_000),
    ("gpt-4.1", 1_047_576),
    ("gpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("gpt-4", 8_192),
    ("gpt-3.5", 16_385),
    ("o4-mini", 200_000),
    ("o3", 200_000),
    ("o1", 200_000),
    # Common open-weights ids, for OpenAI-compatible gateways (OpenRouter, Groq, vLLM).
    ("llama-3.1", 131_072),
    ("llama3.1", 131_072),
    ("llama-3.3", 131_072),
    ("llama3.3", 131_072),
    ("qwen", 32_768),
    ("mixtral", 32_768),
    ("mistral", 32_768),
    ("gemma", 8_192),
    ("phi", 16_384),
)


def context_window_for(model_ref: str, config: Config) -> int:
    """Tokens of context the model behind ``model_ref`` can hold, in priority order.

    1. ``[model.context_window]`` — an explicit user override, looked up by the full
       ``provider:model`` ref first and then by the bare model id.
    2. The provider, where the *server* owns the window rather than the model: Ollama serves
       whatever ``[providers.ollama] num_ctx`` asks for, and llama.cpp whatever it was
       launched with — neither is knowable from the model name, so guessing 128k from
       "llama3.1" would hand the budget a number the server will truncate.
    3. :data:`_CONTEXT_WINDOWS`, matched as a substring of the model id.
    4. :data:`DEFAULT_CONTEXT_WINDOW`.

    ``model_ref`` may be a bare model id; then only steps 1, 3 and 4 apply.
    """
    ref = str(model_ref)
    provider, _, model = ref.partition(":")
    if not model:  # a bare model id, no provider prefix
        provider, model = "", ref

    overrides = getattr(config.model, "context_window", {}) or {}
    for key in (ref, model):
        override = overrides.get(key)
        if override:
            return int(override)

    if provider == "ollama":
        pconf = config.providers.get("ollama")
        num_ctx = pconf.num_ctx if pconf else None
        return int(num_ctx) if num_ctx else DEFAULT_CONTEXT_WINDOW
    if provider == "llamacpp":
        # llama.cpp's window is a server launch flag (-c); it is not discoverable over the
        # OpenAI-compatible API, so the conservative default is the only honest answer.
        return DEFAULT_CONTEXT_WINDOW

    ident = model.strip().lower()
    for needle, window in _CONTEXT_WINDOWS:
        if needle in ident:
            return window
    return DEFAULT_CONTEXT_WINDOW


def max_output_tokens_for(model_ref: str, config: Config) -> int:
    """Output cap for one call: the provider's ``max_tokens``, else ``limits.max_output_tokens``.

    ``model_ref``'s provider segment must be the CONFIG SECTION the provider was built from
    (``ModelProvider.config_ref``), not the adapter name — see that property.
    """
    provider = str(model_ref).partition(":")[0]
    pconf = config.providers.get(provider)
    per_provider = pconf.max_tokens if pconf else None
    if per_provider:
        return int(per_provider)
    return int(config.limits.max_output_tokens or 8192)


__all__ = [
    "DEFAULT_CONTEXT_WINDOW",
    "SAMPLING_PARAMS",
    "apply_sampling_params",
    "context_window_for",
    "is_sampling_rejection",
    "mark_sampling_unsupported",
    "max_output_tokens_for",
    "normalize_model",
    "supports_sampling_params",
]
