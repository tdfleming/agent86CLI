"""The installed wheel, driven the way a user would drive it.

Everything here runs the `agent86` console script (or the installed interpreter) out of a fresh
venv — no source tree on `sys.path`, no editable install, no conftest monkeypatching. If the
entry point, the version, or the lazy-import contract is broken in the artifact but fine in the
repo, this is where it shows up.
"""

from __future__ import annotations

import json

import pytest

from .conftest import LAZY_ONLY_MODULES, Venv, run_captured

pytestmark = pytest.mark.packaging


def test_console_script_reports_the_pyproject_version(
    installed_venv: Venv, project_version: str
) -> None:
    result = run_captured([installed_venv.agent86, "--version"], cwd=installed_venv.root)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert result.stdout.strip() == f"agent86 {project_version}"


def test_package_metadata_version_matches_the_dunder_version(
    installed_venv: Venv, project_version: str
) -> None:
    """`__version__` is a literal that `check_release.py` guards; both must agree in the wheel."""
    code = (
        "import json, importlib.metadata as m, agent86;"
        'print(json.dumps({"dunder": agent86.__version__, "dist": m.version("agent86")}))'
    )
    result = run_captured([installed_venv.python, "-c", code], cwd=installed_venv.root)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    reported = json.loads(result.stdout.strip().splitlines()[-1])
    assert reported["dunder"] == project_version
    assert reported["dist"] == project_version


def test_run_help_exits_zero(installed_venv: Venv) -> None:
    """`run` is the scripting/CI contract; its help must work in a bare install."""
    result = run_captured([installed_venv.agent86, "run", "--help"], cwd=installed_venv.root)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "--json" in result.stdout


def test_top_level_help_exits_zero(installed_venv: Venv) -> None:
    result = run_captured([installed_venv.agent86, "--help"], cwd=installed_venv.root)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_python_dash_m_entry_works(installed_venv: Venv, project_version: str) -> None:
    result = run_captured(
        [installed_venv.python, "-m", "agent86", "--version"], cwd=installed_venv.root
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert project_version in result.stdout


def test_importing_the_cli_stays_lazy(installed_venv: Venv) -> None:
    """Textual, keyring and tomlkit must not be dragged in by `import agent86.cli`."""
    code = (
        "import sys, json, agent86.cli;"
        f"print(json.dumps([m for m in {LAZY_ONLY_MODULES!r} if m in sys.modules]))"
    )
    result = run_captured([installed_venv.python, "-c", code], cwd=installed_venv.root)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    eager = json.loads(result.stdout.strip().splitlines()[-1])
    assert eager == [], f"lazy-import contract broken: {eager} imported by agent86.cli"


def test_run_help_stays_lazy(installed_venv: Venv) -> None:
    """The one-shot path itself, not just the module import, must avoid the heavy deps."""
    code = (
        "import sys, json;"
        "sys.argv = ['agent86', 'run', '--help'];"
        "import agent86.cli as c;"
        "\ntry:\n    c.app()\nexcept SystemExit:\n    pass\n"
        f"sys.stderr.write(json.dumps([m for m in {LAZY_ONLY_MODULES!r} if m in sys.modules]))"
    )
    result = run_captured([installed_venv.python, "-c", code], cwd=installed_venv.root)
    eager = json.loads(result.stderr.strip().splitlines()[-1])
    assert eager == [], f"`run --help` eagerly imported {eager}"
