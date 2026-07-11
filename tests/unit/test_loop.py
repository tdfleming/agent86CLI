"""Phase 2 — the harness loop and provider factory (no network)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agent86.cognitive.base import ModelProvider, ProviderError, provider_for_model
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.types import (
    AgentPhase,
    Completion,
    CompletionDelta,
    CompletionRequest,
    Role,
    Usage,
)


class FakeProvider(ModelProvider):
    """A provider that streams a canned answer with no tool calls."""

    name = "fake"

    def __init__(self, model: str = "fake:test", reply: str = "hello there"):
        self.model = model
        self._reply = reply

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        for word in self._reply.split():
            yield CompletionDelta(text=word + " ")
        yield CompletionDelta(
            done=True,
            completion=Completion(
                text=self._reply,
                usage=Usage(input_tokens=11, output_tokens=5, cost_usd=0.0),
                model=self.model,
                stop_reason="end_turn",
            ),
        )


def _config():
    return load_config()


def test_run_turn_records_history_and_usage():
    harness = Harness(_config(), provider=FakeProvider())
    state = harness.new_session()

    deltas = list(harness.run_turn("hi", state))
    streamed = "".join(d.text for d in deltas if d.text)

    assert "hello there" in streamed
    # user + assistant appended
    assert [m.role for m in state.messages] == [Role.USER, Role.ASSISTANT]
    assert state.messages[-1].content == "hello there"
    # one step recorded, usage accumulated, phase completed
    assert state.step_count == 1
    assert state.usage.input_tokens == 11
    assert state.usage.output_tokens == 5
    assert state.phase is AgentPhase.DONE


def test_complete_is_derived_from_stream():
    provider = FakeProvider(reply="one two three")
    completion = provider.complete(
        CompletionRequest(model="fake:test", messages=[])
    )
    assert completion.text == "one two three"
    assert completion.usage.output_tokens == 5


def test_factory_rejects_unwired_and_unknown_providers():
    cfg = _config()
    with pytest.raises(ProviderError, match="Phase 7"):
        provider_for_model("openai:gpt-4o", cfg)
    with pytest.raises(ProviderError, match="Unknown provider"):
        provider_for_model("mystery:model", cfg)
