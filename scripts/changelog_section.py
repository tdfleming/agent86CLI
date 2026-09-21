#!/usr/bin/env python
"""Extract one version's section from CHANGELOG.md — the body of a GitHub Release.

    python scripts/changelog_section.py 1.0.0
    python scripts/changelog_section.py v1.0.0 --output release-notes.md
    python scripts/changelog_section.py 1.0.0 --heading   # keep the `## [1.0.0] - …` line

Prints the section body (everything between ``## [<version>]`` and the next ``## `` heading) to
stdout, or writes it to ``--output``. Exits 1 with a list of the headings it did find when the
version has no section, so a release stops before it publishes empty notes.

The parser is shared with ``check_release.py``, which is what guarantees the section exists in
the first place.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_release import (  # noqa: E402
    CHANGELOG,
    changelog_sections,
    force_utf8_stdio,
    normalise_tag,
)

HEADING_RE = re.compile(r"^##\s+\[([^\]]+)\].*$")


def section_heading(text: str, version: str) -> str:
    """The literal `## [1.0.0] - 2026-09-21` line, so `--heading` keeps the date."""
    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match and match.group(1) == version:
            return line
    return f"## [{version}]"


def extract(text: str, version: str, *, heading: bool = False) -> str | None:
    sections = changelog_sections(text)
    body = sections.get(version)
    if body is None:
        return None
    return f"{section_heading(text, version)}\n\n{body}".strip() if heading else body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract one version's section from CHANGELOG.md.",
    )
    parser.add_argument("version", help="the version to extract, with or without a leading 'v'")
    parser.add_argument("--output", type=Path, help="write to this file instead of stdout")
    parser.add_argument("--changelog", type=Path, default=CHANGELOG, help="path to CHANGELOG.md")
    parser.add_argument(
        "--heading", action="store_true", help="include the `## [version] - date` heading line"
    )
    args = parser.parse_args(argv)

    force_utf8_stdio()
    if not args.changelog.exists():
        print(f"changelog_section: no such file: {args.changelog}", file=sys.stderr)
        return 1

    text = args.changelog.read_text(encoding="utf-8")
    version = normalise_tag(args.version)
    body = extract(text, version, heading=args.heading)

    if body is None:
        found = sorted(changelog_sections(text))
        print(
            f"changelog_section: no [{version}] section in {args.changelog.name}; "
            f"headings found: {found}",
            file=sys.stderr,
        )
        return 1
    if not body.strip():
        print(f"changelog_section: the [{version}] section is empty", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(body + "\n", encoding="utf-8")
        print(f"changelog_section: wrote {len(body.splitlines())} line(s) to {args.output}")
    else:
        sys.stdout.write(body + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
