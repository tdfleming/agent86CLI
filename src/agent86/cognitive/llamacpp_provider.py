"""llama.cpp / LM Studio provider (Tier 3).

Both expose an OpenAI-compatible server, so this is a thin specialization of
:class:`OpenAIProvider` that points at the local endpoint and requires no API key.
"""

from __future__ import annotations

from typing import Any

from agent86.cognitive.base import UNRESOLVED
from agent86.cognitive.openai_provider import OpenAIProvider
from agent86.config import ProviderConfig

_DEFAULT_LOCAL_BASE = "http://localhost:8080/v1"  # llama.cpp server; LM Studio is :1234/v1


class LlamaCppProvider(OpenAIProvider):
    name = "llamacpp"

    def __init__(self, model: str, config: ProviderConfig, api_key: Any = UNRESOLVED):
        if not config.base_url:
            # model_copy preserves every other field on the caller's config (notably
            # read_timeout_s/connect_timeout_s) instead of dropping them by reconstructing a
            # bare ProviderConfig with only base_url/api_key_env carried over.
            config = config.model_copy(update={"base_url": _DEFAULT_LOCAL_BASE})
        super().__init__(model=model, config=config, require_key=False, api_key=api_key)


__all__ = ["LlamaCppProvider"]
