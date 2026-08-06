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
