"""MCP client (Tier 4) — mount external Model Context Protocol server tools.

agent86 acts as an MCP *client*: for each configured server it spawns the process, lists its
tools, and wraps each as a first-class :class:`Tool` in the registry — so MCP tools get the
same schema advertisement, approval gating, and observability as built-ins.

The MCP Python SDK is async and its stdio sessions are long-lived; this manager runs a
dedicated background event loop so the synchronous harness can call MCP tools via
``run_coroutine_threadsafe``. Everything degrades gracefully: no servers configured, or the
``mcp`` package missing, yields zero tools and a note rather than an error.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
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


class MCPManager:
    def __init__(self, servers: dict[str, MCPServerConfig]):
        self.servers = servers
        self.note: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, Any] = {}
        self._stack: Any = None
        self._tools: list[MCPTool] = []
        self._started = False

    def start(self) -> None:
        if self._started or not self.servers:
            return
        try:
            from contextlib import AsyncExitStack

            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            self.note = (
                'mcp package not installed; MCP tools unavailable (pip install "agent86[mcp]").'
            )
            return

        self._started = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        async def _connect() -> tuple[Any, list[MCPTool]]:
            stack = AsyncExitStack()
            tools: list[MCPTool] = []
            for name, cfg in self.servers.items():
                try:
                    params = StdioServerParameters(
                        command=cfg.command,
                        args=cfg.args,
                        env={**os.environ, **cfg.env} if cfg.env else None,
                    )
                    read, write = await stack.enter_async_context(stdio_client(params))
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    self._sessions[name] = session
                    listed = await session.list_tools()
                    for t in listed.tools:
                        tools.append(
                            MCPTool(self, name, t.name, t.description or "", t.inputSchema or {})
                        )
                except Exception as exc:
                    self.note = f"MCP server '{name}' failed to start: {exc}"
            return stack, tools

        try:
            fut = asyncio.run_coroutine_threadsafe(_connect(), self._loop)
            self._stack, self._tools = fut.result(timeout=30)
        except Exception as exc:
            self.note = f"MCP startup failed: {exc}"

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def tools(self) -> list[MCPTool]:
        return self._tools

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
        if self._stack is not None:
            async def _aclose() -> None:
                await self._stack.aclose()

            try:
                asyncio.run_coroutine_threadsafe(_aclose(), self._loop).result(timeout=10)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        self._loop = None


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
