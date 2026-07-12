"""Execution backends for Tier 4.

The sandbox has two interchangeable backends behind one interface: the default restricted
subprocess (fast, pragmatic on Windows) and an opt-in Docker container (true isolation).
Tools call ``executor.run(...)`` and ``executor.python_argv()`` without knowing which backend
is active; :func:`build_executor` picks one from config and falls back to subprocess (with a
note) if Docker was requested but isn't usable.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Protocol

from agent86.config import Config
from agent86.tools.sandbox.policy import SandboxPolicy
from agent86.tools.sandbox.subprocess_exec import ExecResult, run_subprocess


class Executor(Protocol):
    name: str

    def run(
        self,
        policy: SandboxPolicy,
        *,
        args: list[str] | None = None,
        shell_command: str | None = None,
        stdin: str | None = None,
    ) -> ExecResult: ...

    def python_argv(self) -> list[str]: ...


class SubprocessExecutor:
    """Runs commands in a restricted subprocess on the host."""

    name = "subprocess"

    def run(
        self,
        policy: SandboxPolicy,
        *,
        args: list[str] | None = None,
        shell_command: str | None = None,
        stdin: str | None = None,
    ) -> ExecResult:
        return run_subprocess(policy, args=args, shell_command=shell_command, stdin=stdin)

    def python_argv(self) -> list[str]:
        # Use this interpreter on the host, isolated from site/user config.
        return [sys.executable, "-I", "-"]


_DEFAULT = SubprocessExecutor()


def get_default_executor() -> SubprocessExecutor:
    return _DEFAULT


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10, text=True
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def build_executor(config: Config) -> tuple[Executor, str | None]:
    """Return ``(executor, note)`` for the configured sandbox mode."""
    if config.sandbox.mode == "docker":
        if docker_available():
            from agent86.tools.sandbox.docker_exec import DockerExecutor

            return DockerExecutor(config.sandbox), None
        return _DEFAULT, (
            "Docker requested but not available; falling back to the subprocess sandbox."
        )
    return _DEFAULT, None


__all__ = [
    "Executor",
    "SubprocessExecutor",
    "build_executor",
    "get_default_executor",
    "docker_available",
]
