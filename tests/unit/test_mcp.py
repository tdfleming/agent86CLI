"""Phase 6 — MCP client wiring (no live server)."""

from __future__ import annotations

import pytest

from agent86.config import MCPServerConfig, load_config
from agent86.tools.mcp_client import MCPManager, MCPTool, _open_transport, _sanitize, build_mcp
from agent86.types import ToolCall


def test_build_mcp_none_without_servers():
    assert build_mcp(load_config()) is None


def test_manager_start_is_noop_without_servers():
    m = MCPManager({})
    m.start()
    assert m.tools() == []
    m.close()


def test_sanitize_tool_name():
    assert _sanitize("my server.do/thing") == "my_server_do_thing"


def test_mcp_tool_name_and_delegation():
    class FakeManager:
        def __init__(self):
            self.called = None

        def call_tool(self, server, tool, arguments):
            self.called = (server, tool, arguments)
            return "result text"

    mgr = FakeManager()
    schema = {"type": "object", "properties": {}}
    tool = MCPTool(mgr, "myserver", "do_thing", "does a thing", schema)
    assert tool.name == "mcp__myserver__do_thing"
    assert tool.spec().side_effecting is True

    res = tool.run(ToolCall(id="1", name=tool.name, arguments={"x": 1}), ctx=None)
    assert res.ok and res.content == "result text"
    assert mgr.called == ("myserver", "do_thing", {"x": 1})


def test_mcp_tool_run_handles_error():
    class FailManager:
        def call_tool(self, *a):
            raise RuntimeError("boom")

    tool = MCPTool(FailManager(), "s", "t", "", {})
    res = tool.run(ToolCall(id="1", name="x", arguments={}), ctx=None)
    assert not res.ok and "boom" in (res.error or "")


# --- transport config: inference & validation ------------------------------- #


def test_transport_defaults_to_stdio_for_command():
    assert MCPServerConfig(command="mcp-server").transport == "stdio"


def test_transport_defaults_to_http_for_url():
    assert MCPServerConfig(url="https://example.com/mcp").transport == "http"


def test_transport_streamable_http_alias_normalizes():
    cfg = MCPServerConfig(url="https://x/mcp", transport="streamable-http")
    assert cfg.transport == "http"


def test_transport_sse_explicit():
    assert MCPServerConfig(url="https://x/sse", transport="sse").transport == "sse"


def test_rejects_both_command_and_url():
    with pytest.raises(ValueError, match="both"):
        MCPServerConfig(command="x", url="https://y/mcp")


def test_rejects_neither_command_nor_url():
    with pytest.raises(ValueError, match="command.*stdio.*url|url.*sse"):
        MCPServerConfig()


def test_rejects_unknown_transport():
    with pytest.raises(ValueError, match="unknown MCP transport"):
        MCPServerConfig(url="https://x", transport="carrier-pigeon")


def test_rejects_stdio_without_command():
    with pytest.raises(ValueError):
        MCPServerConfig(url="https://x", transport="stdio")


def test_rejects_http_without_url():
    with pytest.raises(ValueError):
        MCPServerConfig(command="x", transport="http")


def test_open_transport_selects_client_per_transport():
    # stdio -> a stdio_client context manager; url transports -> their respective clients.
    stdio_cm = _open_transport(MCPServerConfig(command="echo", args=["hi"]))
    assert "stdio" in type(stdio_cm).__module__ or hasattr(stdio_cm, "__aenter__")

    sse_cm = _open_transport(MCPServerConfig(url="https://x/sse", transport="sse"))
    assert hasattr(sse_cm, "__aenter__")

    http_cm = _open_transport(MCPServerConfig(url="https://x/mcp", transport="http"))
    assert hasattr(http_cm, "__aenter__")


# --- Wave 0 scaffolds: ToolRegistry.unregister + per-server MCPManager lifecycle (MCP-01) ----- #


def test_registry_unregister_removes_a_tool():
    from agent86.tools.registry import ToolRegistry

    registry = ToolRegistry()
    tool = MCPTool(FakeManager(), "srv", "do_thing", "does a thing", {})
    registry.register(tool)
    assert registry.unregister(tool.name) is True
    assert tool.name not in registry.names()
    assert registry.get(tool.name) is None


def test_registry_unregister_unknown_returns_false():
    from agent86.tools.registry import ToolRegistry

    registry = ToolRegistry()
    assert registry.unregister("nope") is False


class FakeManager:
    def __init__(self):
        self.called = None

    def call_tool(self, server, tool, arguments):
        self.called = (server, tool, arguments)
        return "result text"


