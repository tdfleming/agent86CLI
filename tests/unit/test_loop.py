"""Phase 2 — the harness loop and provider factory (no network)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agent86.cognitive.base import ModelProvider, ProviderError, provider_for_model
from agent86.config import MCPServerConfig, load_config
from agent86.orchestration.loop import Harness, _summarize
from agent86.tools.base import EmptyArgs, Tool, ToolContext
from agent86.tools.mcp_client import MCPManager
from agent86.types import (
    AgentPhase,
    Completion,
    CompletionDelta,
    CompletionRequest,
    Role,
    ToolCall,
    ToolResult,
    ToolSpec,
    Usage,
)


def test_summarize_failed_result_without_error_string():
    # Regression: a failed result with no error string (e.g. web_fetch on a non-2xx status)
    # must not IndexError on an empty splitlines().
    r = ToolResult(call_id="1", name="web_fetch", ok=False, content="HTTP 403 https://x\nblocked")
    out = _summarize(r)
    assert out.startswith("error:") and "HTTP 403" in out
    # A wholly empty failed result falls back to a placeholder rather than crashing.
    assert _summarize(ToolResult(call_id="1", name="x", ok=False)) == "error: (failed)"


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
    harness = Harness(_config(), provider=FakeProvider(), memory=None)
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


def test_factory_rejects_unknown_provider():
    with pytest.raises(ProviderError, match="Unknown provider"):
        provider_for_model("mystery:model", _config())


def test_openai_without_key_reports_clearly(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="API key"):
        provider_for_model("openai:gpt-4o", _config())


# ---- ensure_mcp / add_mcp_server / remove_mcp_server (plan 04-06) ---------------- #


def _harness_no_mcp():
    return Harness(_config(), provider=FakeProvider(), memory=None)


def test_ensure_mcp_creates_manager_when_none():
    harness = _harness_no_mcp()
    assert harness.mcp is None

    manager = harness.ensure_mcp()

    assert isinstance(manager, MCPManager)
    assert harness.mcp is manager


def test_ensure_mcp_is_idempotent():
    harness = _harness_no_mcp()
    first = harness.ensure_mcp()
    second = harness.ensure_mcp()
    assert first is second


def test_ensure_mcp_does_not_touch_registry():
    harness = _harness_no_mcp()
    before = harness.registry.names()
    harness.ensure_mcp()
    assert harness.registry.names() == before


class _FakeMCPManager:
    """A stand-in for MCPManager exposing only what add/remove_mcp_server touch."""

    def __init__(self, server_tools: dict[str, list[Tool]] | None = None):
        self.servers: dict[str, MCPServerConfig] = {}
        self._server_tools = server_tools or {}
        self.stopped: list[str] = []

    def tools_for(self, name: str) -> list[Tool]:
        return list(self._server_tools.get(name, []))

    def stop_server(self, name: str, timeout: float = 10.0) -> None:
        self.stopped.append(name)
        self._server_tools.pop(name, None)


class _FakeMCPTool(Tool[EmptyArgs]):
    Args = EmptyArgs

    def __init__(self, name: str):
        self.name = name
        self.description = f"fake tool {name}"
        self.side_effecting = True

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name, description=self.description,
            parameters={"type": "object", "properties": {}}, side_effecting=True,
        )

    def execute(self, args: EmptyArgs, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError

    def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        return ToolResult(call_id=call.id, name=self.name, content="ok")


def _mcp_cfg() -> MCPServerConfig:
    return MCPServerConfig(command="echo", args=["hi"])


def test_add_mcp_server_mounts_tools_into_registry():
    harness = _harness_no_mcp()
    fake_tools = [_FakeMCPTool("mcp__alpha__foo"), _FakeMCPTool("mcp__alpha__bar")]
    harness.mcp = _FakeMCPManager({"alpha": fake_tools})

    mounted, collisions = harness.add_mcp_server("alpha", _mcp_cfg())

    assert set(mounted) == {"mcp__alpha__foo", "mcp__alpha__bar"}
    assert collisions == []
    names = harness.registry.names()
    spec_names = [s.name for s in harness.registry.specs()]
    for tool_name in mounted:
        assert tool_name in names
        assert tool_name in spec_names


def test_add_mcp_server_reports_collisions():
    harness = _harness_no_mcp()
    colliding = _FakeMCPTool("mcp__alpha__foo")
    pre_registered = _FakeMCPTool("mcp__alpha__foo")
    harness.registry.register(pre_registered)
    harness.mcp = _FakeMCPManager({"alpha": [colliding]})

    mounted, collisions = harness.add_mcp_server("alpha", _mcp_cfg())

    assert mounted == []
    assert collisions == ["mcp__alpha__foo"]
    assert harness.registry.get("mcp__alpha__foo") is pre_registered


def test_add_mcp_server_records_config_in_manager_servers():
    harness = _harness_no_mcp()
    harness.mcp = _FakeMCPManager({"alpha": []})
    cfg = _mcp_cfg()

    harness.add_mcp_server("alpha", cfg)

    assert harness.mcp.servers["alpha"] is cfg


def test_add_mcp_server_never_opens_a_transport(monkeypatch):
    import agent86.tools.mcp_client as mcp_client_mod

    def _boom(*args, **kwargs):
        raise AssertionError("add_mcp_server must never open a transport")

    monkeypatch.setattr(mcp_client_mod, "_open_transport", _boom)

    harness = _harness_no_mcp()
    fake_tools = [_FakeMCPTool("mcp__alpha__foo")]
    harness.mcp = _FakeMCPManager({"alpha": fake_tools})

    mounted, collisions = harness.add_mcp_server("alpha", _mcp_cfg())

    assert mounted == ["mcp__alpha__foo"]
    assert collisions == []


def test_remove_mcp_server_unregisters_and_stops():
    harness = _harness_no_mcp()
    fake_tools = [_FakeMCPTool("mcp__alpha__foo"), _FakeMCPTool("mcp__alpha__bar")]
    harness.mcp = _FakeMCPManager({"alpha": fake_tools})
    harness.add_mcp_server("alpha", _mcp_cfg())

    harness.remove_mcp_server("alpha")

    names = harness.registry.names()
    assert "mcp__alpha__foo" not in names
    assert "mcp__alpha__bar" not in names
    assert harness.mcp.stopped == ["alpha"]
    assert "alpha" not in harness.mcp.servers


def test_remove_mcp_server_unknown_name_is_noop():
    harness = _harness_no_mcp()
    harness.mcp = _FakeMCPManager({})
    before = harness.registry.names()

    harness.remove_mcp_server("nonexistent")

    assert harness.registry.names() == before
    assert harness.mcp.stopped == ["nonexistent"]


def test_remove_mcp_server_with_no_manager_is_noop():
    harness = _harness_no_mcp()
    assert harness.mcp is None

    harness.remove_mcp_server("alpha")  # must not raise

    assert harness.mcp is None


# ---- turn cancellation (Harness.cancel) ------------------------------------ #


class _RecordingTool(Tool[EmptyArgs]):
    """Records every invocation; optionally cancels the harness from inside `execute`."""

    Args = EmptyArgs

    def __init__(self, name: str, harness_box: dict | None = None):
        self.name = name
        self.description = f"test tool {name}"
        self.side_effecting = False
        self.runs = 0
        self._harness_box = harness_box

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name, description=self.description,
            parameters={"type": "object", "properties": {}}, side_effecting=False,
        )

    def execute(self, args: EmptyArgs, ctx: ToolContext) -> ToolResult:
        self.runs += 1
        if self._harness_box is not None:
            self._harness_box["harness"].cancel()
        return ToolResult(call_id="", name=self.name, content="ok")


class _CapturingRecorder:
    """Stand-in for `Recorder` that keeps every event in memory."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def event(self, session_id: str, kind: str, **data: object) -> None:
        self.events.append((session_id, kind, dict(data)))

    def close(self) -> None:
        pass


