"""The use_skill tool — progressive disclosure of skill instructions.

Skill names + descriptions are advertised in the system prompt. When the model decides a
skill applies, it calls ``use_skill`` to load that skill's full instructions into the
conversation on demand — keeping the base context lean.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent86.tools.base import Tool, ToolContext
from agent86.types import ToolResult


class UseSkillTool(Tool["UseSkillTool.Args"]):
    name = "use_skill"
    description = (
        "Load the full instructions for a named skill. Call this when a skill from the "
        "'Available skills' list applies to the task, then follow the returned instructions."
    )
    side_effecting = False

    class Args(BaseModel):
        name: str = Field(..., description="The exact name of the skill to load.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        skill = ctx.skills.get(args.name)
        if skill is None:
            available = ", ".join(sorted(ctx.skills)) or "(none)"
            return ToolResult(
                call_id="", name=self.name, ok=False,
                error=f"No skill named '{args.name}'. Available: {available}.",
            )
        body = skill.instructions()
        resources = skill.resources()
        if resources:
            body += "\n\nBundled resources in the skill directory: " + ", ".join(resources)
        return ToolResult(call_id="", name=self.name, content=body)


__all__ = ["UseSkillTool"]
