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
    from contextlib import asynccontextmanager

    import agent86.tools.mcp_client as mcp_client

    @asynccontextmanager
    async def _fake_open_transport(cfg, env_passthrough=None):
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
    from contextlib import asynccontextmanager

    import agent86.tools.mcp_client as mcp_client

    @asynccontextmanager
    async def _fake_open_transport(cfg, env_passthrough=None):
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


# --- v0.7: stdio env scrubbing, note accumulation, readOnlyHint, restart -------------------- #


def _fake_tool(name, annotations=None, schema=None):
    class _T:
        pass

    t = _T()
    t.name = name
    t.description = f"does {name}"
    t.input_schema = schema or {"type": "object", "properties": {}}
    t.annotations = annotations
    return t


def _install_fake_transport(monkeypatch, tools):
    """Wire a fake transport + session that lists ``tools``. Returns the recorded configs."""
    from contextlib import asynccontextmanager

    import agent86.tools.mcp_client as mcp_client

    seen: list = []

    @asynccontextmanager
    async def _fake_open_transport(cfg, env_passthrough=None):
        seen.append((cfg, env_passthrough))
        yield (object(), object())

    class _FakeListed:
        pass

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
            listed = _FakeListed()
            listed.tools = tools
            return listed

    monkeypatch.setattr(mcp_client, "_open_transport", _fake_open_transport)
    monkeypatch.setattr(mcp_client, "ClientSession", _FakeSession, raising=False)
    return seen


def test_stdio_env_never_forwards_api_keys(monkeypatch):
    """A server declaring one env var used to receive the whole host environment."""
    from agent86.tools.mcp_client import stdio_env

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-secret")
    cfg = MCPServerConfig(command="npx", env={"SERVER_MODE": "fast"})

    env = stdio_env(cfg)

    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    assert "sk-ant-secret" not in "".join(env.values())
    assert env["SERVER_MODE"] == "fast"
    assert "PATH" in env  # the server can still find its own executables


def test_stdio_env_keeps_resolved_server_secret(monkeypatch):
    """A ${VAR} the server explicitly asked for still arrives — and nothing else does."""
    from agent86.tools.mcp_client import _resolve_server_secrets, stdio_env

    monkeypatch.setenv("A86_GH", "ghp-for-this-server")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    cfg = _resolve_server_secrets(MCPServerConfig(command="npx", env={"TOKEN": "${A86_GH}"}))

    env = stdio_env(cfg)

    assert env["TOKEN"] == "ghp-for-this-server"
    assert "ANTHROPIC_API_KEY" not in env


def test_stdio_env_honours_passthrough(monkeypatch):
    from agent86.tools.mcp_client import stdio_env

    monkeypatch.setenv("MY_BUILD_FLAVOUR", "debug")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    cfg = MCPServerConfig(command="npx")

    env = stdio_env(cfg, ["MY_BUILD_FLAVOUR", "ANTHROPIC_API_KEY"])

    assert env["MY_BUILD_FLAVOUR"] == "debug"
    assert "ANTHROPIC_API_KEY" not in env  # passthrough can't smuggle a credential


