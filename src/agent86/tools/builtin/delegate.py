"""The delegate tool — model-driven sub-agent spawning (supervisor topology).

When the main agent decides a subtask is best handled by a focused specialist, it calls
``delegate`` with a role and a task. The harness spins up a sub-agent that runs to completion
(with the same tools, sandbox, and guardrails) and returns its result as the tool output —
so the main agent acts as the supervisor.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent86.tools.base import Tool, ToolContext
from agent86.types import ToolResult


class DelegateTool(Tool["DelegateTool.Args"]):
    name = "delegate"
    description = (
        "Delegate a focused subtask to a fresh sub-agent with a given role (e.g. "
        "'researcher', 'coder', 'reviewer'). The sub-agent runs to completion and returns "
        "its result. Use for well-scoped subtasks you want handled independently."
    )
    side_effecting = False  # the sub-agent's own tools are individually gated

    class Args(BaseModel):
        role: str = Field(default="assistant", description="The sub-agent's role/persona.")
        task: str = Field(..., description="The self-contained task for the sub-agent.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        if ctx.spawn is None:
            return ToolResult(
                call_id="", name=self.name, ok=False, error="Delegation is disabled."
            )
        result = ctx.spawn(args.role, args.task)
        return ToolResult(call_id="", name=self.name, content=result)


__all__ = ["DelegateTool"]
