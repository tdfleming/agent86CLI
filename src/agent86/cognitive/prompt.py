"""Prompt compilation (Tier 3).

Assembles the system prompt from the harness identity, environment facts, and (in later
phases) the loaded skills and available-tool descriptions. Phase 2 ships the base
identity; tool/skill sections are appended here as those tiers come online.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent86 import __version__
from agent86.config import Config
from agent86.types import Message, Role

if TYPE_CHECKING:
    from agent86.skills.models import Skill

_BASE_IDENTITY = """\
You are agent86, an autonomous agent running inside a deterministic agentic harness.

You operate in a Reason -> Act -> Observe loop. When tools are available, prefer taking a
concrete action over speculating; the harness executes your tool calls, validates them,
and returns real results for you to reason over. When no tool is needed, answer directly
and concisely.

Principles:
- Be truthful about what you did and did not do. Never claim a tool ran if it did not.
- Keep responses focused; avoid filler.
- If a request is ambiguous and the answer would change materially, ask a brief question.
- Use memory sparingly. Only call `remember` for durable, user-specific facts (a stated
  preference, identity detail, or lasting project constraint) — typically when the user
  asks you to remember something. Never remember answers you just computed, transient state,
  or general knowledge. When in doubt, don't remember.
"""


def build_system_prompt(
    config: Config, skills: dict[str, Skill] | None = None
) -> Message:
    """Compile the system prompt into a single SYSTEM message."""
    parts = [_BASE_IDENTITY.strip()]
    parts.append(
        f"\nEnvironment: agent86 v{__version__}. "
        f"Default model: {config.model.default}. Sandbox: {config.sandbox.mode}."
    )
    if skills:
        # Progressive disclosure: advertise only name + description here. The full
        # instructions load when the model calls use_skill(name).
        lines = ["\nAvailable skills (call use_skill with the name to load full instructions):"]
        for skill in skills.values():
            lines.append(f"- {skill.name}: {skill.description}")
        parts.append("\n".join(lines))
    return Message(role=Role.SYSTEM, content="\n".join(parts))


__all__ = ["build_system_prompt"]