class _TwoToolCallProvider(ModelProvider):
    """One completion carrying TWO tool calls, so the between-calls check is observable."""

    name = "twotool"

    def __init__(self, calls: list[ToolCall]):
        self.model = "fake:twotool"
        self._calls = calls
        self.stream_count = 0

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        self.stream_count += 1
        if self.stream_count == 1:
            yield CompletionDelta(
                done=True,
                completion=Completion(
                    text="", tool_calls=self._calls,
                    usage=Usage(input_tokens=5, output_tokens=2),
                    model=self.model, stop_reason="tool_use",
                ),
            )
            return
        yield CompletionDelta(text="second turn")
        yield CompletionDelta(
            done=True,
            completion=Completion(
                text="second turn", usage=Usage(input_tokens=1, output_tokens=1),
                model=self.model,
            ),
        )


def _turn_end(recorder: _CapturingRecorder) -> dict:
    ends = [data for _, kind, data in recorder.events if kind == "turn_end"]
    assert ends, "the turn never recorded a turn_end event"
    return ends[-1]


def test_cancel_before_a_tool_call_skips_the_rest_of_the_batch():
    """Cancelling from inside tool #1 must stop tool #2 dead and end the turn.

    Sequential semantics, so `parallel_tools` is off: a cancel raised from inside one call
    obviously cannot un-start a sibling that is already running on another thread. The
    parallel batch has its own cancellation test below.
    """
    from agent86.tools.registry import ToolRegistry

    box: dict = {}
    first = _RecordingTool("stopper", harness_box=box)
    second = _RecordingTool("never_runs")
    registry = ToolRegistry()
    registry.register(first)
    registry.register(second)

    provider = _TwoToolCallProvider(
        [
            ToolCall(id="a", name="stopper", arguments={}),
            ToolCall(id="b", name="never_runs", arguments={}),
        ]
    )
    cfg = _config()
    cfg.limits.parallel_tools = False
    harness = Harness(cfg, provider=provider, memory=None, registry=registry)
    box["harness"] = harness
    recorder = _CapturingRecorder()
    harness.recorder = recorder
    state = harness.new_session()

    deltas = list(harness.run_turn("go", state))

    assert first.runs == 1
    assert second.runs == 0                       # the second call never executed
    assert provider.stream_count == 1             # and no further model call was made
    assert "[cancelled]" in "".join(d.text for d in deltas if d.text)
    assert _turn_end(recorder)["status"] == "cancelled"
    assert state.phase is AgentPhase.ERROR


