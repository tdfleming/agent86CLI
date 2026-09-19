"""Phase 8 — multi-agent: envelopes, broker, sub-agents, delegate tool, orchestrator."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agent86.agents.broker import MessageBus
from agent86.agents.envelope import AgentMessage, Intent
from agent86.agents.orchestrator import SupervisorOrchestrator
from agent86.agents.subagent import DEFAULT_SUB_MAX_STEPS, SubAgent
from agent86.cognitive.base import ModelProvider
from agent86.cognitive.prompt import build_system_prompt
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.types import (
    ApprovalMode,
    Completion,
    CompletionDelta,
    CompletionRequest,
    Role,
    ToolCall,
    ToolResult,
    Usage,
)
from tests.support import make_text_provider

# ---- envelope + broker ------------------------------------------------- #


def test_envelope_reply_correlates():
    m = AgentMessage(sender="sup", recipient="worker", intent=Intent.REQUEST, content="do it")
    reply = m.reply("done")
    assert reply.sender == "worker" and reply.recipient == "sup"
    assert reply.intent == Intent.RESPONSE
    assert reply.correlation_id == m.correlation_id


def test_message_bus():
    bus = MessageBus()
    m = AgentMessage("s", "r", Intent.INFORM, "x")
    bus.send(m)
    assert bus.pending("r") == 1
    assert bus.receive("r") is m
    assert bus.receive("r") is None
    bus.send(m)
    assert bus.drain("r") == [m]
    assert len(bus.history) == 2


# ---- sub-agent --------------------------------------------------------- #


def _cfg():
    cfg = load_config()
    cfg.guardrails.approval = ApprovalMode.AUTO
    return cfg


def test_subagent_runs_and_returns(tmp_path):
    h = Harness(_cfg(), provider=make_text_provider("sub answer"), memory=None, workspace=tmp_path)
    text, usage = SubAgent(h, "worker", depth=1).run("do a thing")
    assert text == "sub answer"
    # run() reports what it spent, so the parent turn can be charged for it.
    assert usage.input_tokens == 3 and usage.output_tokens == 2


def test_spawn_depth_guard(tmp_path):
    cfg = _cfg()
    cfg.agents.max_depth = 1
    h = Harness(cfg, provider=make_text_provider("x"), memory=None, workspace=tmp_path)
    assert "max agent depth" in h.spawn_subagent("r", "t", depth=2)


# ---- orchestrator ------------------------------------------------------ #


def test_orchestrator_fan_out(tmp_path):
    h = Harness(_cfg(), provider=make_text_provider("done"), memory=None, workspace=tmp_path)
    orch = SupervisorOrchestrator(h)
    replies = orch.fan_out([("researcher", "task a"), ("writer", "task b")])
    assert len(replies) == 2
    assert all(r.intent == Intent.RESPONSE for r in replies)
    assert replies[0].content == "done"
    assert replies[0].sender == "researcher"
    assert len(orch.bus.history) == 4  # 2 requests + 2 responses


# ---- delegate tool wired into the main loop ---------------------------- #


class DelegatingProvider(ModelProvider):
    """Main call 1 -> delegate; sub call -> result; main call 2 -> final answer."""

    name = "deleg"

    def __init__(self, model: str = "fake:deleg"):
        self.model = model
        self.calls = 0

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        self.calls += 1
        if self.calls == 1:
            tc = ToolCall(id="d1", name="delegate",
                          arguments={"role": "worker", "task": "do subtask"})
            completion = Completion(text="", tool_calls=[tc], usage=Usage(), model=self.model)
        elif self.calls == 2:
            completion = Completion(text="subtask result", usage=Usage(), model=self.model)
        else:
            completion = Completion(text="all done", usage=Usage(), model=self.model)
        yield CompletionDelta(done=True, completion=completion)


def test_delegate_tool_spawns_subagent(tmp_path):
    provider = DelegatingProvider()
    h = Harness(_cfg(), provider=provider, memory=None, workspace=tmp_path)
    assert "delegate" in h.registry.names()

    state = h.new_session()
    list(h.run_turn("delegate a subtask then finish", state))

    assert provider.calls == 3  # main, sub, main-final
    assert state.messages[-1].content == "all done"
    tool_msgs = [m for m in state.messages if m.role == Role.TOOL and m.name == "delegate"]
    assert tool_msgs and tool_msgs[0].content == "subtask result"


# ---- sub-agent accountability (v0.7 task 4) ---------------------------- #


class CostlyDelegatingProvider(ModelProvider):
    """Main call 1 -> delegate; the SUB-agent's call (2) is the expensive one; 3 -> answer."""

    name = "costdeleg"

    def __init__(self, cost: float = 0.25, model: str = "fake:costdeleg"):
        self.model = model
        self.cost = cost
        self.calls = 0

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        self.calls += 1
        if self.calls == 1:
            tc = ToolCall(id="d1", name="delegate",
                          arguments={"role": "worker", "task": "do subtask"})
            completion = Completion(text="", tool_calls=[tc], usage=Usage(), model=self.model)
        elif self.calls == 2:
            completion = Completion(
                text="subtask result",
                usage=Usage(input_tokens=10, output_tokens=4, cost_usd=self.cost),
                model=self.model,
            )
        else:
            completion = Completion(text="all done", usage=Usage(), model=self.model)
        yield CompletionDelta(done=True, completion=completion)


