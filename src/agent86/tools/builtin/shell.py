"""Built-in shell tool — runs a command under the restricted-subprocess sandbox."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from agent86.tools.base import Tool, ToolContext
from agent86.tools.builtin.files import head_of
from agent86.types import ToolResult

#: A command long enough to hide something is capped, not truncated mid-token at 300 chars.
PREVIEW_MAX_LINES = 60


class RunCommandTool(Tool["RunCommandTool.Args"]):
    name = "run_command"
    description = (
        "Run a shell command in the workspace and return its stdout, stderr, and exit "
        "code. Runs under the sandbox: scrubbed environment, workspace cwd, and a timeout."
    )
    side_effecting = True
    preview_lexer = "bash"

    class Args(BaseModel):
        command: str = Field(..., description="The shell command to execute.")

    def preview(self, arguments: Mapping[str, Any], ctx: ToolContext | None = None) -> str | None:
        """The whole command — the one thing the user must read before approving it."""
        command = arguments.get("command")
        if not isinstance(command, str):
            return None
        return head_of(command, PREVIEW_MAX_LINES)

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        result = ctx.get_executor().run(ctx.policy, shell_command=args.command)
        body = _format(result.returncode, result.stdout, result.stderr)
        return ToolResult(
            call_id="",
            name=self.name,
            ok=result.ok,
            content=body,
            metadata={"returncode": result.returncode, "timed_out": result.timed_out},
        )


def _format(rc: int, out: str, err: str) -> str:
    parts = [f"exit code: {rc}"]
    if out.strip():
        parts.append(f"stdout:\n{out.rstrip()}")
    if err.strip():
        parts.append(f"stderr:\n{err.rstrip()}")
    return "\n".join(parts)


__all__ = ["RunCommandTool"]
