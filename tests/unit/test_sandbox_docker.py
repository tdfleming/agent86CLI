"""Phase 9 — executor selection, Docker command construction, subprocess execution."""

from __future__ import annotations

import sys

from agent86.config import SandboxConfig, load_config
from agent86.tools.base import ToolContext
from agent86.tools.builtin.shell import RunCommandTool
from agent86.tools.sandbox import executor as exec_mod
from agent86.tools.sandbox.docker_exec import DockerExecutor
from agent86.tools.sandbox.executor import SubprocessExecutor, build_executor
from agent86.tools.sandbox.policy import SandboxPolicy, default_policy
from agent86.tools.sandbox.subprocess_exec import ExecResult
from agent86.types import ToolCall


def test_build_executor_default_is_subprocess():
    ex, note = build_executor(load_config())
    assert isinstance(ex, SubprocessExecutor)
    assert note is None


def test_build_executor_docker_falls_back_when_unavailable(monkeypatch):
    cfg = load_config()
    cfg.sandbox.mode = "docker"
    monkeypatch.setattr(exec_mod, "docker_available", lambda: False)
    ex, note = build_executor(cfg)
    assert isinstance(ex, SubprocessExecutor)
    assert note and "falling back" in note


def test_build_executor_docker_when_available(monkeypatch):
    cfg = load_config()
    cfg.sandbox.mode = "docker"
    monkeypatch.setattr(exec_mod, "docker_available", lambda: True)
    ex, note = build_executor(cfg)
    assert isinstance(ex, DockerExecutor)
    assert note is None


def test_subprocess_executor_runs(tmp_path):
    ex = SubprocessExecutor()
    res = ex.run(SandboxPolicy(workspace=tmp_path), shell_command="echo hello")
    assert res.ok
    assert "hello" in res.stdout
    assert ex.python_argv()[0] == sys.executable


def test_docker_build_command(tmp_path):
    ex = DockerExecutor(
        SandboxConfig(docker_image="python:3.12-slim", docker_memory="256m", docker_cpus="2")
    )
    policy = SandboxPolicy(workspace=tmp_path)

    shell_cmd = ex.build_command(policy, args=None, shell_command="echo hi")
    assert shell_cmd[0] == "docker" and "run" in shell_cmd
    assert "--network" in shell_cmd and "none" in shell_cmd
    assert "--memory" in shell_cmd and "256m" in shell_cmd
    assert "--cpus" in shell_cmd and "2" in shell_cmd
    assert "python:3.12-slim" in shell_cmd
    assert shell_cmd[-3:] == ["sh", "-c", "echo hi"]

    py_cmd = ex.build_command(policy, args=ex.python_argv(), shell_command=None)
    assert py_cmd[-3:] == ["python", "-I", "-"]


def test_docker_network_enabled_omits_none(tmp_path):
    ex = DockerExecutor(SandboxConfig(docker_network=True))
    cmd = ex.build_command(SandboxPolicy(workspace=tmp_path), args=None, shell_command="echo hi")
    assert "--network" not in cmd


def test_tool_uses_context_executor(tmp_path):
    """A shell/python tool must run through ctx.executor, not hardcode the default."""
    calls: list = []

    class RecordingExecutor:
        name = "rec"

        def run(self, policy, *, args=None, shell_command=None, stdin=None):
            calls.append(shell_command or args)
            return ExecResult(returncode=0, stdout="ok", stderr="")

        def python_argv(self):
            return ["python"]

    cfg = load_config()
    ctx = ToolContext(
        workspace=tmp_path,
        policy=default_policy(cfg, tmp_path),
        config=cfg,
        executor=RecordingExecutor(),
    )
    res = RunCommandTool().run(
        ToolCall(id="1", name="run_command", arguments={"command": "echo hi"}), ctx
    )
    assert res.ok
    assert calls == ["echo hi"]
