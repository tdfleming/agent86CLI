"""llama.cpp / LM Studio provider (Tier 3).

Both expose an OpenAI-compatible server, so this is a thin specialization of
:class:`OpenAIProvider` that points at the local endpoint and requires no API key.
"""

from __future__ import annotations

from agent86.cognitive.openai_provider import OpenAIProvider
from agent86.config import ProviderConfig

_DEFAULT_LOCAL_BASE = "http://localhost:8080/v1"  # llama.cpp server; LM Studio is :1234/v1


class LlamaCppProvider(OpenAIProvider):
    name = "llamacpp"

    def __init__(self, model: str, config: ProviderConfig):
        if not config.base_url:
            config = ProviderConfig(base_url=_DEFAULT_LOCAL_BASE, api_key_env=config.api_key_env)
        super().__init__(model=model, config=config, require_key=False)


__all__ = ["LlamaCppProvider"]
