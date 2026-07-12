"""Phase 8 — multi-agent: envelopes, broker, sub-agents, delegate tool, orchestrator."""

from __future__ import annotations

from collections.abc import Iterator

from agent86.agents.broker import MessageBus
from agent86.agents.envelope import AgentMessage, Intent
from agent86.agents.orchestrator import SupervisorOrchestrator
from agent86.agents.subagent import SubAgent
from agent86.cognitive.base import ModelProvider
from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.types import (
    ApprovalMode,
    Completion,
    CompletionDelta,
    CompletionRequest,
    Role,
    ToolCall,
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
    assert SubAgent(h, "worker", depth=1).run("do a thing") == "sub answer"


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
