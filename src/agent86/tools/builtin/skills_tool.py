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
            body += (
                f"\n\nBundled resources in the skill directory ({skill.directory}), readable "
                "with read_file: " + ", ".join(resources)
            )
        # Activating a skill *replaces* any previously active one, so its allowed-tools list
        # is the restriction in force from here until the end of the turn.
        ctx.activate_skill(skill)
        if skill.allowed_tools:
            body += (
                "\n\nWhile this skill is active you may only call these tools: "
                + ", ".join(skill.allowed_tools)
                + " (plus use_skill). Other tools will be refused."
            )
        return ToolResult(
            call_id="",
            name=self.name,
            content=body,
            metadata={"skill": skill.name, "allowed_tools": list(skill.allowed_tools)},
        )


__all__ = ["UseSkillTool"]
