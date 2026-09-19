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


def is_summary_request(request: CompletionRequest) -> bool:
    """True when ``request`` is the harness asking for a compaction summary."""
    from agent86.memory.working import SUMMARY_SYSTEM_PROMPT
    from agent86.types import Role

    return any(
        m.role == Role.SYSTEM and m.content == SUMMARY_SYSTEM_PROMPT for m in request.messages
    )


class ScriptedProvider(ModelProvider):
    """Streams a scripted list of ``Completion``s, one per call; the last one repeats.

    The general-purpose fake for multi-step loop tests (continuations, tool batches): each
    ``stream()`` returns the next scripted completion and records the request it was given.
    """

    name = "scripted"

    def __init__(self, completions: list[Completion], model: str = "fake:scripted"):
        self.model = model
        self._script = list(completions)
        self.requests: list[CompletionRequest] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        self.requests.append(request)
        completion = self._script[min(len(self.requests) - 1, len(self._script) - 1)]
        completion = completion.model_copy(deep=True)
        completion.model = self.model
        if completion.text:
            yield CompletionDelta(text=completion.text)
        yield CompletionDelta(done=True, completion=completion)


class CompactingProvider(ModelProvider):
    """Serves compaction summaries separately from ordinary turns.

    A summarization request (recognised by its system prompt) gets ``summary`` back — or
    raises, when ``fail_summary`` is set, so the drop fallback can be exercised. Every other
    request gets ``reply``.
    """

    name = "compacting"

    def __init__(
        self,
        reply: str = "all done",
        summary: str = "GOAL: ship v0.8\nFACTS: src/agent86/orchestration/loop.py",
        fail_summary: bool = False,
        model: str = "fake:compacting",
    ):
        self.model = model
        self._reply = reply
        self._summary = summary
        self._fail = fail_summary
        self.summary_requests: list[CompletionRequest] = []
        self.turn_requests: list[CompletionRequest] = []

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        if is_summary_request(request):
            self.summary_requests.append(request)
            if self._fail:
                raise RuntimeError("summarizer exploded")
            yield CompletionDelta(
                done=True,
                completion=Completion(
                    text=self._summary,
                    usage=Usage(input_tokens=40, output_tokens=12),
                    model=self.model,
                    stop_reason="end_turn",
                ),
            )
            return
        self.turn_requests.append(request)
        yield CompletionDelta(text=self._reply)
        yield CompletionDelta(
            done=True,
            completion=Completion(
                text=self._reply,
                usage=Usage(input_tokens=7, output_tokens=3),
                model=self.model,
                stop_reason="end_turn",
            ),
        )
