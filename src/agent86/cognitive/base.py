"""The unified model interface and provider factory (Tier 3).

Every backend — Anthropic, OpenAI-compatible, Ollama, llama.cpp — implements
:class:`ModelProvider`, so the Orchestration Tier stays completely model-agnostic.
Providers implement :meth:`stream`; :meth:`complete` is derived from it, so a single
API round-trip yields both live text and the authoritative result (tool calls + usage).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from agent86.config import Config, ProviderConfig
from agent86.types import (
    Completion,
    CompletionDelta,
    CompletionRequest,
    Message,
    ModelRef,
)

#: Sentinel for "the caller did not supply a key; resolve it yourself from env/keyring".
#: ``provider_for_ref`` passes a concrete ``str | None`` because only it knows the config
#: section name (``ref.provider``) that D-07 keys the keyring on; direct construction (tests,
#: ad-hoc use) falls back to self-resolution so existing call sites keep working.
UNRESOLVED: Any = object()


class ProviderError(RuntimeError):
    """A provider could not be constructed or reached (missing key, SDK, or server)."""


class ModelProvider(ABC):
    """Adapter behind one provider's API."""

    #: short provider id, e.g. "anthropic"
    name: str = "base"
    #: the concrete model this instance targets
    model: str = ""
    #: whether the backend supports first-class tool/function calling
    supports_native_tools: bool = False

    @abstractmethod
    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        """Yield text deltas; the final delta carries ``done=True`` + full completion."""
        raise NotImplementedError

    def complete(self, request: CompletionRequest) -> Completion:
        """Consume :meth:`stream` and return the assembled completion."""
        final: Completion | None = None
        text_parts: list[str] = []
        for delta in self.stream(request):
            if delta.text:
                text_parts.append(delta.text)
            if delta.done and delta.completion is not None:
                final = delta.completion
        if final is None:
            final = Completion(text="".join(text_parts), model=self.model)
        elif not final.text:
            final.text = "".join(text_parts)
        return final

    def count_tokens(self, messages: list[Message]) -> int:
        """Rough token estimate (~4 chars/token). Overridden where a real counter exists."""
        chars = sum(len(m.content or "") for m in messages)
        return chars // 4


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #

def _build_provider(ref: ModelRef, pconf: ProviderConfig, api_key: Any) -> ModelProvider:
    """The provider dispatch table. Extracted so provider_for_ref can guard construction."""
    if ref.provider == "anthropic":
        from agent86.cognitive.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=ref.model, config=pconf, api_key=api_key)

    if ref.provider == "ollama":
        from agent86.cognitive.ollama_provider import OllamaProvider

        return OllamaProvider(model=ref.model, config=pconf)

    if ref.provider in ("openai", "openai-compatible"):
        from agent86.cognitive.openai_provider import OpenAIProvider

        return OpenAIProvider(model=ref.model, config=pconf, api_key=api_key)

    if ref.provider == "llamacpp":
        from agent86.cognitive.llamacpp_provider import LlamaCppProvider

        return LlamaCppProvider(model=ref.model, config=pconf, api_key=api_key)

    # Fallback: any custom provider with a base_url is treated as OpenAI-compatible.
    # This makes OpenRouter, Groq, Together, Fireworks, Azure, vLLM, LM Studio, etc.
    # first-class prefixes — just add a `[providers.<name>]` block with a base_url
    # (and api_key_env if the endpoint needs a key).
    if pconf.base_url:
        from agent86.cognitive.openai_provider import OpenAIProvider

        # Require a key only when the config names an env var for one (hosted APIs);
        # a base_url with no api_key_env is treated as a keyless local endpoint.
        return OpenAIProvider(
            model=ref.model, config=pconf, require_key=bool(pconf.api_key_env), api_key=api_key
        )

    raise ProviderError(
        f"Unknown provider '{ref.provider}'. Built-in: anthropic, openai, ollama, llamacpp. "
        f"For an OpenAI-compatible endpoint, add a [providers.{ref.provider}] block with a "
        "base_url (e.g. OpenRouter, Groq, Together) to your config."
    )


def provider_for_ref(ref: ModelRef, config: Config, api_key: Any = UNRESOLVED) -> ModelProvider:
    """Construct the provider that serves ``ref`` (e.g. ``anthropic:claude-opus-4-8``).

    ``api_key`` may be supplied explicitly (the TUI connection test passes a key that is being
    validated but is not yet stored anywhere — D-14); otherwise it is resolved env-first then
    from the OS keyring, keyed on ``ref.provider`` (the config section name, D-07).

    Any exception escaping construction is converted to a ProviderError with a redacted
    message and a severed cause chain (SEC-01 / D-10): the resolved key lives in the locals
    of every frame below this point, so letting a raw TypeError propagate prints the secret
    (UAT gap 2). It also means callers that already handle ProviderError — the plain loop's
    `run_repl`, the TUI connection test — degrade cleanly instead of dumping a traceback.
    """
    pconf: ProviderConfig = config.providers.get(ref.provider, ProviderConfig())

    if api_key is UNRESOLVED:
        from agent86.secrets import resolve_api_key

        api_key = resolve_api_key(ref.provider, pconf.api_key_env)

    try:
        return _build_provider(ref, pconf, api_key)
    except ProviderError:
        raise
    except Exception as exc:
        from agent86.secrets import redact

        detail = redact(
            f"{type(exc).__name__}: {exc}",
            api_key if isinstance(api_key, str) else None,
        )
        # `from None` is deliberate: the chained frames hold the key in their locals.
        raise ProviderError(
            f"Could not construct the '{ref.provider}' provider — {detail}"
        ) from None


def provider_for_model(model: str, config: Config) -> ModelProvider:
    """Convenience wrapper: parse a ``provider:model`` string and build its provider."""
    return provider_for_ref(ModelRef.parse(model), config)


__all__ = [
    "ModelProvider",
    "ProviderError",
    "UNRESOLVED",
    "provider_for_ref",
    "provider_for_model",
]