def test_cancel_from_a_tool_prevents_the_follow_up_model_call():
    """The ToolThenTextProvider shape: turn 2 would normally stream a reply; cancel stops it."""
    from agent86.tools.registry import ToolRegistry
    from tests.support import ToolThenTextProvider

    box: dict = {}
    tool = _RecordingTool("stopper", harness_box=box)
    registry = ToolRegistry()
    registry.register(tool)

    provider = ToolThenTextProvider(ToolCall(id="a", name="stopper", arguments={}), reply="done")
    harness = Harness(_config(), provider=provider, memory=None, registry=registry)
    box["harness"] = harness
    recorder = _CapturingRecorder()
    harness.recorder = recorder
    state = harness.new_session()

    streamed = "".join(d.text for d in harness.run_turn("go", state) if d.text)

    assert provider.calls == 1                    # the follow-up model call never happened
    assert "done" not in streamed
    assert streamed.endswith("[cancelled]\n")
    assert _turn_end(recorder)["status"] == "cancelled"


def test_cancel_mid_stream_closes_the_provider_generator():
    """A cancel raised while the model is still streaming stops it and closes the generator."""

    class _LongStream(ModelProvider):
        name = "longstream"

        def __init__(self) -> None:
            self.model = "fake:long"
            self.closed = False
            self.emitted = 0
            self.harness: Harness | None = None

        def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
            try:
                for i in range(50):
                    self.emitted += 1
                    if i == 1 and self.harness is not None:
                        self.harness.cancel()
                    yield CompletionDelta(text=f"chunk{i} ")
                yield CompletionDelta(  # pragma: no cover - cancel lands first
                    done=True,
                    completion=Completion(
                        text="all", usage=Usage(input_tokens=1, output_tokens=1),
                        model=self.model,
                    ),
                )
            finally:
                self.closed = True

    provider = _LongStream()
    harness = Harness(_config(), provider=provider, memory=None)
    provider.harness = harness
    recorder = _CapturingRecorder()
    harness.recorder = recorder
    state = harness.new_session()

    streamed = "".join(d.text for d in harness.run_turn("go", state) if d.text)

    assert provider.emitted < 50                  # stopped early, mid-stream
    assert provider.closed is True                # the generator's finally ran
    assert streamed.endswith("[cancelled]\n")
    assert _turn_end(recorder)["status"] == "cancelled"


