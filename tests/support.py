"""Shared test helpers (not shipped in the package)."""

from __future__ import annotations

from collections.abc import Iterator

from agent86.cognitive.base import ModelProvider
from agent86.types import Completion, CompletionDelta, CompletionRequest, Usage


class TextProvider(ModelProvider):
    """A provider that always streams a fixed reply with no tool calls."""

    name = "text"

    def __init__(self, reply: str, model: str = "fake:text"):
        self.model = model
        self._reply = reply

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        yield CompletionDelta(text=self._reply)
        yield CompletionDelta(
            done=True,
            completion=Completion(
                text=self._reply,
                usage=Usage(input_tokens=3, output_tokens=2),
                model=self.model,
            ),
        )


def make_text_provider(reply: str) -> TextProvider:
    return TextProvider(reply)
