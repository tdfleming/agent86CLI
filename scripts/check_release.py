#!/usr/bin/env python
"""Pre-flight checks that must pass before agent86 is tagged and published.

Run it locally before tagging, and first in the release workflow::

    python scripts/check_release.py --tag v1.0.0

It verifies, in order:

1. the git tag, ``project.version`` in ``pyproject.toml``, and ``agent86.__version__`` all
   name the same version;
2. ``CHANGELOG.md`` has a ``## [<version>]`` section with a real body;
3. ``## [Unreleased]`` is empty — anything still sitting there was meant for this release.

Why the version is a literal
----------------------------
``agent86.__version__`` stays a plain string in ``src/agent86/__init__.py`` rather than being
derived from ``importlib.metadata.version("agent86")``. Both approaches keep ``agent86
--version`` correct in an editable install and in a wheel, so the tie-breakers are cost and
failure mode:

* ``importlib.metadata`` is a real import on the cold-start path, and cold start for scripting is
  an explicit constraint of this project (see CLAUDE.md). A literal costs nothing.
* ``importlib.metadata.version()`` raises ``PackageNotFoundError`` when the package is merely on
  ``sys.path`` and not installed — running from a source checkout, a vendored copy, or a zipapp —
  which turns ``--version`` into a crash in exactly the situations where it is least expected.

The cost of a literal is that it can drift from ``pyproject.toml``. That drift is a *release*
concern, not a runtime one, so this script is where it is caught: the duplication is real but it
is mechanically checked once per release, and the packaging tests assert the same equality
against the built wheel.

Exit code is 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
INIT_PY = REPO_ROOT / "src" / "agent86" / "__init__.py"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-.a-zA-Z0-9]*)$")


@dataclass
class Report:
    """Accumulated check results — collected in full so one run shows every problem."""

    failures: list[str]

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        if ok:
            print(f"  ok    {label}")
        else:
            print(f"  FAIL  {label}{': ' + detail if detail else ''}")
            self.failures.append(f"{label}{': ' + detail if detail else ''}")
        return ok


def pyproject_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def package_version() -> str:
    """Load ``src/agent86/__init__.py`` directly, so an installed copy can't shadow the source."""
    spec = importlib.util.spec_from_file_location("_agent86_version_probe", INIT_PY)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {INIT_PY}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module.__version__)


def normalise_tag(tag: str) -> str:
    """``v1.0.0`` and ``1.0.0`` both name version ``1.0.0``."""
    return tag[1:] if tag.startswith("v") else tag


def changelog_sections(text: str) -> dict[str, str]:
    """Map each ``## [name]`` heading to its body, up to the next ``## `` heading."""
    sections: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        heading = re.match(r"^##\s+\[([^\]]+)\]", line)
        if heading:
            if current is not None:
                sections[current] = "\n".join(body).strip()
            current = heading.group(1)
            body = []
        elif current is not None:
            if line.startswith("## "):  # a non-bracketed heading still ends the section
                sections[current] = "\n".join(body).strip()
                current = None
                body = []
            else:
                body.append(line)
    if current is not None:
        sections[current] = "\n".join(body).strip()
    return sections


def _resolve_tag(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    ref = os.environ.get("GITHUB_REF_NAME", "")
    if ref and os.environ.get("GITHUB_REF_TYPE") == "tag":
        return ref
    return None


def run_checks(tag: str | None) -> Report:
    report = Report(failures=[])

    print("Version")
    proj = pyproject_version()
    pkg = package_version()
    report.check(bool(VERSION_RE.match(proj)), "pyproject version is well-formed", f"got {proj!r}")
    report.check(
        pkg == proj,
        "agent86.__version__ matches pyproject",
        f"__init__.py says {pkg!r}, pyproject says {proj!r}",
    )
    if tag is None:
        print("  skip  tag comparison (no --tag and not a tag build)")
    else:
        report.check(
            normalise_tag(tag) == proj,
            "git tag matches pyproject",
            f"tag {tag!r} -> {normalise_tag(tag)!r}, pyproject says {proj!r}",
        )

    print("Changelog")
    if not CHANGELOG.exists():
        report.check(False, "CHANGELOG.md exists", str(CHANGELOG))
        return report

    sections = changelog_sections(CHANGELOG.read_text(encoding="utf-8"))
    has_section = proj in sections
    report.check(
        has_section,
        f"CHANGELOG has a [{proj}] section",
        f"headings found: {sorted(sections)}",
    )
    if has_section:
        report.check(
            len(sections[proj]) > 0,
            f"the [{proj}] section has a body",
            "the section is empty",
        )
    unreleased = sections.get("Unreleased")
    if unreleased is None:
        print("  skip  [Unreleased] section is absent")
    else:
        report.check(
            unreleased == "",
            "[Unreleased] is empty",
            f"{len(unreleased.splitlines())} line(s) still unreleased — move them into "
            f"[{proj}] or cut a different version",
        )

    print("Files")
    for name in ("README.md", "LICENSE", "docs/ARCHITECTURE.md"):
        report.check((REPO_ROOT / name).exists(), f"{name} is present")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--tag",
        help="the tag being released, e.g. v1.0.0 (defaults to GITHUB_REF_NAME on a tag build)",
    )
    args = parser.parse_args(argv)

    report = run_checks(_resolve_tag(args.tag))
    print()
    if report.failures:
        print(f"check_release: {len(report.failures)} problem(s) — not ready to publish")
        return 1
    print(f"check_release: ready to publish {pyproject_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
