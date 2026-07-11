"""Phase 3 — the full Reason->Act->Observe loop with tool execution (no network)."""

from __future__ import annotations

from collections.abc import Iterator

from agent86.cognitive.base import ModelProvider
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.types import (
    AgentPhase,
    ApprovalMode,
    Completion,
    CompletionDelta,
    CompletionRequest,
    Role,
    ToolCall,
    Usage,
)


class WriteThenAnswerProvider(ModelProvider):
    """Turn 1: request write_file. Turn 2 (after observing the result): answer."""

    name = "faketool"

    def __init__(self, model: str = "fake:tool"):
        self.model = model
        self.calls = 0

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        self.calls += 1
        if self.calls == 1:
            call = ToolCall(
                id="c1", name="write_file", arguments={"path": "out.txt", "content": "hi there"}
            )
            yield CompletionDelta(
                done=True,
                completion=Completion(
                    text="", tool_calls=[call], usage=Usage(input_tokens=5, output_tokens=2),
                    model=self.model, stop_reason="tool_use",
                ),
            )
        else:
            yield CompletionDelta(text="done")
            yield CompletionDelta(
                done=True,
                completion=Completion(
                    text="done", usage=Usage(input_tokens=6, output_tokens=1), model=self.model
                ),
            )


def _auto_config():
    cfg = load_config()
    cfg.guardrails.approval = ApprovalMode.AUTO
    return cfg


def test_loop_executes_approved_tool_and_observes(tmp_path):
    provider = WriteThenAnswerProvider()
    harness = Harness(_auto_config(), provider=provider, workspace=tmp_path)
    state = harness.new_session()

    deltas = list(harness.run_turn("create out.txt with 'hi there'", state))
    streamed = "".join(d.text for d in deltas if d.text)

    # The tool actually ran, jailed to the workspace.
    assert (tmp_path / "out.txt").read_text() == "hi there"
    # The model looped twice (act, then observe->answer).
    assert provider.calls == 2
    # A tool observation is in the transcript, and the run finished with an answer.
    assert any(m.role == Role.TOOL for m in state.messages)
    assert state.messages[-1].content == "done"
    assert state.phase is AgentPhase.DONE
    assert "[tool] write_file" in streamed


def test_loop_declines_side_effect_without_approval(tmp_path):
    # Default approval is ASK; run() (no interactive prompt) => declined.
    provider = WriteThenAnswerProvider()
    cfg = load_config()  # approval = ASK, no prompt callback
    harness = Harness(cfg, provider=provider, workspace=tmp_path)
    state = harness.new_session()

    list(harness.run_turn("create out.txt", state))

    assert not (tmp_path / "out.txt").exists()  # nothing was written
    tool_msg = next(m for m in state.messages if m.role == Role.TOOL)
    assert "Not executed" in tool_msg.content
    assert state.phase is AgentPhase.DONE  # still terminates cleanly
