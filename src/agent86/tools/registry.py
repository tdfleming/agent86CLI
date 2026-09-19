"""Tool registry (Tier 4).

One place that holds every available tool — built-in, and later MCP- and skill-provided —
exposes their specs to the Cognitive Tier, and dispatches validated calls. The orchestrator
only ever talks to the registry, never to concrete tools.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from agent86.config import Config
from agent86.tools.base import Tool, ToolContext
from agent86.tools.builtin.delegate import DelegateTool
from agent86.tools.builtin.files import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from agent86.tools.builtin.memory import RecallTool, RememberTool
from agent86.tools.builtin.python_exec import PythonExecTool
from agent86.tools.builtin.shell import RunCommandTool
from agent86.tools.builtin.skills_tool import UseSkillTool
from agent86.tools.builtin.web import WebFetchTool
from agent86.types import ToolCall, ToolResult, ToolSpec

if TYPE_CHECKING:
    from agent86.memory.semantic import SemanticMemory
    from agent86.skills.models import Skill

logger = logging.getLogger(__name__)

#: MCP tool names are sanitized to this length; two long names sharing a prefix can collide
#: purely because of the truncation, which is worth saying out loud when they do.
_MCP_NAME_LIMIT = 64


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        #: Names dropped at startup because something already owned them. Kept so the CLI/TUI
        #: can show the user which of their MCP tools are NOT callable — silently dropping a
        #: tool the user configured looks like the server failed to connect.
        self.collisions: list[str] = []

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def try_register(self, tool: Tool) -> bool:
        """Register ``tool`` unless its name is taken; record and log the clash if it is.

        The lenient path used when mounting many tools at startup, where one collision must
        not abort the run — but must not vanish either.
        """
        if tool.name not in self._tools:
            self._tools[tool.name] = tool
            return True
        detail = f"'{tool.name}' (already provided by another tool"
        if len(tool.name) >= _MCP_NAME_LIMIT:
            detail += f"; names are truncated to {_MCP_NAME_LIMIT} characters"
        self.collisions.append(tool.name)
        logger.warning("Tool name collision: %s) — this tool is not callable.", detail)
        return False

    def unregister(self, name: str) -> bool:
        """Remove one tool by name; True if it was present (D-14).

        Needed so a removed or disabled MCP server's tools stop being callable *immediately*,
        without rebuilding the whole registry — leaving them mounted would let the model invoke
        something the user just deleted.
        """
        return self._tools.pop(name, None) is not None

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]

    def dispatch(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=f"Unknown tool '{call.name}'. Available: {', '.join(self.names())}.",
            )
        return tool.run(call, ctx)


_BUILTINS: tuple[type[Tool], ...] = (
    ReadFileTool,
    WriteFileTool,
    EditFileTool,
    ListDirTool,
    RunCommandTool,
    PythonExecTool,
    WebFetchTool,
)


def default_registry(
    config: Config,
    memory: SemanticMemory | None = None,
    skills: dict[str, Skill] | None = None,
    mcp_tools: Sequence[Tool] | None = None,
    enable_delegate: bool = False,
) -> ToolRegistry:
    """Registry pre-loaded with the built-in tools, plus memory/skill/MCP/agent tools.

    - ``remember`` / ``recall`` are added only when semantic memory is available.
    - ``use_skill`` is added only when at least one skill was discovered.
    - ``delegate`` is added only when multi-agent spawning is enabled.
    - MCP tools (already constructed by the MCP manager) are mounted as-is.
    """
    registry = ToolRegistry()
    for tool_cls in _BUILTINS:
        registry.register(tool_cls())
    if memory is not None:
        registry.register(RememberTool())
        registry.register(RecallTool())
    if skills:
        registry.register(UseSkillTool())
    if enable_delegate:
        delegate = DelegateTool()
        # `delegate` is read-only at this level (the sub-agent's own tools are individually
        # gated), but it runs a whole nested agent loop — including approval prompts of its
        # own. Two of those racing for one terminal is not something the gate can untangle,
        # so delegation never joins a parallel batch.
        delegate.parallel_safe = False
        registry.register(delegate)
    for tool in mcp_tools or []:
        registry.try_register(tool)  # a duplicate name is recorded, not raised
    if registry.collisions:
        logger.warning(
            "%d tool name collision(s) at startup; these tools are not callable: %s",
            len(registry.collisions),
            ", ".join(registry.collisions),
        )
    return registry


__all__ = ["ToolRegistry", "default_registry"]
