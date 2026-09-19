"""v0.7 — a timed-out tool must take its whole process tree with it.

These tests spawn real processes (a parent that forks a long-lived grandchild) with a ~1s
budget, so they stay fast while proving the kill actually cascades.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

from agent86.tools.sandbox.policy import SandboxPolicy
from agent86.tools.sandbox.subprocess_exec import run_subprocess

SPAWNER = """
import subprocess, sys, time

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(child.pid, flush=True)
time.sleep(120)
"""


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - not ours, but it exists
        return True
    return True


def _wait_gone(pid: int, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


def test_timeout_kills_the_grandchild_too(tmp_path):
    script = tmp_path / "spawner.py"
    script.write_text(SPAWNER, encoding="utf-8")
    policy = SandboxPolicy(workspace=tmp_path, timeout_s=1)

    res = run_subprocess(policy, args=[sys.executable, str(script)])

    assert res.timed_out and res.returncode == 124
    assert "timed out after 1s" in res.stderr
    grandchild = int(res.stdout.strip().splitlines()[0])
    assert _wait_gone(grandchild), f"grandchild {grandchild} survived the timeout"


def test_timeout_kills_a_shell_tree(tmp_path):
    script = tmp_path / "spawner.py"
    script.write_text(SPAWNER, encoding="utf-8")
    policy = SandboxPolicy(workspace=tmp_path, timeout_s=1)

    res = run_subprocess(policy, shell_command=f'"{sys.executable}" "{script}"')

    assert res.timed_out
    grandchild = int(res.stdout.strip().splitlines()[0])
    assert _wait_gone(grandchild), f"grandchild {grandchild} survived the shell timeout"


def test_normal_command_still_returns_output_and_code(tmp_path):
    policy = SandboxPolicy(workspace=tmp_path, timeout_s=30)
    res = run_subprocess(policy, args=[sys.executable, "-c", "print('hello')"])
    assert res.ok and "hello" in res.stdout

    failed = run_subprocess(policy, args=[sys.executable, "-c", "raise SystemExit(3)"])
    assert failed.returncode == 3 and not failed.ok


def test_stdin_is_delivered(tmp_path):
    policy = SandboxPolicy(workspace=tmp_path, timeout_s=30)
    res = run_subprocess(
        policy,
        args=[sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
        stdin="shout",
    )
    assert res.ok and "SHOUT" in res.stdout


def test_stdin_is_closed_when_none_so_a_reader_cannot_hang(tmp_path):
    """No stdin means EOF, not the user's terminal — otherwise the tool blocks until timeout."""
    policy = SandboxPolicy(workspace=tmp_path, timeout_s=10)
    code = "import sys; print(len(sys.stdin.read()))"
    res = run_subprocess(policy, args=[sys.executable, "-c", code])
    assert res.ok and res.stdout.strip() == "0"
