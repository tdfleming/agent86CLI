"""Docker container executor (Tier 4, opt-in) — true isolation.

Runs each command in a fresh, throwaway container: no network by default, capped memory and
CPU, a PID limit, and the workspace bind-mounted read-write at ``/workspace``. Invoked via the
``docker`` CLI (no Python SDK dependency). This is the stronger end of the sandbox spectrum
the book describes; the restricted subprocess remains the default.
"""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from pathlib import Path

from agent86.config import SandboxConfig
from agent86.tools.sandbox.policy import SandboxPolicy
from agent86.tools.sandbox.subprocess_exec import ExecResult

logger = logging.getLogger(__name__)

_CONTAINER_WORKDIR = "/workspace"
#: Seconds allowed for the `docker kill` that cleans up after a timeout.
_KILL_TIMEOUT_S = 10


def _mount_source(workspace: Path) -> str:
    """Render a bind-mount source Docker accepts, incl. Windows drive paths.

    ``C:\\Users\\me\\proj`` -> ``/c/Users/me/proj`` (Docker Desktop understands this and it
    avoids the drive-letter colon confusing ``-v``'s ``src:dst`` parsing).
    """
    p = workspace.resolve()
    if os.name == "nt" and p.drive:
        return "/" + p.drive[0].lower() + p.as_posix()[len(p.drive):]
    return p.as_posix()


class DockerExecutor:
    name = "docker"

    def __init__(self, sandbox: SandboxConfig):
        self.image = sandbox.docker_image
        self.memory = sandbox.docker_memory
        self.cpus = sandbox.docker_cpus
        self.network = sandbox.docker_network

    def python_argv(self) -> list[str]:
        # Inside the container the interpreter is simply `python`.
        return ["python", "-I", "-"]

    def _docker_prefix(self, policy: SandboxPolicy, name: str | None = None) -> list[str]:
        cmd = [
            "docker", "run", "--rm", "-i",
            "--memory", self.memory,
            "--cpus", self.cpus,
            "--pids-limit", "256",
            "-w", _CONTAINER_WORKDIR,
            "-v", f"{_mount_source(policy.workspace)}:{_CONTAINER_WORKDIR}",
        ]
        if not self.network:
            cmd += ["--network", "none"]
        if name:
            # A known name is the only handle on the container once `docker run` is killed:
            # killing the client leaves the container running (and `--rm` never fires).
            cmd += ["--name", name]
        cmd.append(self.image)
        return cmd

    def build_command(
        self,
        policy: SandboxPolicy,
        *,
        args: list[str] | None,
        shell_command: str | None,
        name: str | None = None,
    ) -> list[str]:
        prefix = self._docker_prefix(policy, name)
        if shell_command is not None:
            return prefix + ["sh", "-c", shell_command]
        return prefix + (args or [])

    def run(
        self,
        policy: SandboxPolicy,
        *,
        args: list[str] | None = None,
        shell_command: str | None = None,
        stdin: str | None = None,
    ) -> ExecResult:
        if (args is None) == (shell_command is None):
            raise ValueError("Provide exactly one of 'args' or 'shell_command'.")
        name = f"agent86-{uuid.uuid4().hex[:12]}"
        command = self.build_command(policy, args=args, shell_command=shell_command, name=name)
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=policy.timeout_s,
                input=stdin,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            # subprocess.run only killed the `docker run` client; the container keeps going.
            killed = self._kill_container(name)
            note = "" if killed else " (container may still be running)"
            return ExecResult(
                returncode=124, stdout="",
                stderr=f"[timed out after {policy.timeout_s}s]{note}",
                timed_out=True,
            )
        except FileNotFoundError as exc:
            return ExecResult(returncode=127, stdout="", stderr=f"docker not found: {exc}")
        return ExecResult(
            returncode=proc.returncode,
            stdout=policy.truncate(proc.stdout or ""),
            stderr=policy.truncate(proc.stderr or ""),
        )

    def _kill_container(self, name: str) -> bool:
        """Stop the orphaned container by name. Best effort, never raises."""
        try:
            killed = subprocess.run(
                ["docker", "kill", name], capture_output=True, timeout=_KILL_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Could not kill timed-out container %s: %s", name, exc)
            return False
        if killed.returncode != 0:
            logger.warning("docker kill %s exited %s", name, killed.returncode)
        return killed.returncode == 0


__all__ = ["DockerExecutor"]
