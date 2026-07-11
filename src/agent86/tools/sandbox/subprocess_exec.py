"""Restricted-subprocess executor (Tier 4, default sandbox).

Runs a command under the :class:`SandboxPolicy`: workspace as cwd, scrubbed environment,
a hard timeout, and truncated output. Not true isolation (that's Docker in Phase 9) — but
it removes the sharpest edges: no inherited secrets, no unbounded runtime, no runaway output.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent86.tools.sandbox.policy import SandboxPolicy


@dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def run_subprocess(
    policy: SandboxPolicy,
    *,
    args: list[str] | None = None,
    shell_command: str | None = None,
    cwd: Path | None = None,
    stdin: str | None = None,
) -> ExecResult:
    """Execute either an argv list or a shell command string under the policy."""
    if (args is None) == (shell_command is None):
        raise ValueError("Provide exactly one of 'args' or 'shell_command'.")

    popen_arg: list[str] | str = shell_command if shell_command is not None else args  # type: ignore[assignment]
    try:
        proc = subprocess.run(
            popen_arg,
            shell=shell_command is not None,
            cwd=str(cwd or policy.workspace),
            env=policy.scrubbed_env(),
            capture_output=True,
            text=True,
            timeout=policy.timeout_s,
            input=stdin,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return ExecResult(
            returncode=124,
            stdout=policy.truncate(out),
            stderr=policy.truncate(err) + f"\n[timed out after {policy.timeout_s}s]",
            timed_out=True,
        )

    return ExecResult(
        returncode=proc.returncode,
        stdout=policy.truncate(proc.stdout or ""),
        stderr=policy.truncate(proc.stderr or ""),
    )


__all__ = ["run_subprocess", "ExecResult"]
