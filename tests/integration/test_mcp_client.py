"""v0.5 — MCP client surfaces that don't need the `mcp` package or a live server.

Covers MCPTool (spec from the server schema, run success/failure) and the MCPManager /
build_mcp degradation paths — the previously thin `tools/mcp_client.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent86.config import Config, MCPServerConfig, load_config
from agent86.tools.mcp_client import MCPManager, MCPTool, build_mcp
from agent86.types import ToolCall

try:
    import mcp.server.fastmcp  # noqa: F401

    _HAS_FASTMCP = True
except ImportError:
    _HAS_FASTMCP = False


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


# --- Wave 0 scaffold for plan 04-04: real-stdio per-server lifecycle (D-23 regression guard) - #
#
# Requires the `mcp` extra (FastMCP server). Guarded by a module-level boolean + skipif, never a
# module-level `pytest.importorskip` — that would skip the mock-only tests above.

_SERVER = Path(__file__).with_name("live_mcp_server.py")


def _stdio_cfg() -> MCPServerConfig:
    return MCPServerConfig(command=sys.executable, args=[str(_SERVER), "stdio", "0"])


@pytest.mark.skipif(not _HAS_FASTMCP, reason="requires the 'mcp' extra")
def test_per_server_start_lists_real_tools():
    manager = MCPManager({})
    try:
        tools = manager.start_server("alpha", _stdio_cfg(), timeout=30.0)
        assert {t._tool for t in tools} == {"add", "shout"}
        assert all(t.name.startswith("mcp__alpha__") for t in tools)
    finally:
        manager.close()


@pytest.mark.skipif(not _HAS_FASTMCP, reason="requires the 'mcp' extra")
def test_per_server_call_tool_round_trip():
    manager = MCPManager({})
    try:
        manager.start_server("alpha", _stdio_cfg(), timeout=30.0)
        result = manager.call_tool("alpha", "add", {"a": 2, "b": 3})
        assert "5" in result
    finally:
        manager.close()


@pytest.mark.skipif(not _HAS_FASTMCP, reason="requires the 'mcp' extra")
def test_independent_teardown_leaves_other_server_intact():
    """The highest-value test in the phase (D-23): stopping one server must not tear down
    another server's session via a cross-task cancel scope."""
    manager = MCPManager({})
    try:
        manager.start_server("alpha", _stdio_cfg(), timeout=30.0)
        manager.start_server("beta", _stdio_cfg(), timeout=30.0)

        try:
            manager.stop_server("alpha")
        except RuntimeError as exc:
            text = str(exc)
            assert "cancel scope" not in text
            assert "different task" not in text
            raise

        assert manager.tools_for("alpha") == []
        assert "alpha" not in manager._sessions

        assert "2" in manager.call_tool("beta", "add", {"a": 1, "b": 1})

        with pytest.raises(RuntimeError):
            manager.call_tool("alpha", "add", {"a": 1, "b": 1})
    finally:
        manager.close()


@pytest.mark.skipif(not _HAS_FASTMCP, reason="requires the 'mcp' extra")
def test_close_after_partial_stop_is_clean():
    manager = MCPManager({})
    try:
        manager.start_server("alpha", _stdio_cfg(), timeout=30.0)
        manager.start_server("beta", _stdio_cfg(), timeout=30.0)
        manager.stop_server("alpha")
    finally:
        manager.close()
    assert manager._loop is None


@pytest.mark.skipif(not _HAS_FASTMCP, reason="requires the 'mcp' extra")
def test_start_server_failure_does_not_break_manager():
    manager = MCPManager({})
    try:
        bad_cfg = MCPServerConfig(command=sys.executable, args=["-c", "import sys; sys.exit(1)"])
        with pytest.raises(Exception):
            manager.start_server("bad", bad_cfg, timeout=30.0)
        manager.start_server("alpha", _stdio_cfg(), timeout=30.0)
    finally:
        manager.close()