# ---- the step budget is the configured one --------------------------------- #


class _AlwaysToolProvider(ModelProvider):
    """Never stops asking for a tool, so the turn runs until a bound trips."""

    name = "always"

    def __init__(self, tool: str = "ping"):
        self.model = "fake:always"
        self.tool = tool
        self.calls = 0

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        self.calls += 1
        call = ToolCall(id=f"c{self.calls}", name=self.tool, arguments={})
        yield CompletionDelta(
            done=True,
            completion=Completion(
                text="", tool_calls=[call], usage=Usage(input_tokens=1, output_tokens=1),
                model=self.model, stop_reason="tool_use",
            ),
        )


def _stepping_harness(max_steps: int):
    from agent86.tools.registry import ToolRegistry

    cfg = _config()
    cfg.limits.max_steps = max_steps
    registry = ToolRegistry()
    registry.register(_RecordingTool("ping"))
    provider = _AlwaysToolProvider()
    harness = Harness(cfg, provider=provider, memory=None, registry=registry)
    harness.recorder = _CapturingRecorder()
    return harness, provider


def test_turn_step_budget_is_the_configured_limit():
    from agent86.orchestration.loop import HarnessError

    harness, provider = _stepping_harness(3)
    state = harness.new_session()

    with pytest.raises(HarnessError, match="step budget reached"):
        list(harness.run_turn("go", state))

    assert provider.calls == 3  # tripped at limits.max_steps, not at some hidden constant
    assert state.phase is AgentPhase.ERROR


def test_turn_step_budget_above_twelve_is_honoured():
    """Regression: a private _MAX_TURN_STEPS=12 silently capped `limits.max_steps`."""
    from agent86.orchestration.loop import HarnessError

    harness, provider = _stepping_harness(14)
    state = harness.new_session()

    with pytest.raises(HarnessError, match="step budget reached"):
        list(harness.run_turn("go", state))

    assert provider.calls == 14


# ---- provider failure mid-stream ------------------------------------------- #


class _FailingStreamProvider(ModelProvider):
    """Streams one delta, then blows up the way a dropped connection does."""

    name = "failing"

    def __init__(self, exc: BaseException):
        self.model = "fake:failing"
        self._exc = exc
        self.closed = False

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        try:
            yield CompletionDelta(text="partial ")
            raise self._exc
        finally:
            self.closed = True


def _failing_harness(exc: BaseException):
    provider = _FailingStreamProvider(exc)
    harness = Harness(_config(), provider=provider, memory=None)
    recorder = _CapturingRecorder()
    harness.recorder = recorder
    persisted: list[int] = []
    original = harness._persist

    def _spy(state) -> None:
        persisted.append(len(state.messages))
        original(state)

    harness._persist = _spy
    return harness, provider, recorder, persisted


def test_provider_error_mid_stream_aborts_the_turn_cleanly():
    from agent86.cognitive.base import ProviderError

    harness, provider, recorder, persisted = _failing_harness(ProviderError("stream died"))
    state = harness.new_session()

    with pytest.raises(ProviderError, match="stream died"):
        list(harness.run_turn("hi", state))

    # The user message survives, the phase is ERROR, and the turn was persisted + recorded.
    assert [m.role for m in state.messages] == [Role.USER]
    assert state.phase is AgentPhase.ERROR
    end = _turn_end(recorder)
    assert end["status"] == "error"
    assert "stream died" in end["reason"]
    assert persisted[-1] == 1  # persisted AFTER the user message was appended
    assert provider.closed is True


def test_raw_stream_exception_is_wrapped_as_provider_error():
    import httpx

    from agent86.cognitive.base import ProviderError

    harness, _provider, recorder, _ = _failing_harness(httpx.RemoteProtocolError("peer closed"))
    state = harness.new_session()

    with pytest.raises(ProviderError) as excinfo:
        list(harness.run_turn("hi", state))

    assert "RemoteProtocolError" in str(excinfo.value)
    assert "fake:failing" in str(excinfo.value)
    assert state.phase is AgentPhase.ERROR
    assert _turn_end(recorder)["status"] == "error"


