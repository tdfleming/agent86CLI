"""Skill discovery and the SKILL.md frontmatter parser (Agent Skills convention).

A skill is a folder containing ``SKILL.md`` with YAML frontmatter:

    ---
    name: pirate-speak
    description: >
      Rewrite text in pirate dialect. Use when the user asks for pirate
      voice, sea-shanty phrasing, or a nautical rewrite.
    allowed-tools: read_file write_file
    license: MIT
    metadata:
      version: 1.2.0
    ---
    When invoked, rewrite the user's text as a pirate would speak...

Only ``name`` + ``description`` are surfaced to the model up front (progressive disclosure);
the body loads on demand when the agent calls ``use_skill``.

**Search order** (first match wins — an earlier root *overrides* a later one, so a project
skill shadows a user skill of the same name, and nothing overrides a project skill)::

    <workspace>/.agent86/skills   →  project, agent86's own
    <workspace>/.claude/skills    →  project, shared with Claude Code
    ~/.agent86/skills            →  user
    ~/.claude/skills             →  user, shared with Claude Code
    [skills] paths               →  whatever the config adds, in order

The project roots resolve against the *workspace*, not the process CWD — ``discover_skills``
takes an optional ``workspace``; when the caller does not pass one it falls back to
``Path.cwd()``, which is the harness's default workspace anyway.

The frontmatter parser uses PyYAML when it happens to be installed and otherwise falls back
to a built-in mini parser covering what SKILL.md actually uses: ``key: value``, quoted
strings, inline and block lists, and ``>``/``|`` block scalars (a folded multi-line
``description`` is the single most common thing in real skills). PyYAML stays an optional
dependency — a skill must never need one.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent86.config import Config
from agent86.skills.models import Skill

logger = logging.getLogger(__name__)

#: Keys whose value is a list of tool names, however the author spelled the separator.
_TOOL_KEYS = ("allowed-tools", "allowed_tools")


# --------------------------------------------------------------------------- #
# Frontmatter
# --------------------------------------------------------------------------- #


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split ``text`` into (raw frontmatter, body).

    The closing delimiter must be a ``---`` **on its own line**; splitting on the first three
    hyphens anywhere (the pre-v0.9 behaviour) truncated any skill whose body contained a
    horizontal rule or a YAML document marker.
    """
    stripped = text.lstrip("﻿")
    lines = stripped.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", stripped
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :]).lstrip("\n")
    return "", stripped  # unterminated frontmatter: treat the whole file as body


def parse_skill_md(text: str) -> tuple[dict[str, Any], str]:
    """Split a SKILL.md into (frontmatter mapping, body)."""
    raw, body = split_frontmatter(text)
    if not raw.strip():
        return {}, body
    meta = _yaml_frontmatter(raw)
    if meta is None:
        meta = _mini_frontmatter(raw)
    return {str(k).strip().lower(): v for k, v in meta.items()}, body


def _yaml_frontmatter(raw: str) -> dict[str, Any] | None:
    """Parse with PyYAML if it is installed, else None. Lazy: yaml is never a hard dep."""
    try:
        # Optional dependency, imported only when present — and never at module import time.
        import yaml  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError:
        return None
    try:
        loaded = yaml.safe_load(raw)
    except Exception:  # malformed YAML: the mini parser may still salvage the simple keys
        return None
    return loaded if isinstance(loaded, dict) else None


def _mini_frontmatter(raw: str) -> dict[str, Any]:
    """The no-dependency fallback: key/value, block scalars, block and inline lists."""
    meta: dict[str, Any] = {}
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1] in (" ", "\t") or ":" not in line:
            continue  # a continuation line the block handlers below already consumed
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if value[:1] in ("|", ">") and value.rstrip("-+0123456789") in ("|", ">"):
            block, i = _block_scalar(lines, i, folded=value.startswith(">"))
            meta[key] = block
        elif not value:
            items, i = _block_list(lines, i)
            meta[key] = items if items else ""
        else:
            meta[key] = _scalar(value)
    return meta


def _block_scalar(lines: list[str], start: int, *, folded: bool) -> tuple[str, int]:
    """Collect an indented ``|``/``>`` block starting at ``start``; return (text, next index)."""
    collected: list[str] = []
    indent: int | None = None
    i = start
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            collected.append("")
            i += 1
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent == 0 or (indent is not None and line_indent < indent):
            break
        if indent is None:
            indent = line_indent
        collected.append(line[indent:])
        i += 1
    while collected and not collected[-1]:
        collected.pop()
    if not folded:
        return "\n".join(collected), i
    # Folded: lines of a paragraph join with a space, blank lines separate paragraphs.
    paragraphs: list[list[str]] = [[]]
    for entry in collected:
        if entry:
            paragraphs[-1].append(entry.strip())
        elif paragraphs[-1]:
            paragraphs.append([])
    return "\n".join(" ".join(p) for p in paragraphs if p), i


