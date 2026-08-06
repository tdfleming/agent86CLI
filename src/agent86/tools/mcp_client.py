"""MCP client (Tier 4) — mount external Model Context Protocol server tools.

agent86 acts as an MCP *client*: for each configured server it opens a transport, lists its
tools, and wraps each as a first-class :class:`Tool` in the registry — so MCP tools get the
same schema advertisement, approval gating, and observability as built-ins.

Three transports are supported: ``stdio`` (spawn a local subprocess), ``sse``, and ``http``
(streamable HTTP) — the last two connect to a remote ``url`` with optional auth ``headers``.
The MCP Python SDK is async and its sessions are long-lived; this manager runs a dedicated
background event loop so the synchronous harness can call MCP tools via
``run_coroutine_threadsafe``. Everything degrades gracefully: no servers configured, or the
``mcp`` package missing, yields zero tools and a note rather than an error.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
from contextlib import asynccontextmanager
from typing import Any

from agent86.config import Config, MCPServerConfig
from agent86.tools.base import EmptyArgs, Tool, ToolContext
from agent86.types import ToolCall, ToolResult, ToolSpec

_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")


def _sanitize(name: str) -> str:
    return _NAME_RE.sub("_", name)[:64]


class MCPTool(Tool[EmptyArgs]):
    """A registry tool backed by a remote MCP server tool."""

    Args = EmptyArgs  # unused: spec() and run() are overridden (schema comes from the server)

    def __init__(self, manager: MCPManager, server: str, tool_name: str,
                 description: str, input_schema: dict):
        self._manager = manager
        self._server = server
        self._tool = tool_name
        self.name = _sanitize(f"mcp__{server}__{tool_name}")
        self.description = f"{description or tool_name} (MCP: {server})"
        self.side_effecting = True  # external side effects -> gated by the approval gate
        self._schema = input_schema or {"type": "object", "properties": {}}

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name, description=self.description,
            parameters=self._schema, side_effecting=True,
        )

    def execute(self, args: EmptyArgs, ctx: ToolContext) -> ToolResult:  # pragma: no cover
        raise NotImplementedError  # run() is overridden; execute is never called

    def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        try:
            text = self._manager.call_tool(self._server, self._tool, call.arguments)
        except Exception as exc:
            return ToolResult(
                call_id=call.id, name=self.name, ok=False, error=f"MCP call failed: {exc}"
            )
        return ToolResult(call_id=call.id, name=self.name, content=text)


def _get_client_session() -> Any:
    """Return ``mcp.ClientSession``, looked up through this module's own globals first.

    Tests monkeypatch ``mcp_client.ClientSession`` (with ``raising=False``) to inject a fake
    session without a real transport; checking ``globals()`` first (before falling back to a
    fresh ``from mcp import ClientSession``) lets that monkeypatch take effect even though the
    real import happens lazily, per server, inside ``_serve``.
    """
    cached = globals().get("ClientSession")
    if cached is not None:
        return cached
    from mcp import ClientSession as _ClientSession

    return _ClientSession


class MCPManager:
    def __init__(self, servers: dict[str, MCPServerConfig]):
        self.servers = servers
        self.note: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, Any] = {}
        self._tasks: dict[str, Any] = {}  # name -> asyncio.Task (owns its own stack)
        self._close_events: dict[str, Any] = {}  # name -> asyncio.Event
        self._server_tools: dict[str, list[MCPTool]] = {}
        self._started = False

    def _ensure_loop(self) -> None:
        """Start the background event loop, lazily importing `mcp`. Raises if it is missing.

        Every entry point (bulk `start`, per-server `start_server`) funnels through here so the
        degrade-with-a-note contract is identical no matter which one the caller used.
        """
        if self._loop is not None:
            return
        try:
            from contextlib import AsyncExitStack  # noqa: F401 - import probe

            from mcp import ClientSession  # noqa: F401 - import probe
        except ImportError as exc:
            self.note = (
                'mcp package not installed; MCP tools unavailable (pip install "agent86[mcp]").'
            )
            raise RuntimeError(self.note) from exc
        self._started = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def start_server(
        self,
        name: str,
        cfg: MCPServerConfig,
        timeout: float = 30.0,
        overrides: dict[str, str] | None = None,
    ) -> list[MCPTool]:
        """Open one server's transport and return its tools. Blocks the caller until ready.

        Raises on connection failure or timeout — the connection-test modal surfaces it verbatim
        (D-19/D-20). On success the server's owning task stays parked until `stop_server`.
        """
        self._ensure_loop()
        assert self._loop is not None
        if name in self._tasks:
            self.stop_server(name)
        resolved = _resolve_server_secrets(cfg, overrides)
        fut = asyncio.run_coroutine_threadsafe(self._launch(name, resolved), self._loop)
        try:
            tools = fut.result(timeout=timeout)
        except Exception:
            self._tasks.pop(name, None)
            self._close_events.pop(name, None)
            self._server_tools.pop(name, None)
            raise
        return tools

    async def _launch(self, name: str, cfg: MCPServerConfig) -> list[MCPTool]:
        close_event = asyncio.Event()
        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(self._serve(name, cfg, ready, close_event))
        self._tasks[name] = task
        self._close_events[name] = close_event
        return await ready

    async def _serve(
        self, name: str, cfg: MCPServerConfig, ready: asyncio.Future, close_event: asyncio.Event
    ) -> None:
        """The server's owning task: opens its OWN AsyncExitStack and lets it unwind here.

        anyio binds each transport's cancel scope to the task that entered it, so `aclose()` may
        only run in that same task (python-sdk issues #79/#922). Parking on `close_event` and
        letting the `async with` unwind in place is what makes per-server teardown legal.
        """
        from contextlib import AsyncExitStack

        ClientSession = _get_client_session()

        try:
            async with AsyncExitStack() as stack:
                streams = await stack.enter_async_context(_open_transport(cfg))
                # sse/stdio yield (read, write); streamable HTTP yields a 3rd
                # get_session_id we don't need — take the first two either way.
                read, write = streams[0], streams[1]
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listed = await session.list_tools()
                tools = [
                    MCPTool(self, name, t.name, t.description or "", t.inputSchema or {})
                    for t in listed.tools
                ]
                self._sessions[name] = session
                self._server_tools[name] = tools
                if not ready.done():
                    ready.set_result(tools)
                await close_event.wait()
        except BaseException as exc:  # noqa: BLE001 - surfaced to the caller verbatim
            if not ready.done():
                ready.set_exception(exc)
        finally:
            self._sessions.pop(name, None)

    def stop_server(self, name: str, timeout: float = 10.0) -> None:
        """Signal one server's owning task to unwind its own stack, then wait for it."""
        close_event = self._close_events.pop(name, None)
        task = self._tasks.pop(name, None)
        self._server_tools.pop(name, None)
        if close_event is None or task is None or self._loop is None:
            return

        async def _stop() -> None:
            close_event.set()
            await task  # awaiting a task from another task is fine — no scope is exited here

        try:
            asyncio.run_coroutine_threadsafe(_stop(), self._loop).result(timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - a stuck teardown must not wedge the app
            self.note = f"MCP server '{name}' did not shut down cleanly: {exc}"
        self._sessions.pop(name, None)

    def tools_for(self, name: str) -> list[MCPTool]:
        return list(self._server_tools.get(name, []))

    def tools(self) -> list[MCPTool]:
        return [tool for tools in self._server_tools.values() for tool in tools]

    def start(self) -> None:
        if self._started or not self.servers:
            return
        try:
            self._ensure_loop()
        except RuntimeError:
            return  # note already set by _ensure_loop
        for name, cfg in self.servers.items():
            try:
                self.start_server(name, cfg)
            except Exception as exc:  # noqa: BLE001 - one bad server degrades to a note
                self.note = f"MCP server '{name}' failed to start: {exc}"

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def call_tool(self, server: str, tool: str, arguments: dict) -> str:
        if self._loop is None or server not in self._sessions:
            raise RuntimeError("MCP session not available")
        session = self._sessions[server]

        async def _call() -> str:
            result = await session.call_tool(tool, arguments)
            return _content_to_text(result)

        return asyncio.run_coroutine_threadsafe(_call(), self._loop).result(timeout=120)

    def close(self) -> None:
        if self._loop is None:
            return
        for name in list(self._tasks):
            self.stop_server(name)
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        self._loop = None


@asynccontextmanager
async def _streamable_http(url: str, headers: dict[str, str]) -> Any:
    """Streamable-HTTP transport, owning the httpx client's lifecycle.

    The SDK's ``streamable_http_client`` takes a caller-provided httpx client (the older
    all-in-one ``streamablehttp_client`` is deprecated), so we create one here — carrying any
    auth ``headers`` — and close it with the transport. Yields the transport's stream tuple.
    """
    import httpx
    from mcp.client.streamable_http import streamable_http_client

    async with httpx.AsyncClient(headers=headers or None) as client:
        async with streamable_http_client(url, http_client=client) as streams:
            yield streams


def _resolve_server_secrets(
    cfg: MCPServerConfig, overrides: dict[str, str] | None = None
) -> MCPServerConfig:
    """Return a COPY of ``cfg`` with every ``${VAR}`` resolved (D-17/D-25).

    Applied to ``args``, ``env`` values, ``url``, and ``headers`` values — resolved fresh at
    connect time, never cached back into config. ``command`` is deliberately NOT expanded: letting
    an env var or keyring entry decide which executable is spawned is a foot-gun with no use case
    in this phase's scope.

    Raises :class:`agent86.secrets.MissingSecretRef` for the first unresolved name; the caller
    turns that into a masked key prompt (D-18) rather than connecting with an empty credential.
    """
    from agent86.secrets import expand_var_refs

    return cfg.model_copy(
        update={
            "args": [expand_var_refs(a, overrides) for a in cfg.args],
            "env": {k: expand_var_refs(v, overrides) for k, v in cfg.env.items()},
            "url": expand_var_refs(cfg.url, overrides) if cfg.url else cfg.url,
            "headers": {k: expand_var_refs(v, overrides) for k, v in cfg.headers.items()},
        }
    )


def unresolved_var_refs(cfg: MCPServerConfig, overrides: dict[str, str] | None = None) -> list[str]:
    """Every ${VAR} name in args/env/url/headers that neither an override, the environment, nor
    the OS keyring can supply — in stable sorted order, so the caller prompts predictably."""
    from agent86.secrets import find_var_refs, resolve_api_key

    overrides = overrides or {}
    texts = [*cfg.args, *cfg.env.values(), cfg.url or "", *cfg.headers.values()]
    missing = [
        name
        for name in sorted(find_var_refs(*texts))
        if name not in overrides and resolve_api_key(name, name) is None
    ]
    return missing


def _open_transport(cfg: MCPServerConfig) -> Any:
    """Return the async transport context manager for a server's configured transport.

    ``cfg`` is expected to already be ``${VAR}``-resolved (see ``_resolve_server_secrets``) —
    this function does no expansion of its own.

    Imports are lazy and per-transport so a server that only uses stdio never pulls in the
    HTTP transports (and vice versa). The caller enters the returned context on the MCP loop.
    """
    # The config validator guarantees command/url are set for their transport; assert the
    # invariant so the type checker can narrow away the Optional.
    if cfg.transport == "stdio":
        assert cfg.command is not None
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env={**os.environ, **cfg.env} if cfg.env else None,
        )
        return stdio_client(params)
    assert cfg.url is not None
    if cfg.transport == "sse":
        from mcp.client.sse import sse_client

        return sse_client(cfg.url, headers=cfg.headers or None)
    # "http" -> streamable HTTP (the modern successor to the SSE transport)
    return _streamable_http(cfg.url, cfg.headers)


def _content_to_text(result: Any) -> str:
    parts: list[str] = []
    for chunk in getattr(result, "content", None) or []:
        text = getattr(chunk, "text", None)
        parts.append(text if text is not None else str(chunk))
    body = "\n".join(parts) if parts else "(no content)"
    if getattr(result, "isError", False):
        return f"ERROR: {body}"
    return body


def build_mcp(config: Config) -> MCPManager | None:
    """Start MCP servers from config, or return None if disabled / none configured."""
    if not config.mcp.enabled or not config.mcp_servers:
        return None
    manager = MCPManager(config.mcp_servers)
    manager.start()
    return manager


__all__ = ["MCPManager", "MCPTool", "build_mcp"]