def test_manager_start_server_registers_tools_for_lookup(monkeypatch):
    import agent86.tools.mcp_client as mcp_client
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_open_transport(cfg):
        yield (object(), object())

    class _FakeTool:
        def __init__(self, name):
            self.name = name
            self.description = f"does {name}"
            self.inputSchema = {}

    class _FakeListed:
        tools = [_FakeTool("alpha"), _FakeTool("beta")]

    class _FakeSession:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def initialize(self):
            return None

        async def list_tools(self):
            return _FakeListed()

    monkeypatch.setattr(mcp_client, "_open_transport", _fake_open_transport)
    monkeypatch.setattr(mcp_client, "ClientSession", _FakeSession, raising=False)

    manager = MCPManager({})
    cfg = MCPServerConfig(command="npx")
    tools = manager.start_server("srv", cfg)
    assert len(tools) == 2
    assert {t.name for t in tools} == {t.name for t in manager.tools_for("srv")}


def test_manager_stop_server_drops_its_tools(monkeypatch):
    import agent86.tools.mcp_client as mcp_client
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_open_transport(cfg):
        yield (object(), object())

    class _FakeTool:
        def __init__(self, name):
            self.name = name
            self.description = f"does {name}"
            self.inputSchema = {}

    class _FakeListed:
        tools = [_FakeTool("alpha")]

    class _FakeSession:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def initialize(self):
            return None

        async def list_tools(self):
            return _FakeListed()

    monkeypatch.setattr(mcp_client, "_open_transport", _fake_open_transport)
    monkeypatch.setattr(mcp_client, "ClientSession", _FakeSession, raising=False)

    manager = MCPManager({})
    cfg = MCPServerConfig(command="npx")
    manager.start_server("srv", cfg)
    manager.stop_server("srv")
    assert manager.tools_for("srv") == []
    assert "srv" not in manager._sessions


def test_manager_start_server_without_mcp_package_raises_with_note(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *a, **k):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("no module named mcp")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    manager = MCPManager({})
    cfg = MCPServerConfig(command="npx")
    with pytest.raises(RuntimeError):
        manager.start_server("srv", cfg)
    assert manager.note is not None and 'pip install "agent86[mcp]"' in manager.note


# --- ${VAR} resolution at the transport boundary (D-17/D-25, plan 04-04) --------------------- #


def test_resolve_server_secrets_expands_env_and_headers(monkeypatch):
    from agent86.tools.mcp_client import _resolve_server_secrets

    monkeypatch.setenv("A86_T", "sekret")
    cfg = MCPServerConfig(
        command="npx",
        env={"TOKEN": "${A86_T}"},
        headers={"Authorization": "Bearer ${A86_T}"},
    )
    resolved = _resolve_server_secrets(cfg)
    assert resolved.env == {"TOKEN": "sekret"}
    assert resolved.headers == {"Authorization": "Bearer sekret"}
    # original cfg is untouched
    assert cfg.env == {"TOKEN": "${A86_T}"}
    assert cfg.headers == {"Authorization": "Bearer ${A86_T}"}


def test_resolve_server_secrets_never_expands_command(monkeypatch):
    from agent86.tools.mcp_client import _resolve_server_secrets

    monkeypatch.setenv("A86_T", "sekret")
    cfg = MCPServerConfig(command="${A86_T}")
    resolved = _resolve_server_secrets(cfg)
    assert resolved.command == "${A86_T}"


def test_resolve_server_secrets_overrides_win(monkeypatch):
    from agent86.tools.mcp_client import _resolve_server_secrets

    monkeypatch.setenv("A86_T", "from-env")
    cfg = MCPServerConfig(command="npx", env={"TOKEN": "${A86_T}"})
    resolved = _resolve_server_secrets(cfg, overrides={"A86_T": "typed"})
    assert resolved.env == {"TOKEN": "typed"}


def test_resolve_server_secrets_missing_raises(monkeypatch):
    from agent86.secrets import MissingSecretRef
    from agent86.tools.mcp_client import _resolve_server_secrets

    monkeypatch.delenv("A86_MISSING", raising=False)
    cfg = MCPServerConfig(command="npx", env={"TOKEN": "${A86_MISSING}"})
    with pytest.raises(MissingSecretRef):
        _resolve_server_secrets(cfg)


def test_unresolved_var_refs_lists_only_missing_names(monkeypatch):
    from agent86.tools.mcp_client import unresolved_var_refs

    monkeypatch.setenv("A86_HAVE", "yes")
    monkeypatch.delenv("A86_MISSING", raising=False)
    cfg = MCPServerConfig(
        command="npx",
        env={"A": "${A86_HAVE}"},
        headers={"Authorization": "Bearer ${A86_MISSING}"},
    )
    assert unresolved_var_refs(cfg) == ["A86_MISSING"]
