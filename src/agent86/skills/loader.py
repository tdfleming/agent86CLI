"""Skill discovery and the SKILL.md frontmatter parser.

A skill is a folder containing ``SKILL.md``:

    ---
    name: pirate-speak
    description: Rewrite text in pirate dialect.
    allowed-tools: read_file, write_file
    ---
    When invoked, rewrite the user's text as a pirate would speak...

Only ``name`` + ``description`` are surfaced to the model up front (progressive disclosure);
the body loads on demand when the agent calls ``use_skill``. The frontmatter parser is
intentionally tiny (key: value + simple lists) so skills need no YAML dependency.
"""

from __future__ import annotations

from pathlib import Path

from agent86.config import Config
from agent86.skills.models import Skill


def parse_skill_md(text: str) -> tuple[dict[str, str], str]:
    """Split a SKILL.md into (frontmatter dict, body)."""
    meta: dict[str, str] = {}
    body = text
    stripped = text.lstrip("﻿")  # tolerate BOM
    if stripped.startswith("---"):
        parts = stripped.split("---", 2)
        if len(parts) >= 3:
            frontmatter, body = parts[1], parts[2].lstrip("\n")
            for line in frontmatter.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, _, value = line.partition(":")
                meta[key.strip().lower()] = value.strip().strip("'\"")
    return meta, body


def _parse_list(value: str) -> list[str]:
    value = value.strip().strip("[]")
    return [item.strip().strip("'\"") for item in value.split(",") if item.strip()]


def _load_skill(skill_md: Path) -> Skill | None:
    try:
        meta, _ = parse_skill_md(skill_md.read_text(encoding="utf-8"))
    except OSError:
        return None
    name = meta.get("name") or skill_md.parent.name
    description = meta.get("description", "")
    allowed = _parse_list(meta["allowed-tools"]) if "allowed-tools" in meta else []
    return Skill(name=name, description=description, path=skill_md, allowed_tools=allowed)


def default_skill_paths(config: Config) -> list[Path]:
    paths = [Path.home() / ".agent86" / "skills", Path(".agent86") / "skills"]
    paths += [Path(p).expanduser() for p in config.skills.paths]
    return paths


def discover_skills(config: Config) -> dict[str, Skill]:
    """Find all skills across the configured paths, keyed by name (first wins on conflict)."""
    if not config.skills.enabled:
        return {}
    found: dict[str, Skill] = {}
    for root in default_skill_paths(config):
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            skill_md = entry / "SKILL.md"
            if entry.is_dir() and skill_md.is_file():
                skill = _load_skill(skill_md)
                if skill and skill.name not in found:
                    found[skill.name] = skill
    return found


__all__ = ["discover_skills", "parse_skill_md", "default_skill_paths"]
