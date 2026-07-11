"""Prompt compilation (Tier 3).

Assembles the system prompt from the harness identity, environment facts, and (in later
phases) the loaded skills and available-tool descriptions. Phase 2 ships the base
identity; tool/skill sections are appended here as those tiers come online.
"""

from __future__ import annotations

from agent86 import __version__
from agent86.config import Config
from agent86.types import Message, Role

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
"""


def build_system_prompt(config: Config) -> Message:
    """Compile the system prompt into a single SYSTEM message."""
    parts = [_BASE_IDENTITY.strip()]
    parts.append(
        f"\nEnvironment: agent86 v{__version__}. "
        f"Default model: {config.model.default}. Sandbox: {config.sandbox.mode}."
    )
    # PHASE 3/6: append tool catalog and loaded-skill summaries here.
    return Message(role=Role.SYSTEM, content="\n".join(parts))


__all__ = ["build_system_prompt"]
