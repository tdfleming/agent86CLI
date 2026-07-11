"""Sandbox policy (Tier 4).

The deterministic contract every side-effecting tool runs under: a working-directory
jail for file access, a curated environment (so secrets like API keys never leak into tool
subprocesses), a network toggle, and output/time limits. This is the *restricted
subprocess* tier — pragmatic isolation on Windows; Docker (Phase 9) adds true containment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Environment variables safe to forward into tool subprocesses. Anything not listed
# (notably ANTHROPIC_API_KEY / OPENAI_API_KEY and other secrets) is scrubbed.
_ENV_ALLOWLIST = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "HOMEDRIVE",
    "HOMEPATH",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "OS",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
)


class PolicyError(RuntimeError):
    """A tool attempted an action the sandbox policy forbids."""


@dataclass
class SandboxPolicy:
    """Constraints applied to every sandboxed tool execution."""

    workspace: Path
    allow_paths: list[Path] = field(default_factory=list)
    network: bool = True
    timeout_s: int = 30
    max_output_bytes: int = 100_000

    # ---- path jail ---------------------------------------------------- #

    def _roots(self) -> list[Path]:
        return [self.workspace.resolve(), *(p.resolve() for p in self.allow_paths)]

    def resolve_within(self, path_str: str) -> Path:
        """Resolve ``path_str`` (relative to the workspace) and enforce the jail."""
        candidate = Path(path_str)
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        candidate = candidate.resolve()
        for root in self._roots():
            if candidate == root or root in candidate.parents:
                return candidate
        raise PolicyError(
            f"Path '{path_str}' resolves outside the workspace jail ({self.workspace})."
        )

    def require_network(self) -> None:
        if not self.network:
            raise PolicyError("Network access is disabled by the sandbox policy.")

    # ---- environment scrubbing --------------------------------------- #

    def scrubbed_env(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    # ---- output truncation ------------------------------------------- #

    def truncate(self, text: str) -> str:
        limit = self.max_output_bytes
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n... [truncated {len(text) - limit} bytes]"


def default_policy(config, workspace: Path | None = None) -> SandboxPolicy:
    """Build the default policy from config and the current workspace."""
    ws = (workspace or Path.cwd()).resolve()
    return SandboxPolicy(
        workspace=ws,
        network=True,
        timeout_s=config.limits.max_wall_clock_s if config.limits.max_wall_clock_s < 120 else 60,
    )


__all__ = ["SandboxPolicy", "PolicyError", "default_policy"]
