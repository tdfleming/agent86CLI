"""Session fixtures for the packaging tests.

These build the *real* sdist and wheel with `python -m build` and install the wheel into a
throwaway virtualenv, so the assertions run against the artifact a user would actually get from
PyPI rather than against the source tree. Both steps are session-scoped and shared by every
module here: one build, one venv, roughly 25s on a warm pip cache.

Everything in this package is marked `packaging` and excluded from the default `pytest` run by
`addopts = "-m 'not packaging'"`; CI's `package` job and the release workflow opt in with
`pytest -m packaging tests/packaging`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Modules the CLI entry path must never pull in — the lazy-import contract from CLAUDE.md.
LAZY_ONLY_MODULES = ("textual", "keyring", "tomlkit")


@dataclass(frozen=True)
class Venv:
    """A throwaway virtualenv with the freshly built wheel installed into it."""

    root: Path

    @property
    def _bin(self) -> Path:
        return self.root / ("Scripts" if os.name == "nt" else "bin")

    @property
    def python(self) -> Path:
        return self._bin / ("python.exe" if os.name == "nt" else "python")

    @property
    def agent86(self) -> Path:
        return self._bin / ("agent86.exe" if os.name == "nt" else "agent86")


def run_captured(
    args: list[str | Path],
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    timeout: float = 300.0,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with decoded, colour-free output.

    `home` redirects HOME/USERPROFILE so an `agent86` invocation can't write the flight recorder
    into the developer's real `~/.agent86`. The build and install steps deliberately *don't* set
    it — they need the real pip/uv caches, or every run re-downloads the dependency tree.
    """
    env = dict(os.environ)
    # Rich gives FORCE_COLOR precedence over NO_COLOR and still emits bold/dim attributes under
    # NO_COLOR alone; the release workflow sets FORCE_COLOR=1 for readable logs, which turned
    # `agent86 1.0.0` into `agent86 \x1b[1m1.0\x1b[0m...` and broke the plain-text asserts.
    env.pop("FORCE_COLOR", None)
    env.update(
        {
            "NO_COLOR": "1",
            "TERM": "dumb",
            "COLUMNS": "200",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        }
    )
    if home is not None:
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
    env.pop("PYTHONPATH", None)  # never let the source tree shadow the installed wheel
    result = subprocess.run(
        [str(a) for a in args],
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    # Belt and braces: whatever the environment did, the asserts see plain text.
    return subprocess.CompletedProcess(
        result.args, result.returncode, _strip_ansi(result.stdout), _strip_ansi(result.stderr)
    )


_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


@pytest.fixture(scope="session")
def project_version() -> str:
    """The version declared in pyproject.toml — the single source of truth."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


@pytest.fixture(scope="session")
def dist_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the sdist and the wheel into a temp directory (never the repo's own `dist/`)."""
    pytest.importorskip("build", reason="`build` is in the dev extra; needed to make artifacts")
    out = tmp_path_factory.mktemp("dist")
    result = run_captured([sys.executable, "-m", "build", "--outdir", out, REPO_ROOT])
    assert result.returncode == 0, f"python -m build failed:\n{result.stdout}\n{result.stderr}"
    return out


@pytest.fixture(scope="session")
def wheel_path(dist_dir: Path) -> Path:
    wheels = sorted(dist_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {[w.name for w in wheels]}"
    return wheels[0]


@pytest.fixture(scope="session")
def sdist_path(dist_dir: Path) -> Path:
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    assert len(sdists) == 1, f"expected exactly one sdist, got {[s.name for s in sdists]}"
    return sdists[0]


@pytest.fixture(scope="session")
def installed_venv(tmp_path_factory: pytest.TempPathFactory, wheel_path: Path) -> Venv:
    """A fresh venv with the wheel (and its runtime deps) installed."""
    root = tmp_path_factory.mktemp("venv")
    created = run_captured([sys.executable, "-m", "venv", root])
    assert created.returncode == 0, f"venv creation failed:\n{created.stderr}"

    venv = Venv(root)
    installed = run_captured(
        [venv.python, "-m", "pip", "install", "--quiet", "--force-reinstall", wheel_path],
        cwd=root,
    )
    assert installed.returncode == 0, (
        f"installing the wheel failed:\n{installed.stdout}\n{installed.stderr}"
    )
    assert venv.agent86.exists(), f"console script missing at {venv.agent86}"
    return venv
