"""Restricted-subprocess executor (Tier 4, default sandbox).

Runs a command under the :class:`SandboxPolicy`: workspace as cwd, scrubbed environment,
a hard timeout, and truncated output. Not true isolation (that's Docker in Phase 9) — but
it removes the sharpest edges: no inherited secrets, no unbounded runtime, no runaway output.

The timeout kills the whole *process tree*, not just the direct child. ``npm test`` or a
shell one-liner spawns children of its own; killing the parent alone leaves them running
(holding ports, burning CPU, and keeping the output pipes open) long after the harness has
moved on. So the child is started in its own process group / session and the group is what
gets killed.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent86.tools.sandbox.policy import SandboxPolicy

logger = logging.getLogger(__name__)

#: Seconds to wait for the pipes to drain after a kill before giving up on the output.
_DRAIN_TIMEOUT_S = 5


@dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def _group_kwargs() -> dict:
    """Popen kwargs that put the child at the head of its own killable group.

    The platform-only names are fetched with ``getattr`` so this module type-checks on both
    platforms (typeshed hides ``CREATE_NEW_PROCESS_GROUP`` off Windows and ``killpg`` on it).
    """
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill ``proc`` and every process it spawned. Best effort, never raises."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # CREATE_NEW_PROCESS_GROUP alone doesn't cascade; taskkill /T walks the tree.
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=_DRAIN_TIMEOUT_S,
            )
        else:
            killpg = getattr(os, "killpg", None)
            getpgid = getattr(os, "getpgid", None)
            sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
            if killpg is not None and getpgid is not None:
                killpg(getpgid(proc.pid), sigkill)
    except (OSError, subprocess.SubprocessError) as exc:  # already gone, or no permission
        logger.debug("Process-tree kill for pid %s failed: %s", proc.pid, exc)
    finally:
        try:
            proc.kill()  # make sure the direct child is reaped even if the group kill missed
        except OSError:
            pass


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
    proc = subprocess.Popen(
        popen_arg,
        shell=shell_command is not None,
        cwd=str(cwd or policy.workspace),
        env=policy.scrubbed_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_group_kwargs(),
    )
    try:
        out, err = proc.communicate(stdin, timeout=policy.timeout_s)
    except subprocess.TimeoutExpired:
        kill_process_tree(proc)
        out, err = _drain(proc)
        return ExecResult(
            returncode=124,
            stdout=policy.truncate(out),
            stderr=policy.truncate(err) + f"\n[timed out after {policy.timeout_s}s]",
            timed_out=True,
        )

    return ExecResult(
        returncode=proc.returncode,
        stdout=policy.truncate(out or ""),
        stderr=policy.truncate(err or ""),
    )


def _drain(proc: subprocess.Popen) -> tuple[str, str]:
    """Collect whatever the killed tree already wrote; never block for long."""
    try:
        out, err = proc.communicate(timeout=_DRAIN_TIMEOUT_S)
    except subprocess.TimeoutExpired:  # a surviving grandchild still holds the pipe
        proc.kill()
        return "", ""
    except ValueError:  # pragma: no cover - pipes closed under us
        return "", ""
    return _as_text(out), _as_text(err)


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


__all__ = ["run_subprocess", "ExecResult", "kill_process_tree"]
