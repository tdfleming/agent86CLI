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

# Providers slated for later phases, with the phase that delivers them.
_PLANNED: dict[str, str] = {
    "openai": "Phase 7",
    "llamacpp": "Phase 7",
}


def provider_for_ref(ref: ModelRef, config: Config) -> ModelProvider:
    """Construct the provider that serves ``ref`` (e.g. ``anthropic:claude-opus-4-8``)."""
    pconf: ProviderConfig = config.providers.get(ref.provider, ProviderConfig())

    if ref.provider == "anthropic":
        from agent86.cognitive.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=ref.model, config=pconf)

    if ref.provider == "ollama":
        from agent86.cognitive.ollama_provider import OllamaProvider

        return OllamaProvider(model=ref.model, config=pconf)

    if ref.provider in _PLANNED:
        raise ProviderError(
            f"Provider '{ref.provider}' is not wired yet ({_PLANNED[ref.provider]} - "
            "see docs/ARCHITECTURE.md)."
        )

    raise ProviderError(
        f"Unknown provider '{ref.provider}'. Known: anthropic, ollama "
        f"(openai, llamacpp coming in Phase 7)."
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
