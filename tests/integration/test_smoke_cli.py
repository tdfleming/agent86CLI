"""Smoke: every command surface starts, on a machine with nothing configured.

These run the real entry point in a real subprocess (``python -m agent86``) under a temp
HOME with no config file and no API keys — the state a first-time user, or a CI runner, is
actually in. The bar is deliberately low and absolute: exit 0, and no traceback. A CLI that
crashes before it can tell you what's missing is the worst possible first impression, and
that failure mode is invisible to in-process tests, which share the developer's own
environment.

The cold-start guard is here rather than in ``tests/tui`` because it is a property of the
*scripting* path: ``agent86 run`` and ``--plain`` must not pay for Textual, keyring, tomlkit,
OpenTelemetry, or torch. Set ``AGENT86_SKIP_PERF=1`` to skip the wall-clock half on a slow
or heavily-loaded runner; the import-graph half is deterministic and always runs.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

#: Modules the scripting entry point must never pull in. Each is either a heavy optional
#: dependency (Textual, torch, OpenTelemetry) or one that touches the OS/keychain or rewrites
#: config (keyring, tomlkit) — all of them lazy-imported by contract.
FORBIDDEN_IMPORTS = ("textual", "keyring", "tomlkit", "opentelemetry", "torch")

#: Generous on purpose: this is a regression guard against someone adding a top-level import
#: of a 3-second dependency, not a benchmark.
COLD_START_BUDGET_S = 1.5


def _bare_env(home) -> dict[str, str]:
    """The process environment of a machine with no agent86 setup at all."""
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    for var in list(env):
        if var.endswith("_API_KEY"):
            env.pop(var)
    return env


def _run(argv: list[str], home) -> subprocess.CompletedProcess:
    # utf-8 explicitly: the CLI reconfigures its own streams to UTF-8 on startup (Windows
    # console quirk), so decoding its output with the ambient code page corrupts it.
    return subprocess.run(
        [sys.executable, "-m", "agent86", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(home),
        env=_bare_env(home),
    )


def _command_paths() -> list[list[str]]:
    """Every command and sub-command the app exposes, as argv prefixes.

    Discovered from the Typer app rather than hard-coded, so a command added later is
    smoke-tested without anyone remembering to add it here.
    """
    import typer.main

    from agent86.cli import app

    found: list[list[str]] = []

    def walk(command, prefix: list[str]) -> None:
        found.append(prefix)
        # Duck-typed rather than `isinstance(..., click.Group)`: Typer's own group class
        # does not test as one under every click/typer pairing.
        for name, sub in sorted(getattr(command, "commands", {}).items()):
            walk(sub, [*prefix, name])

    walk(typer.main.get_command(app), [])
    return found


@pytest.fixture
def home(tmp_path):
    """A HOME with no ``.agent86`` in it, used as the CWD too (so no project config)."""
    return tmp_path


def _assert_clean(result: subprocess.CompletedProcess, argv: list[str]) -> None:
    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"{argv} exited {result.returncode}\n{combined}"
    assert "Traceback (most recent call last)" not in combined, combined


def test_version(home):
    result = _run(["--version"], home)

    _assert_clean(result, ["--version"])
    assert "agent86" in result.stdout


def test_root_help(home):
    result = _run(["--help"], home)

    _assert_clean(result, ["--help"])
    assert "run" in result.stdout


@pytest.mark.parametrize("path", _command_paths(), ids=lambda p: " ".join(p) or "(root)")
def test_every_command_help(path, home):
    argv = [*path, "--help"]

    _assert_clean(_run(argv, home), argv)


# --------------------------------------------------------------------------- #
# cold start
# --------------------------------------------------------------------------- #


def _imported_packages(stderr: str) -> set[str]:
    """Top-level package names from ``-X importtime`` output."""
    names: set[str] = set()
    for line in stderr.splitlines():
        if not line.startswith("import time:"):
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        module = parts[2].strip()
        if module and module != "imported package":
            names.add(module.split(".")[0])
    return names


def test_importing_the_cli_pulls_in_no_heavy_dependency(home):
    result = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", "import agent86.cli"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(home),
        env=_bare_env(home),
    )

    assert result.returncode == 0, result.stderr
    imported = _imported_packages(result.stderr)
    assert imported, "importtime produced no parseable output"
    leaked = sorted(imported & set(FORBIDDEN_IMPORTS))
    assert not leaked, f"agent86.cli imported {leaked} at module level; keep them lazy"


@pytest.mark.skipif(
    bool(os.getenv("AGENT86_SKIP_PERF")), reason="AGENT86_SKIP_PERF is set (slow/loaded runner)"
)
def test_cold_start_stays_under_budget(home):
    # Warm the interpreter's own caches first, so the measured run times agent86 rather than
    # the filesystem's first look at site-packages.
    _run(["--version"], home)

    started = time.perf_counter()
    result = _run(["--version"], home)
    elapsed = time.perf_counter() - started

    _assert_clean(result, ["--version"])
    assert elapsed < COLD_START_BUDGET_S, (
        f"`agent86 --version` took {elapsed:.2f}s (budget {COLD_START_BUDGET_S}s) — "
        "something heavy is being imported at module level"
    )
