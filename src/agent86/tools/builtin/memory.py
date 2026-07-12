"""Memory tools — let the agent persist and retrieve knowledge across sessions.

Registered only when the memory system is available. ``remember`` and ``recall`` operate on
semantic memory; they are internal (not external-world) side effects, so they don't require
HITL approval.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent86.tools.base import Tool, ToolContext
from agent86.types import ToolResult


class RememberTool(Tool):
    name = "remember"
    description = (
        "Persist a durable, user-specific fact to long-term memory for future sessions — "
        "a stable preference, identity detail, or project constraint the user would expect "
        "you to recall later. Do NOT use it for answers you just computed, transient "
        "conversation state, general knowledge, or anything only relevant to this turn. "
        "Only call it when the user asks you to remember something, or states a lasting "
        "fact about themselves or their work. When in doubt, do not remember."
    )
    side_effecting = False

    class Args(BaseModel):
        text: str = Field(..., description="The fact to remember, as a self-contained sentence.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        if ctx.memory is None:
            return ToolResult(call_id="", name=self.name, ok=False, error="Memory is disabled.")
        ctx.memory.add(args.text)
        return ToolResult(call_id="", name=self.name, content="Remembered.")


class RecallTool(Tool):
    name = "recall"
    description = "Search long-term semantic memory for facts relevant to a query."
    side_effecting = False

    class Args(BaseModel):
        query: str = Field(..., description="What to search memory for.")
        k: int = Field(default=5, description="Maximum number of results.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        if ctx.memory is None:
            return ToolResult(call_id="", name=self.name, ok=False, error="Memory is disabled.")
        hits = ctx.memory.search(args.query, k=max(1, min(args.k, 20)))
        if not hits:
            return ToolResult(call_id="", name=self.name, content="(no relevant memories)")
        body = "\n".join(f"- {h.text}  [score {h.score:.2f}]" for h in hits)
        return ToolResult(call_id="", name=self.name, content=body)


__all__ = ["RememberTool", "RecallTool"]
