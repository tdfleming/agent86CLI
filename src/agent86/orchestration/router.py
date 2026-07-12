"""Dynamic model routing (Tier 3 policy) — the triage pattern.

Routes each turn to a cheap/local model or a frontier model based on apparent complexity,
so simple asks don't pay frontier prices. Routing is a fast deterministic heuristic (no extra
model call); when ``model.router`` is ``off`` every turn uses the default model. Providers are
built lazily and cached by model string.
"""

from __future__ import annotations

import re

from agent86.cognitive.base import ModelProvider, provider_for_model
from agent86.config import Config

# Signals that a task is non-trivial and deserves the frontier model.
_COMPLEX = re.compile(
    r"\b(code|coding|program|script|debug|refactor|analy[sz]e|implement|plan|design|"
    r"architect|multi[- ]?step|step by step|research|reason|prove|optimi[sz]e|build|"
    r"fix|migrate|review|explain why)\b",
    re.I,
)
_SIMPLE_MAX_CHARS = 240


def is_simple(task_text: str) -> bool:
    """Heuristic: short and free of complexity keywords -> route to the cheap model."""
    if _COMPLEX.search(task_text):
        return False
    return len(task_text.strip()) <= _SIMPLE_MAX_CHARS


class ModelRouter:
    def __init__(self, config: Config, forced_provider: ModelProvider | None = None):
        self.config = config
        self.forced = forced_provider
        self._cache: dict[str, ModelProvider] = {}
        if forced_provider is not None:
            self._cache[forced_provider.model] = forced_provider

    @property
    def enabled(self) -> bool:
        return self.forced is None and self.config.model.router == "triage"

    def select_model(self, task_text: str) -> str:
        if self.forced is not None:
            return self.forced.model
        if not self.enabled:
            return self.config.model.default
        route = self.config.model.route
        return route.cheap if is_simple(task_text) else route.frontier

    def set_forced(self, provider: ModelProvider) -> None:
        """Pin the router to a single provider (overrides triage routing)."""
        self.forced = provider
        self._cache[provider.model] = provider

    def provider_for(self, model_str: str) -> ModelProvider:
        if self.forced is not None:
            return self.forced
        if model_str not in self._cache:
            self._cache[model_str] = provider_for_model(model_str, self.config)
        return self._cache[model_str]

    def default_provider(self) -> ModelProvider:
        if self.forced is not None:
            return self.forced
        return self.provider_for(self.config.model.default)


__all__ = ["ModelRouter", "is_simple"]
