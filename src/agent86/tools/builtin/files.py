"""Built-in file tools: read, write, edit, list — all jailed to the workspace."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent86.tools.base import Tool, ToolContext
from agent86.types import ToolResult


def _fail(name: str, msg: str) -> ToolResult:
    return ToolResult(call_id="", name=name, ok=False, error=msg)


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a UTF-8 text file within the workspace and return its contents."
    side_effecting = False

    class Args(BaseModel):
        path: str = Field(..., description="Path to the file, relative to the workspace.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        target = ctx.policy.resolve_within(args.path)
        if not target.exists():
            return _fail(self.name, f"No such file: {args.path}")
        if not target.is_file():
            return _fail(self.name, f"Not a file: {args.path}")
        text = target.read_text(encoding="utf-8", errors="replace")
        return ToolResult(call_id="", name=self.name, content=ctx.policy.truncate(text))


class WriteFileTool(Tool):
    name = "write_file"
    description = "Create or overwrite a text file within the workspace (creates parent dirs)."
    side_effecting = True

    class Args(BaseModel):
        path: str = Field(..., description="Path to write, relative to the workspace.")
        content: str = Field(..., description="Full file contents to write.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        target = ctx.policy.resolve_within(args.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(args.content, encoding="utf-8")
        return ToolResult(
            call_id="", name=self.name, content=f"Wrote {len(args.content)} bytes to {args.path}."
        )


class EditFileTool(Tool):
    name = "edit_file"
    description = (
        "Replace an exact substring in a workspace file. The old text must appear "
        "exactly once, or the edit is rejected."
    )
    side_effecting = True

    class Args(BaseModel):
        path: str = Field(..., description="Path to the file, relative to the workspace.")
        old: str = Field(..., description="Exact text to replace (must be unique in the file).")
        new: str = Field(..., description="Replacement text.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        target = ctx.policy.resolve_within(args.path)
        if not target.is_file():
            return _fail(self.name, f"No such file: {args.path}")
        text = target.read_text(encoding="utf-8")
        count = text.count(args.old)
        if count == 0:
            return _fail(self.name, "Old text not found.")
        if count > 1:
            return _fail(
                self.name, f"Old text is not unique ({count} matches); include more context."
            )
        target.write_text(text.replace(args.old, args.new), encoding="utf-8")
        return ToolResult(call_id="", name=self.name, content=f"Edited {args.path}.")


class ListDirTool(Tool):
    name = "list_dir"
    description = "List the entries of a directory within the workspace."
    side_effecting = False

    class Args(BaseModel):
        path: str = Field(default=".", description="Directory path, relative to the workspace.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        target = ctx.policy.resolve_within(args.path)
        if not target.is_dir():
            return _fail(self.name, f"Not a directory: {args.path}")
        lines = []
        for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            marker = "/" if entry.is_dir() else ""
            lines.append(f"{entry.name}{marker}")
        body = "\n".join(lines) if lines else "(empty)"
        return ToolResult(call_id="", name=self.name, content=ctx.policy.truncate(body))


__all__ = ["ReadFileTool", "WriteFileTool", "EditFileTool", "ListDirTool"]