def test_stream_without_final_completion_aborts_the_turn():
    from agent86.orchestration.loop import HarnessError

    class _NoFinal(ModelProvider):
        name = "nofinal"
        model = "fake:nofinal"

        def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
            yield CompletionDelta(text="orphan")

    harness = Harness(_config(), provider=_NoFinal(), memory=None)
    recorder = _CapturingRecorder()
    harness.recorder = recorder
    state = harness.new_session()

    with pytest.raises(HarnessError, match="without a final completion"):
        list(harness.run_turn("hi", state))

    assert state.phase is AgentPhase.ERROR
    assert _turn_end(recorder)["status"] == "error"


def test_cancel_at_idle_does_not_poison_the_next_turn():
    """`cancel()` with no turn running is a no-op — run_turn clears the flag on entry."""
    harness = Harness(_config(), provider=FakeProvider(), memory=None)
    harness.cancel()
    assert harness.cancelled is True

    state = harness.new_session()
    streamed = "".join(d.text for d in harness.run_turn("hi", state) if d.text)

    assert "hello there" in streamed
    assert "[cancelled]" not in streamed
    assert state.phase is AgentPhase.DONE


# ---- per-turn summary (state.last_turn) ------------------------------------ #


def test_turn_summary_is_recorded_on_a_completed_turn():
    harness = Harness(_config(), provider=FakeProvider(), memory=None)
    state = harness.new_session()
    assert state.last_turn is None

    list(harness.run_turn("hi", state))

    summary = state.last_turn
    assert summary is not None
    assert summary.input_tokens == 11
    assert summary.output_tokens == 5
    assert summary.steps == 1
    assert summary.tool_calls == 0
    assert summary.compactions == 0
    assert summary.continuations == 0
    assert summary.duration_s >= 0.0
    # Providers without cache accounting leave these at zero rather than crashing.
    assert summary.cache_read_tokens == 0
    assert summary.cache_creation_tokens == 0


def test_turn_summary_counts_tool_calls_and_survives_cancellation():
    from agent86.tools.registry import ToolRegistry

    box: dict = {}
    registry = ToolRegistry()
    registry.register(_RecordingTool("stopper", harness_box=box))

    provider = _TwoToolCallProvider([ToolCall(id="a", name="stopper", arguments={})])
    harness = Harness(_config(), provider=provider, memory=None, registry=registry)
    box["harness"] = harness
    state = harness.new_session()

    list(harness.run_turn("go", state))

    assert state.last_turn is not None
    assert state.last_turn.tool_calls == 1
    assert state.last_turn.steps == 1


def test_turn_summary_survives_a_json_round_trip():
    from agent86.orchestration.state import AgentState

    harness = Harness(_config(), provider=FakeProvider(), memory=None)
    state = harness.new_session()
    list(harness.run_turn("hi", state))

    revived = AgentState.model_validate_json(state.model_dump_json())
    assert revived.last_turn is not None
    assert revived.last_turn.output_tokens == 5


# ---- the context budget comes from the real window ------------------------- #


class _WindowProbe(ModelProvider):
    """Captures the request so the resolved budget can be inspected."""

    name = "anthropic"

    def __init__(self, model: str = "claude-opus-4-8"):
        self.model = model
        self.requests: list[CompletionRequest] = []

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        self.requests.append(request)
        yield CompletionDelta(
            done=True,
            completion=Completion(
                text="ok", usage=Usage(), model=self.model, stop_reason="end_turn"
            ),
        )


def test_context_budget_uses_the_model_window_not_a_flat_8000():
    harness = Harness(_config(), provider=_WindowProbe(), memory=None)
    state = harness.new_session()
    list(harness.run_turn("hi", state))

    # A 200k Claude window, minus the system prompt + tool schemas + reserve + output cap —
    # emphatically not the old flat 8000.
    assert harness.working.max_tokens > 150_000


def test_context_budget_honours_the_config_override_and_the_hard_cap():
    cfg = _config()
    cfg.model.context_window = {"anthropic:claude-opus-4-8": 32_768}
    harness = Harness(cfg, provider=_WindowProbe(), memory=None)
    list(harness.run_turn("hi", harness.new_session()))
    override_budget = harness.working.max_tokens
    assert 10_000 < override_budget < 32_768

    cfg.limits.max_context_tokens = 5_000  # an explicit hard cap wins over the derived budget
    harness = Harness(cfg, provider=_WindowProbe(), memory=None)
    list(harness.run_turn("hi", harness.new_session()))
    assert harness.working.max_tokens == 5_000


