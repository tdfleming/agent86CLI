"""Shared test helpers (not shipped in the package)."""

from __future__ import annotations

from collections.abc import Iterator

from agent86.cognitive.base import ModelProvider
from agent86.types import Completion, CompletionDelta, CompletionRequest, ToolCall, Usage


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


class ToolThenTextProvider(ModelProvider):
    """Turn 1: emit ``tool_call``. Turn 2 (after observing the result): stream ``reply``."""

    name = "tooltext"

    def __init__(self, tool_call: ToolCall, reply: str = "done", model: str = "fake:tool"):
        self.model = model
        self._call = tool_call
        self._reply = reply
        self.calls = 0

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        self.calls += 1
        if self.calls == 1:
            yield CompletionDelta(
                done=True,
                completion=Completion(
                    text="", tool_calls=[self._call], usage=Usage(input_tokens=5, output_tokens=2),
                    model=self.model, stop_reason="tool_use",
                ),
            )
        else:
            yield CompletionDelta(text=self._reply)
            yield CompletionDelta(
                done=True,
                completion=Completion(
                    text=self._reply, usage=Usage(input_tokens=6, output_tokens=1),
                    model=self.model,
                ),
            )
