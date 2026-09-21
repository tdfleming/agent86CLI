"""Skill data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    """A self-contained skill: metadata always loaded, instructions loaded on demand.

    ``allowed_tools`` is the Agent Skills convention's ``allowed-tools``: when non-empty it
    is a *restriction* — while the skill is active, the registry refuses every tool outside
    the list (see ``ToolRegistry.dispatch``). Empty means "no restriction", not "no tools".
    """

    name: str
    description: str
    path: Path  # the SKILL.md file
    allowed_tools: list[str] = field(default_factory=list)
    license: str | None = None
    #: Free-form ``metadata:`` mapping from the frontmatter; carried, never interpreted.
    metadata: dict[str, Any] = field(default_factory=dict)
    _instructions: str | None = None

    @property
    def directory(self) -> Path:
        return self.path.parent

    def instructions(self) -> str:
        """Load the full instruction body (progressive disclosure — only when invoked)."""
        if self._instructions is None:
            from agent86.skills.loader import parse_skill_md

            _, body = parse_skill_md(self.path.read_text(encoding="utf-8"))
            self._instructions = body
        return self._instructions

    def resources(self) -> list[str]:
        """Names of sibling files/dirs bundled with the skill (excluding SKILL.md)."""
        try:
            return sorted(p.name for p in self.directory.iterdir() if p.name.lower() != "skill.md")
        except OSError:
            return []


__all__ = ["Skill"]