def test_request_carries_the_resolved_max_tokens():
    cfg = _config()
    cfg.providers["anthropic"].max_tokens = 3_000
    provider = _WindowProbe()
    harness = Harness(cfg, provider=provider, memory=None)
    list(harness.run_turn("hi", harness.new_session()))

    assert provider.requests[0].max_tokens == 3_000


# ---- max_tokens continuation ----------------------------------------------- #


def _partial(text: str, stop: str) -> Completion:
    return Completion(
        text=text, usage=Usage(input_tokens=4, output_tokens=2), stop_reason=stop
    )


def test_max_tokens_stop_is_continued_and_stitched_back_together():
    from tests.support import ScriptedProvider

    provider = ScriptedProvider(
        [
            _partial("one ", "max_tokens"),
            _partial("two ", "max_tokens"),
            _partial("three", "end_turn"),
        ]
    )
    harness = Harness(_config(), provider=provider, memory=None)
    recorder = _CapturingRecorder()
    harness.recorder = recorder
    state = harness.new_session()

    streamed = "".join(d.text for d in harness.run_turn("write a long thing", state) if d.text)

    # Every piece reached the user as it streamed ...
    assert streamed == "one two three"
    assert provider.calls == 3
    # ... and the history holds ONE assistant answer, not three partials and two prompts.
    assert [m.role for m in state.messages] == [Role.USER, Role.ASSISTANT]
    assert state.messages[-1].content == "one two three"
    # The harness's own continuation prompt never survives into the history.
    assert all("Continue exactly where" not in m.content for m in state.messages)

    events = [d for _s, k, d in recorder.events if k == "continuation"]
    assert [e["index"] for e in events] == [1, 2]
    assert state.last_turn is not None and state.last_turn.continuations == 2
    assert state.last_turn.steps == 3  # each continuation is a step the breaker counted


def test_continuations_are_bounded():
    from agent86.orchestration.loop import MAX_CONTINUATIONS
    from tests.support import ScriptedProvider

    provider = ScriptedProvider([_partial("chunk ", "max_tokens")])  # never stops
    harness = Harness(_config(), provider=provider, memory=None)
    state = harness.new_session()

    list(harness.run_turn("go", state))

    assert provider.calls == MAX_CONTINUATIONS + 1
    assert state.phase is AgentPhase.DONE
    assert state.messages[-1].content == "chunk " * (MAX_CONTINUATIONS + 1)


def test_a_normal_stop_reason_is_not_continued():
    from tests.support import ScriptedProvider

    provider = ScriptedProvider([_partial("done", "end_turn")])
    harness = Harness(_config(), provider=provider, memory=None)
    state = harness.new_session()

    list(harness.run_turn("go", state))

    assert provider.calls == 1
    assert state.last_turn is not None and state.last_turn.continuations == 0


def test_a_truncated_step_that_then_calls_a_tool_keeps_its_real_history():
    """Continuation stitching must never rewrite a message a tool result attaches to."""
    from agent86.tools.registry import ToolRegistry
    from tests.support import ScriptedProvider

    registry = ToolRegistry()
    registry.register(_RecordingTool("probe"))
    provider = ScriptedProvider(
        [
            _partial("thinking ", "max_tokens"),
            Completion(
                text="",
                tool_calls=[ToolCall(id="t1", name="probe", arguments={})],
                usage=Usage(),
                stop_reason="tool_use",
            ),
            _partial("finished", "end_turn"),
        ]
    )
    harness = Harness(_config(), provider=provider, memory=None, registry=registry)
    state = harness.new_session()

    list(harness.run_turn("go", state))

    roles = [m.role for m in state.messages]
    assert Role.TOOL in roles
    # The tool result still follows the assistant message that requested it.
    tool_idx = roles.index(Role.TOOL)
    assert roles[tool_idx - 1] is Role.ASSISTANT
    assert state.messages[tool_idx - 1].tool_calls[0].id == "t1"
