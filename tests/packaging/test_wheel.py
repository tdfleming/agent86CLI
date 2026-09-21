"""What the built artifacts contain — and, just as importantly, what they don't.

A wheel that ships `tests/`, `.planning/` or stale `__pycache__` is both larger and leakier than
it needs to be, and the exclusions that prevent that live in `pyproject.toml` where nothing else
would notice them rotting.
"""

from __future__ import annotations

import email
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from .conftest import REPO_ROOT, run_captured

pytestmark = pytest.mark.packaging

# Development scaffolding that must never appear as a path segment inside a distribution.
FORBIDDEN_SEGMENTS = ("tests", ".planning", "__pycache__", ".github", ".claude", ".venv")


def _wheel_metadata(wheel: Path) -> email.message.Message:
    with zipfile.ZipFile(wheel) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
        return email.message_from_bytes(zf.read(name))


def test_wheel_version_matches_pyproject(wheel_path: Path, project_version: str) -> None:
    assert wheel_path.name.startswith(f"agent86-{project_version}-")
    assert _wheel_metadata(wheel_path)["Version"] == project_version


def test_wheel_excludes_development_trees(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as zf:
        names = zf.namelist()

    assert names, "the wheel is empty"
    offenders = [
        name for name in names if any(segment in FORBIDDEN_SEGMENTS for segment in Path(name).parts)
    ]
    assert offenders == [], f"development files leaked into the wheel: {offenders}"
    assert not [n for n in names if n.endswith((".pyc", ".pyo"))]


def test_wheel_ships_the_package_and_its_entry_point(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as zf:
        names = set(zf.namelist())
        entry_points = zf.read(
            next(n for n in names if n.endswith(".dist-info/entry_points.txt"))
        ).decode()

    assert "agent86/__init__.py" in names
    assert "agent86/cli.py" in names
    # The TUI is lazy-imported, but it still has to be *in* the wheel.
    assert any(n.startswith("agent86/tui/") for n in names)
    assert "agent86 = agent86.cli:app" in entry_points


def test_wheel_metadata_is_publishable(wheel_path: Path, project_version: str) -> None:
    meta = _wheel_metadata(wheel_path)
    classifiers = meta.get_all("Classifier") or []

    assert meta["Name"] == "agent86"
    assert meta["Requires-Python"] == ">=3.11"
    assert meta["Description-Content-Type"] == "text/markdown"
    assert "License :: OSI Approved :: MIT License" in classifiers
    assert "Programming Language :: Python :: 3.11" in classifiers
    assert "Environment :: Console" in classifiers

    urls = " ".join(meta.get_all("Project-URL") or [])
    for label in ("Homepage", "Repository", "Changelog", "Issues"):
        assert label in urls, f"project.urls is missing {label!r}"

    # The long description is the PyPI landing page; an empty one is a broken release.
    assert len(meta.get_payload()) > 500
    assert project_version in (meta["Version"] or "")


def test_sdist_carries_the_docs_a_packager_needs(sdist_path: Path, project_version: str) -> None:
    with tarfile.open(sdist_path) as tf:
        names = tf.getnames()

    root = f"agent86-{project_version}"
    for expected in ("README.md", "CHANGELOG.md", "LICENSE", "docs/ARCHITECTURE.md"):
        assert f"{root}/{expected}" in names, f"sdist is missing {expected}"

    offenders = [
        name for name in names if any(segment in FORBIDDEN_SEGMENTS for segment in Path(name).parts)
    ]
    assert offenders == [], f"development files leaked into the sdist: {offenders}"


def test_twine_check_passes(dist_dir: Path) -> None:
    """`twine check` is the gate PyPI itself applies to the README and metadata."""
    pytest.importorskip("twine", reason="`twine` is in the dev extra")
    artifacts = sorted(dist_dir.glob("agent86-*"))
    result = run_captured([sys.executable, "-m", "twine", "check", *artifacts], cwd=REPO_ROOT)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "FAILED" not in result.stdout


def test_license_file_is_present_in_the_wheel(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as zf:
        licenses = [n for n in zf.namelist() if "dist-info/licenses/" in n]
    assert licenses, "the wheel ships no LICENSE"
