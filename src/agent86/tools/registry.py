"""Tool registry (Tier 4).

One place that holds every available tool — built-in, and later MCP- and skill-provided —
exposes their specs to the Cognitive Tier, and dispatches validated calls. The orchestrator
only ever talks to the registry, never to concrete tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent86.config import Config
from agent86.tools.base import Tool, ToolContext
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


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

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
    mcp_tools: list[Tool] | None = None,
) -> ToolRegistry:
    """Registry pre-loaded with the built-in tools, plus memory/skill/MCP tools.

    - ``remember`` / ``recall`` are added only when semantic memory is available.
    - ``use_skill`` is added only when at least one skill was discovered.
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
    for tool in mcp_tools or []:
        try:
            registry.register(tool)
        except ValueError:
            pass  # skip duplicate tool names across servers
    return registry


__all__ = ["ToolRegistry", "default_registry"]
