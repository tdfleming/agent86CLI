"""Phase 3 — the full Reason->Act->Observe loop with tool execution (no network)."""

from __future__ import annotations

import time
from collections.abc import Iterator

from agent86.cognitive.base import ModelProvider
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.tools.base import EmptyArgs, Tool, ToolContext
from agent86.types import (
    INVALID_TOOL_ARGS_KEY,
    AgentPhase,
    ApprovalMode,
    Completion,
    CompletionDelta,
    CompletionRequest,
    Role,
    ToolCall,
    ToolResult,
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


# ---- parallel tool dispatch (v0.8) ----------------------------------------- #


class _BatchProvider(ModelProvider):
    """Turn 1: one completion carrying a whole batch of tool calls. Turn 2: answer."""

    name = "batch"

    def __init__(self, calls: list[ToolCall], model: str = "fake:batch"):
        self.model = model
        self._calls = calls
        self.turns = 0

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        self.turns += 1
        if self.turns == 1:
            yield CompletionDelta(
                done=True,
                completion=Completion(
                    text="", tool_calls=list(self._calls), usage=Usage(),
                    model=self.model, stop_reason="tool_use",
                ),
            )
            return
        yield CompletionDelta(
            done=True,
            completion=Completion(
                text="done", usage=Usage(), model=self.model, stop_reason="end_turn"
            ),
        )


class _SleepTool(Tool[EmptyArgs]):
    """Records when it started and finished, so overlap is observable."""

    Args = EmptyArgs

    def __init__(self, name: str, delay: float = 0.3, side_effecting: bool = False,
                 log: list | None = None, on_run=None):
        self.name = name
        self.description = f"sleeps {delay}s"
        self.side_effecting = side_effecting
        self.delay = delay
        self.log = log if log is not None else []
        self.runs = 0
        self._on_run = on_run

    def execute(self, args: EmptyArgs, ctx: ToolContext) -> ToolResult:
        self.runs += 1
        self.log.append(("start", self.name, time.monotonic()))
        if self._on_run is not None:
            self._on_run()
        time.sleep(self.delay)
        self.log.append(("end", self.name, time.monotonic()))
        return ToolResult(call_id="", name=self.name, content=f"{self.name} ok")


def _registry(*tools):
    from agent86.tools.registry import ToolRegistry

    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def test_read_only_tools_in_one_step_run_concurrently():
    log: list = []
    tools = [_SleepTool(f"read_{i}", 0.3, log=log) for i in range(2)]
    provider = _BatchProvider(
        [ToolCall(id=f"c{i}", name=t.name, arguments={}) for i, t in enumerate(tools)]
    )
    harness = Harness(
        _auto_config(), provider=provider, memory=None, registry=_registry(*tools)
    )
    state = harness.new_session()

    started = time.monotonic()
    list(harness.run_turn("go", state))
    elapsed = time.monotonic() - started

    assert all(t.runs == 1 for t in tools)
    assert elapsed < 0.5, f"two 0.3s reads took {elapsed:.2f}s — they did not overlap"
    # Results are still observed in CALL order, whatever order they finished in.
    tool_msgs = [m for m in state.messages if m.role is Role.TOOL]
    assert [m.name for m in tool_msgs] == ["read_0", "read_1"]
    assert [m.tool_call_id for m in tool_msgs] == ["c0", "c1"]


def test_parallel_tools_can_be_disabled():
    log: list = []
    tools = [_SleepTool(f"read_{i}", 0.2, log=log) for i in range(2)]
    cfg = _auto_config()
    cfg.limits.parallel_tools = False
    provider = _BatchProvider(
        [ToolCall(id=f"c{i}", name=t.name, arguments={}) for i, t in enumerate(tools)]
    )
    harness = Harness(cfg, provider=provider, memory=None, registry=_registry(*tools))

    started = time.monotonic()
    list(harness.run_turn("go", harness.new_session()))

    # Strictly one after the other (0.35, not 0.4: Windows' sleep granularity undershoots).
    assert time.monotonic() - started >= 0.35
    # ... and strictly in order: nothing overlaps.
    assert [entry[1] for entry in log] == ["read_0", "read_0", "read_1", "read_1"]


def test_a_side_effecting_call_runs_after_the_reads():
    log: list = []
    read_a = _SleepTool("read_a", 0.2, log=log)
    read_b = _SleepTool("read_b", 0.2, log=log)
    write = _SleepTool("write_it", 0.05, side_effecting=True, log=log)
    # The model asks for the write FIRST; the harness still runs it last.
    provider = _BatchProvider(
        [
            ToolCall(id="c0", name="write_it", arguments={}),
            ToolCall(id="c1", name="read_a", arguments={}),
            ToolCall(id="c2", name="read_b", arguments={}),
        ]
    )
    harness = Harness(
        _auto_config(), provider=provider, memory=None, registry=_registry(read_a, read_b, write)
    )
    state = harness.new_session()

    list(harness.run_turn("go", state))

    write_start = next(e[2] for e in log if e[0] == "start" and e[1] == "write_it")
    reads_end = max(e[2] for e in log if e[0] == "end" and e[1].startswith("read_"))
    assert write_start >= reads_end, "the write overlapped a read"
    # Ordering in the transcript follows the MODEL's call order, not the execution order.
    tool_msgs = [m for m in state.messages if m.role is Role.TOOL]
    assert [m.name for m in tool_msgs] == ["write_it", "read_a", "read_b"]


def test_cancel_mid_batch_skips_the_pending_side_effecting_calls():
    log: list = []
    box: dict = {}
    read_a = _SleepTool("read_a", 0.05, log=log, on_run=lambda: box["h"].cancel())
    read_b = _SleepTool("read_b", 0.05, log=log)
    write = _SleepTool("write_it", 0.05, side_effecting=True, log=log)
    provider = _BatchProvider(
        [
            ToolCall(id="c0", name="read_a", arguments={}),
            ToolCall(id="c1", name="read_b", arguments={}),
            ToolCall(id="c2", name="write_it", arguments={}),
        ]
    )
    harness = Harness(
        _auto_config(), provider=provider, memory=None, registry=_registry(read_a, read_b, write)
    )
    box["h"] = harness
    state = harness.new_session()

    streamed = "".join(d.text for d in harness.run_turn("go", state) if d.text)

    assert write.runs == 0                       # the side effect never happened
    assert provider.turns == 1                   # and no follow-up model call was made
    assert "[cancelled]" in streamed
    assert state.phase is AgentPhase.ERROR
    # Every call still has an observation, so the history has no tool_use without a result.
    tool_msgs = [m for m in state.messages if m.role is Role.TOOL]
    assert [m.tool_call_id for m in tool_msgs] == ["c0", "c1", "c2"]
    assert "Not executed: cancelled" in tool_msgs[-1].content