class LoopingToolProvider(ModelProvider):
    """Always asks for the same tool again — used to prove a step cap actually fires."""

    name = "loopy"

    def __init__(self, tool: str, model: str = "fake:loopy"):
        self.model = model
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


def _noop_registry(name: str = "ping"):
    """A registry holding one cheap, always-approved tool."""
    from agent86.tools.base import EmptyArgs, Tool
    from agent86.tools.registry import ToolRegistry
    from agent86.types import ToolSpec

    class _Ping(Tool[EmptyArgs]):
        Args = EmptyArgs

        def __init__(self) -> None:
            self.name = name
            self.description = "no-op"
            self.side_effecting = False

        def spec(self) -> ToolSpec:
            return ToolSpec(name=self.name, description=self.description,
                            parameters={"type": "object", "properties": {}})

        def execute(self, args: EmptyArgs, ctx) -> ToolResult:
            return ToolResult(call_id="", name=self.name, content="pong")

    registry = ToolRegistry()
    registry.register(_Ping())
    return registry


def test_subagent_usage_lands_in_the_parent_turn(tmp_path):
    """Delegation must not be a blind spot in the turn's cost accounting."""
    provider = CostlyDelegatingProvider(cost=0.25)
    h = Harness(_cfg(), provider=provider, memory=None, workspace=tmp_path)
    state = h.new_session()

    list(h.run_turn("delegate a subtask then finish", state))

    assert provider.calls == 3
    assert state.usage.cost_usd == 0.25           # the sub-agent's spend, on the parent turn
    assert state.usage.input_tokens == 10
    assert state.steps[0].usage.cost_usd == 0.25  # attributed to the delegating step


def test_subagent_step_cap_comes_from_config(tmp_path):
    cfg = _cfg()
    if not hasattr(cfg.agents, "max_steps"):
        pytest.skip("config.agents.max_steps has not landed yet")
    cfg.agents.max_steps = 2

    provider = LoopingToolProvider("ping")
    h = Harness(cfg, provider=provider, memory=None, workspace=tmp_path,
                registry=_noop_registry())
    text, usage = SubAgent(h, "worker", depth=1).run("loop forever")

    assert "halted" in text and "step budget" in text
    assert provider.calls == 2       # exactly the configured cap, not the old hard-coded 8
    assert usage.output_tokens == 2  # both calls are still charged


def test_subagent_step_cap_defaults_when_config_is_silent(tmp_path):
    provider = LoopingToolProvider("ping")
    h = Harness(_cfg(), provider=provider, memory=None, workspace=tmp_path,
                registry=_noop_registry())
    agent = SubAgent(h, "worker", depth=1)
    assert agent.max_steps == getattr(h.config.agents, "max_steps", DEFAULT_SUB_MAX_STEPS)

    text, _usage = agent.run("loop forever")

    assert "halted" in text
    assert provider.calls == agent.max_steps


def test_subagent_system_prompt_carries_the_skills_list(tmp_path):
    h = Harness(_cfg(), provider=make_text_provider("ok"), memory=None, workspace=tmp_path)
    h.skills = {"pdf": _fake_skill(tmp_path)}
    h.system_prompt = build_system_prompt(h.config, h.skills)

    system = SubAgent(h, "researcher", depth=1)._system()

    assert "'researcher' sub-agent" in system.content  # the role preamble comes first
    assert "pdf: work with PDFs" in system.content     # and the parent's skills survive


def _fake_skill(tmp_path):
    from agent86.skills.models import Skill

    return Skill(name="pdf", description="work with PDFs", path=tmp_path / "SKILL.md")


def test_subagent_trims_its_own_context(tmp_path):
    """A sub-agent that ran many tools must not blow the context window on its last call."""
    provider = LoopingToolProvider("ping")
    cfg = _cfg()
    cfg.limits.max_context_tokens = 20  # tiny budget: the trim has to bite immediately
    h = Harness(cfg, provider=provider, memory=None, workspace=tmp_path,
                registry=_noop_registry())
    requests = []
    real_complete = provider.complete

    def _spy(request):
        requests.append(request)
        return real_complete(request)

    provider.complete = _spy
    long_task = "x" * 400

    SubAgent(h, "worker", depth=1).run(long_task)

    # The oversized opening turn is dropped once it no longer fits ...
    assert any(m.content == long_task for m in requests[0].messages)
    assert not any(m.content == long_task for m in requests[-1].messages)
    # ... but the system prompt is held out of the trim and always survives.
    assert all(r.messages[0].role is Role.SYSTEM for r in requests)


def test_subagent_records_model_calls_with_role_and_depth(tmp_path):
    events: list[tuple[str, str, dict]] = []

    class _Rec:
        def event(self, session_id, kind, **data):
            events.append((session_id, kind, dict(data)))

        def close(self):
            pass

    h = Harness(_cfg(), provider=make_text_provider("sub answer"), memory=None,
                workspace=tmp_path)
    h.recorder = _Rec()

    SubAgent(h, "worker", depth=2).run("do a thing")

    calls = [d for _, kind, d in events if kind == "model_call"]
    assert calls and calls[0]["agent"] == "worker" and calls[0]["depth"] == 2