def test_stdio_transport_uses_scrubbed_env(monkeypatch):
    """The parameters handed to stdio_client carry the scrubbed env, not os.environ."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    cm = _open_transport(MCPServerConfig(command="echo", args=["hi"], env={"X": "1"}))
    params = cm.args[0]  # contextlib keeps the arguments the transport was built with
    assert params.env["X"] == "1"
    assert "ANTHROPIC_API_KEY" not in params.env
    assert "PATH" in params.env


def test_manager_passes_its_passthrough_to_the_transport(monkeypatch):
    seen = _install_fake_transport(monkeypatch, [_fake_tool("alpha")])
    manager = MCPManager({}, env_passthrough=["MY_BUILD_FLAVOUR"])
    manager.start_server("srv", MCPServerConfig(command="npx"))
    assert seen[0][1] == ["MY_BUILD_FLAVOUR"]
    manager.close()


def test_build_mcp_reads_env_passthrough_from_config(monkeypatch):
    seen = _install_fake_transport(monkeypatch, [_fake_tool("alpha")])
    cfg = load_config()
    cfg.mcp.enabled = True
    cfg.mcp_servers = {"srv": MCPServerConfig(command="npx")}
    try:
        cfg.sandbox.env_passthrough = ["MY_BUILD_FLAVOUR"]
    except (ValueError, AttributeError):  # config agent adds the field concurrently
        object.__setattr__(cfg.sandbox, "env_passthrough", ["MY_BUILD_FLAVOUR"])

    manager = build_mcp(cfg)
    assert manager is not None
    assert seen[0][1] == ["MY_BUILD_FLAVOUR"]
    manager.close()


def test_notes_accumulate_across_failing_servers(monkeypatch):
    """With several bad servers, one overwritten string hid every failure but the last."""
    from contextlib import asynccontextmanager

    import agent86.tools.mcp_client as mcp_client

    @asynccontextmanager
    async def _boom(cfg, env_passthrough=None):
        raise RuntimeError(f"cannot connect to {cfg.command}")
        yield  # pragma: no cover

    monkeypatch.setattr(mcp_client, "_open_transport", _boom)
    manager = MCPManager(
        {"alpha": MCPServerConfig(command="a"), "beta": MCPServerConfig(command="b")}
    )
    manager.start()

    assert len(manager.notes) == 2
    assert "alpha" in (manager.note or "") and "beta" in (manager.note or "")
    manager.close()


def test_read_only_hint_makes_a_tool_non_side_effecting(monkeypatch):
    class _Annotations:
        read_only_hint = True

    _install_fake_transport(
        monkeypatch,
        [_fake_tool("search", annotations=_Annotations()), _fake_tool("write_file")],
    )
    manager = MCPManager({})
    tools = {t._tool: t for t in manager.start_server("srv", MCPServerConfig(command="npx"))}

    assert tools["search"].side_effecting is False
    assert tools["search"].spec().side_effecting is False
    assert tools["write_file"].side_effecting is True
    manager.close()


def test_read_only_hint_accepts_the_wire_spelling():
    from agent86.tools.mcp_client import _is_read_only

    assert _is_read_only(_fake_tool("t", annotations={"readOnlyHint": True}))
    assert not _is_read_only(_fake_tool("t", annotations={"readOnlyHint": False}))
    assert not _is_read_only(_fake_tool("t"))


def test_tool_schema_reads_both_sdk_spellings():
    from agent86.tools.mcp_client import _tool_schema

    modern = _fake_tool("t", schema={"type": "object", "properties": {"a": {}}})
    assert _tool_schema(modern)["properties"] == {"a": {}}

    class _Legacy:
        inputSchema = {"type": "object", "properties": {"b": {}}}

    assert _tool_schema(_Legacy())["properties"] == {"b": {}}


def test_close_allows_a_later_restart(monkeypatch):
    _install_fake_transport(monkeypatch, [_fake_tool("alpha"), _fake_tool("beta")])
    manager = MCPManager({"srv": MCPServerConfig(command="npx")})

    manager.start()
    assert len(manager.tools()) == 2

    manager.close()
    assert manager.tools() == []

    manager.start()  # previously a silent no-op: _started was never reset
    assert len(manager.tools()) == 2
    manager.close()


def test_real_sdk_tool_object_is_understood():
    """Regression guard: mcp>=2 renamed Tool.inputSchema to input_schema.

    The fakes above would happily keep a wrong attribute name working, and the live-server
    test is skipped wherever FastMCP isn't installed — so assert against the real model.
    """
    types = pytest.importorskip("mcp.types")
    from agent86.tools.mcp_client import _is_read_only, _tool_schema

    tool = types.Tool(
        name="search",
        inputSchema={"type": "object", "properties": {"q": {"type": "string"}}},
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    assert _tool_schema(tool)["properties"] == {"q": {"type": "string"}}
    assert _is_read_only(tool) is True
    assert _is_read_only(types.Tool(name="write", inputSchema={})) is False
