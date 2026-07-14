"""v0.5 — MCP client surfaces that don't need the `mcp` package or a live server.

Covers MCPTool (spec from the server schema, run success/failure) and the MCPManager /
build_mcp degradation paths — the previously thin `tools/mcp_client.py`.
"""

from __future__ import annotations

from agent86.config import load_config
from agent86.tools.mcp_client import MCPManager, MCPTool, build_mcp
from agent86.types import ToolCall


class _FakeManager:
    def __init__(self, result: str | None = None, error: Exception | None = None):
        self._result = result
        self._error = error

    def call_tool(self, server: str, tool: str, arguments: dict) -> str:
        if self._error is not None:
            raise self._error
        return self._result or ""


def test_mcp_tool_spec_uses_server_schema():
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    tool = MCPTool(_FakeManager(), "srv", "mytool", "does a thing", schema)
    spec = tool.spec()
    assert spec.name == "mcp__srv__mytool"
    assert spec.parameters["properties"] == {"x": {"type": "string"}}
    assert spec.side_effecting is True  # external effects -> approval-gated


def test_mcp_tool_run_returns_server_content():
    tool = MCPTool(_FakeManager(result="hello from server"), "srv", "mytool", "d", {})
    res = tool.run(ToolCall(id="1", name=tool.name, arguments={"x": "y"}), ctx=None)  # ctx unused
    assert res.ok and res.content == "hello from server"


def test_mcp_tool_run_wraps_failures_as_soft_error():
    tool = MCPTool(_FakeManager(error=RuntimeError("boom")), "srv", "mytool", "d", {})
    res = tool.run(ToolCall(id="1", name=tool.name, arguments={}), ctx=None)
    assert not res.ok and "boom" in (res.error or "")


def test_mcp_manager_no_servers_is_noop():
    manager = MCPManager({})
    manager.start()  # early-returns; must not import mcp or raise
    assert manager.tools() == []
    assert manager.note is None


def test_build_mcp_returns_none_without_servers():
    # Default config declares no MCP servers -> nothing to manage.
    assert build_mcp(load_config()) is None