def _block_list(lines: list[str], start: int) -> tuple[list[str], int]:
    """Collect an indented ``- item`` list starting at ``start``."""
    items: list[str] = []
    i = start
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if not stripped.startswith("- ") and stripped != "-":
            break
        items.append(_scalar(stripped[1:].strip()))
        i += 1
    return items, i


def _scalar(value: str) -> Any:
    """Unquote a scalar; turn an inline ``[a, b]`` list into a real list."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        return [_scalar(part) for part in value[1:-1].split(",") if part.strip()]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


# --------------------------------------------------------------------------- #
# Field coercion
# --------------------------------------------------------------------------- #


def parse_allowed_tools(value: Any) -> list[str]:
    """Normalise ``allowed-tools`` into a list of tool names.

    The convention is **space-delimited** (``allowed-tools: read_file write_file``), but a
    comma-separated string, a bracketed inline list and a YAML block list all mean the same
    thing to a human writing the file, so all four are accepted.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            parts.extend(parse_allowed_tools(item))
        return parts
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [token.strip().strip("'\"") for token in text.replace(",", " ").split() if token.strip()]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value)
    return str(value).strip()


def load_skill(skill_md: Path) -> Skill | None:
    """Build a ``Skill`` from one SKILL.md, or None when it cannot be read."""
    try:
        meta, _ = parse_skill_md(skill_md.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        logger.debug("skipping unreadable skill file %s", skill_md, exc_info=True)
        return None
    name = _as_text(meta.get("name")) or skill_md.parent.name
    allowed: list[str] = []
    for key in _TOOL_KEYS:
        if key in meta:
            allowed = parse_allowed_tools(meta[key])
            break
    metadata = meta.get("metadata")
    return Skill(
        name=name,
        description=_as_text(meta.get("description")),
        path=skill_md,
        allowed_tools=allowed,
        license=_as_text(meta.get("license")) or None,
        metadata=metadata if isinstance(metadata, dict) else {},
    )


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def default_skill_paths(config: Config, workspace: Path | None = None) -> list[Path]:
    """Every directory searched for skills, **highest precedence first**."""
    root = Path(workspace) if workspace is not None else Path.cwd()
    paths = [
        root / ".agent86" / "skills",
        root / ".claude" / "skills",
        Path.home() / ".agent86" / "skills",
        Path.home() / ".claude" / "skills",
    ]
    paths += [Path(p).expanduser() for p in config.skills.paths]
    return paths


def skill_roots(config: Config, workspace: Path | None = None) -> list[Path]:
    """The subset of ``default_skill_paths`` that exists — what the sandbox may read.

    A skill's instructions routinely point at files bundled beside SKILL.md (a reference
    table, a script, a template). Those live outside the workspace for user-level skills, so
    the sandbox policy grants read access to these roots; without that, every user skill's
    "see reference.md" is a jail error.
    """
    if not config.skills.enabled:
        return []
    roots: list[Path] = []
    for path in default_skill_paths(config, workspace):
        try:
            if path.is_dir():
                roots.append(path.resolve())
        except OSError:  # unreadable/nonexistent drive — not a skill root, not a crash
            continue
    return roots


def discover_skills(config: Config, workspace: Path | None = None) -> dict[str, Skill]:
    """Find all skills across the search paths, keyed by name.

    First root wins on a name conflict, so project skills override user skills; later entries
    never override earlier ones. ``workspace`` locates the project roots (default: CWD).
    """
    if not config.skills.enabled:
        return {}
    found: dict[str, Skill] = {}
    for root in default_skill_paths(config, workspace):
        try:
            if not root.is_dir():
                continue
            entries = sorted(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            skill_md = entry / "SKILL.md"
            if entry.is_dir() and skill_md.is_file():
                skill = load_skill(skill_md)
                if skill and skill.name not in found:
                    found[skill.name] = skill
    return found


__all__ = [
    "discover_skills",
    "parse_skill_md",
    "split_frontmatter",
    "parse_allowed_tools",
    "load_skill",
    "default_skill_paths",
    "skill_roots",
]
