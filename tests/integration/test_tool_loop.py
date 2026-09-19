"""Phase 3 — the full Reason->Act->Observe loop with tool execution (no network)."""

from __future__ import annotations

from collections.abc import Iterator

from agent86.cognitive.base import ModelProvider
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.types import (
    INVALID_TOOL_ARGS_KEY,
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
    harness = Harness(_auto_config(), provider=provider, workspace=tmp_path, memory=None)
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


class InvalidArgsProvider(ModelProvider):
    """Turn 1: a tool call whose arguments the provider could not parse. Turn 2: an answer."""

    name = "badjson"

    def __init__(self, raw: str = '{"path": "out.txt", ', model: str = "fake:badjson"):
        self.model = model
        self.raw = raw
        self.calls = 0

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        self.calls += 1
        if self.calls == 1:
            call = ToolCall(
                id="c1", name="write_file", arguments={INVALID_TOOL_ARGS_KEY: self.raw}
            )
            yield CompletionDelta(
                done=True,
                completion=Completion(
                    text="", tool_calls=[call], usage=Usage(), model=self.model,
                    stop_reason="tool_use",
                ),
            )
        else:
            yield CompletionDelta(
                done=True,
                completion=Completion(text="fixed it", usage=Usage(), model=self.model),
            )


def test_unparseable_tool_arguments_get_a_precise_error(tmp_path):
    """The model must be told its JSON was malformed — not that a field is missing."""
    provider = InvalidArgsProvider()
    harness = Harness(_auto_config(), provider=provider, workspace=tmp_path, memory=None)
    state = harness.new_session()

    list(harness.run_turn("write the file", state))

    tool_msg = next(m for m in state.messages if m.role == Role.TOOL)
    assert "invalid JSON in tool arguments" in tool_msg.content
    assert '{"path": "out.txt", ' in tool_msg.content
    assert "field required" not in tool_msg.content
    # The tool never ran, and the model got a chance to correct itself.
    assert not (tmp_path / "out.txt").exists()
    assert provider.calls == 2
    assert state.phase is AgentPhase.DONE


def test_unparseable_tool_arguments_never_reach_the_tool(tmp_path):
    from agent86.tools.base import EmptyArgs, Tool
    from agent86.tools.registry import ToolRegistry
    from agent86.types import ToolResult, ToolSpec

    class _Spy(Tool[EmptyArgs]):
        Args = EmptyArgs

        def __init__(self) -> None:
            self.name = "write_file"
            self.description = "spy"
            self.side_effecting = False
            self.runs = 0

        def spec(self) -> ToolSpec:
            return ToolSpec(name=self.name, description=self.description,
                            parameters={"type": "object", "properties": {}})

        def execute(self, args: EmptyArgs, ctx) -> ToolResult:
            self.runs += 1
            return ToolResult(call_id="", name=self.name, content="ran")

    spy = _Spy()
    registry = ToolRegistry()
    registry.register(spy)
    harness = Harness(_auto_config(), provider=InvalidArgsProvider(), workspace=tmp_path,
                      memory=None, registry=registry)

    list(harness.run_turn("write the file", harness.new_session()))

    assert spy.runs == 0  # intercepted before dispatch, so the sentinel is never visible


def test_subagent_also_rejects_unparseable_tool_arguments(tmp_path):
    from agent86.agents.subagent import SubAgent

    harness = Harness(_auto_config(), provider=InvalidArgsProvider(), workspace=tmp_path,
                      memory=None)
    call = ToolCall(id="c1", name="write_file", arguments={INVALID_TOOL_ARGS_KEY: "{oops"})

    result = SubAgent(harness, "worker", depth=1)._run_tool(call)

    assert result.ok is False
    assert "invalid JSON in tool arguments" in (result.error or "")
    assert not (tmp_path / "out.txt").exists()


def test_loop_declines_side_effect_without_approval(tmp_path):
    # Default approval is ASK; run() (no interactive prompt) => declined.
    provider = WriteThenAnswerProvider()
    cfg = load_config()  # approval = ASK, no prompt callback
    harness = Harness(cfg, provider=provider, workspace=tmp_path, memory=None)
    state = harness.new_session()

    list(harness.run_turn("create out.txt", state))

    assert not (tmp_path / "out.txt").exists()  # nothing was written
    tool_msg = next(m for m in state.messages if m.role == Role.TOOL)
    assert "Not executed" in tool_msg.content
    assert state.phase is AgentPhase.DONE  # still terminates cleanly
