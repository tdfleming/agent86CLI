"""Built-in Python interpreter tool.

Runs a snippet in a fresh Python process under the sandbox (code delivered over stdin,
so multi-line programs work). This is the book's canonical "Python interpreter tool" — a
restricted subprocess here; Docker/WASM add stronger isolation in later phases.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent86.tools.base import Tool, ToolContext
from agent86.types import ToolResult


class PythonExecTool(Tool["PythonExecTool.Args"]):
    name = "python_exec"
    description = (
        "Execute a Python 3 snippet in a fresh sandboxed process and return its stdout, "
        "stderr, and exit code. Print results you want to see."
    )
    side_effecting = True

    class Args(BaseModel):
        code: str = Field(..., description="Python source to execute. Use print() for output.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        executor = ctx.get_executor()
        result = executor.run(ctx.policy, args=executor.python_argv(), stdin=args.code)
        parts = [f"exit code: {result.returncode}"]
        if result.stdout.strip():
            parts.append(f"stdout:\n{result.stdout.rstrip()}")
        if result.stderr.strip():
            parts.append(f"stderr:\n{result.stderr.rstrip()}")
        return ToolResult(
            call_id="",
            name=self.name,
            ok=result.ok,
            content="\n".join(parts),
            metadata={"returncode": result.returncode, "timed_out": result.timed_out},
        )


__all__ = ["PythonExecTool"]
