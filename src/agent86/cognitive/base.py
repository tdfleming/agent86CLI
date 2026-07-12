"""The unified model interface and provider factory (Tier 3).

Every backend — Anthropic, OpenAI-compatible, Ollama, llama.cpp — implements
:class:`ModelProvider`, so the Orchestration Tier stays completely model-agnostic.
Providers implement :meth:`stream`; :meth:`complete` is derived from it, so a single
API round-trip yields both live text and the authoritative result (tool calls + usage).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from agent86.config import Config, ProviderConfig
from agent86.types import (
    Completion,
    CompletionDelta,
    CompletionRequest,
    Message,
    ModelRef,
)


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

def provider_for_ref(ref: ModelRef, config: Config) -> ModelProvider:
    """Construct the provider that serves ``ref`` (e.g. ``anthropic:claude-opus-4-8``)."""
    pconf: ProviderConfig = config.providers.get(ref.provider, ProviderConfig())

    if ref.provider == "anthropic":
        from agent86.cognitive.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=ref.model, config=pconf)

    if ref.provider == "ollama":
        from agent86.cognitive.ollama_provider import OllamaProvider

        return OllamaProvider(model=ref.model, config=pconf)

    if ref.provider in ("openai", "openai-compatible"):
        from agent86.cognitive.openai_provider import OpenAIProvider

        return OpenAIProvider(model=ref.model, config=pconf)

    if ref.provider == "llamacpp":
        from agent86.cognitive.llamacpp_provider import LlamaCppProvider

        return LlamaCppProvider(model=ref.model, config=pconf)

    # Fallback: any custom provider with a base_url is treated as OpenAI-compatible.
    # This makes OpenRouter, Groq, Together, Fireworks, Azure, vLLM, LM Studio, etc.
    # first-class prefixes — just add a `[providers.<name>]` block with a base_url
    # (and api_key_env if the endpoint needs a key).
    if pconf.base_url:
        from agent86.cognitive.openai_provider import OpenAIProvider

        # Require a key only when the config names an env var for one (hosted APIs);
        # a base_url with no api_key_env is treated as a keyless local endpoint.
        return OpenAIProvider(
            model=ref.model, config=pconf, require_key=bool(pconf.api_key_env)
        )

    raise ProviderError(
        f"Unknown provider '{ref.provider}'. Built-in: anthropic, openai, ollama, llamacpp. "
        f"For an OpenAI-compatible endpoint, add a [providers.{ref.provider}] block with a "
        "base_url (e.g. OpenRouter, Groq, Together) to your config."
    )


def provider_for_model(model: str, config: Config) -> ModelProvider:
    """Convenience wrapper: parse a ``provider:model`` string and build its provider."""
    return provider_for_ref(ModelRef.parse(model), config)


__all__ = [
    "ModelProvider",
    "ProviderError",
    "provider_for_ref",
    "provider_for_model",
]
