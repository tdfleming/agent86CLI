"""Sandbox policy (Tier 4).

The deterministic contract every side-effecting tool runs under: a working-directory
jail for file access, a curated environment (so secrets like API keys never leak into tool
subprocesses), a network toggle, and output/time limits. This is the *restricted
subprocess* tier — pragmatic isolation on Windows; Docker (Phase 9) adds true containment.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Environment variables safe to forward into tool subprocesses. Anything not listed
# (notably ANTHROPIC_API_KEY / OPENAI_API_KEY and other secrets) is scrubbed.
_ENV_ALLOWLIST_COMMON = (
    "PATH",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
)
_ENV_ALLOWLIST_WINDOWS = (
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
)
# Without these, a subprocess on macOS/Linux has no home, no temp dir, no locale and no CA
# bundle — which breaks git (config + credential lookup), pip, and npm outright.
_ENV_ALLOWLIST_POSIX = (
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TMPDIR",
    "TERM",
    "TZ",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
)
#: Whole families that are safe and meaningless one-by-one (locale categories, XDG dirs).
_ENV_ALLOWLIST_PREFIXES = ("LC_", "XDG_")

#: Substrings that mark a variable as a credential. These are refused even when the user
#: names them in ``sandbox.env_passthrough`` — an allowlist entry must not become a way to
#: hand the model's subprocesses the key that pays for the model.
_SECRET_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "API_KEY")
_SECRET_SUFFIXES = ("_KEY",)


def env_allowlist() -> tuple[str, ...]:
    """The exact-name allowlist for this platform."""
    platform_names = _ENV_ALLOWLIST_WINDOWS if os.name == "nt" else _ENV_ALLOWLIST_POSIX
    return _ENV_ALLOWLIST_COMMON + platform_names


def is_secret_name(name: str) -> bool:
    """True if ``name`` looks like it holds a credential."""
    upper = name.upper()
    return any(m in upper for m in _SECRET_MARKERS) or upper.endswith(_SECRET_SUFFIXES)


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
    #: Extra environment variable names the user opted into ([sandbox] env_passthrough).
    #: Credential-looking names are refused here no matter what the config says.
    env_passthrough: list[str] = field(default_factory=list)

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
        """The environment a tool subprocess gets: allowlist + opt-in passthrough, no secrets."""
        allowed = env_allowlist()
        env = {k: v for k, v in os.environ.items() if k in allowed}
        env.update(
            {
                k: v
                for k, v in os.environ.items()
                if k.startswith(_ENV_ALLOWLIST_PREFIXES) and not is_secret_name(k)
            }
        )
        for name in self.env_passthrough:
            if is_secret_name(name):
                logger.warning(
                    "sandbox.env_passthrough entry %r looks like a credential; refusing to "
                    "forward it into tool subprocesses.",
                    name,
                )
                continue
            if name in os.environ:
                env[name] = os.environ[name]
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    # ---- output truncation ------------------------------------------- #

    def truncate(self, text: str) -> str:
        limit = self.max_output_bytes
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n... [truncated {len(text) - limit} bytes]"


def default_policy(
    config, workspace: Path | None = None, extra_allow_paths: Iterable[Path] | None = None
) -> SandboxPolicy:
    """Build the default policy from config and the current workspace.

    ``timeout_s`` is a *per-tool* budget and comes from ``limits.tool_timeout_s``; it used to
    be derived from the whole-run wall clock (``max_wall_clock_s`` when under 120s, else 60),
    which silently shortened tool timeouts for anyone who lowered the run budget and was
    impossible to configure directly.

    Skill roots join ``allow_paths`` automatically. A skill's instructions routinely say "see
    ``reference.md``", and for a user-level skill that file sits under ``~/.claude/skills``,
    outside the workspace — so without this every such reference is a jail error. The jail has
    no read/write split, so this does also make those directories *writable*; a write there is
    still a side-effecting tool call and still passes the approval gate, and the alternative —
    skills whose own bundle is unreachable — is worse. ``extra_allow_paths`` adds roots that
    discovery cannot see.
    """
    ws = (workspace or Path.cwd()).resolve()
    allow: list[Path] = []
    try:
        from agent86.skills.loader import skill_roots

        allow.extend(skill_roots(config, ws))
    except Exception:  # discovery must never be the reason a policy cannot be built
        logger.debug("skill root discovery failed; continuing without them", exc_info=True)
    allow.extend(Path(p).resolve() for p in (extra_allow_paths or ()))
    # Roots already inside the workspace add nothing but noise to every jail check.
    deduped: list[Path] = []
    for path in allow:
        if path != ws and ws not in path.parents and path not in deduped:
            deduped.append(path)
    return SandboxPolicy(
        workspace=ws,
        allow_paths=deduped,
        network=True,
        timeout_s=int(config.limits.tool_timeout_s),
        env_passthrough=list(getattr(config.sandbox, "env_passthrough", []) or []),
    )


__all__ = [
    "SandboxPolicy",
    "PolicyError",
    "default_policy",
    "env_allowlist",
    "is_secret_name",
]
