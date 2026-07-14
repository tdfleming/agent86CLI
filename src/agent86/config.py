"""Layered configuration.

Resolution order (later overrides earlier):

    built-in defaults
      -> ~/.agent86/config.toml        (user)
      -> ./.agent86/config.toml        (project)
      -> environment variables         (AGENT86_*)
      -> explicit overrides            (CLI flags)

Secrets (API keys) are never stored here — config only names the *env var* that
holds each provider's key (``api_key_env``); the key itself is read at provider
construction time.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent86 import __version__
from agent86.types import ApprovalMode

USER_CONFIG_DIR = Path.home() / ".agent86"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.toml"
PROJECT_CONFIG_PATH = Path(".agent86") / "config.toml"


# --------------------------------------------------------------------------- #
# Config schema
# --------------------------------------------------------------------------- #


class ModelRoute(BaseModel):
    cheap: str = "ollama:llama3.1"
    frontier: str = "anthropic:claude-opus-4-8"


class ModelConfig(BaseModel):
    default: str = "anthropic:claude-opus-4-8"
    router: str = "off"  # "off" | "triage"
    route: ModelRoute = Field(default_factory=ModelRoute)
    # Optional per-model context-window overrides for the status-line gauge,
    # keyed by "provider:model" (e.g. "ollama:qwen2.5:3b" = 32768).
    context_window: dict[str, int] = Field(default_factory=dict)


class ProviderConfig(BaseModel):
    api_key_env: str | None = None
    base_url: str | None = None
    # Ollama only: context window (num_ctx) to request. Ollama otherwise defaults to a small
    # window that a tool observation (e.g. web_fetch) can fill, leaving no room to generate —
    # so responses get cut off mid-sentence. None uses Ollama's default.
    num_ctx: int | None = None


def _default_user_agent() -> str:
    # Sites like Wikipedia enforce a User-Agent policy and 403 generic or browser-spoofed
    # strings; a descriptive UA with a contact URL is accepted. Keep the URL real.
    return f"agent86/{__version__} (+https://github.com/tdfleming/agent86CLI)"


class ToolsConfig(BaseModel):
    web_user_agent: str = Field(default_factory=_default_user_agent)
    # Cap web_fetch's extracted text so a huge page (e.g. a long Wikipedia article) doesn't
    # bury the lead/relevant content in more tokens than a model can usefully attend to.
    # 0 = no web-specific cap (still bounded by the sandbox output limit). ~8k chars ≈ 2k tokens.
    web_max_chars: int = 8000


class SandboxConfig(BaseModel):
    mode: str = "subprocess"  # "subprocess" | "docker"
    docker_image: str = "python:3.12-slim"
    docker_memory: str = "512m"
    docker_cpus: str = "1"
    docker_network: bool = False  # containers run with --network none by default


class GuardrailsConfig(BaseModel):
    approval: ApprovalMode = ApprovalMode.ASK
    ingress: str = "warn"  # off | warn | block   (scan user input for injection/PII)
    egress: str = "warn"  # off | warn | redact   (scan model output for secrets/PII)
    scan_observations: bool = True  # scan tool outputs for injected instructions


class MemoryConfig(BaseModel):
    enabled: bool = True
    path: str = "~/.agent86/memory.db"
    embeddings: str = "sentence-transformers:all-MiniLM-L6-v2"
    # Skip the Hugging Face hub update-check when the embedding model is already cached
    # (silences the "unauthenticated requests to the HF Hub" warning and speeds startup).
    # Set false to always let huggingface_hub check for model updates online.
    hf_offline: bool = True
    # Retention caps for the append-only flight-recorder log, applied automatically when the
    # harness starts. 0 disables a cap. Curated semantic facts are never auto-pruned.
    retention_max_episodes: int = 1000
    retention_max_sessions: int = 500
    retention_max_age_days: float = 0.0

    def resolved_path(self) -> Path:
        return Path(os.path.expanduser(self.path))


class LimitsConfig(BaseModel):
    max_steps: int = 40
    max_cost_usd: float = 5.0
    max_wall_clock_s: int = 900
    max_consecutive_errors: int = 3
    max_context_tokens: int = 8000


class UIConfig(BaseModel):
    status_line: bool = True  # show the persistent bottom status line (rich REPL)
    spinner: bool = True  # animate a spinner while the agent is working
    mode_cycle_key: str = "s-tab"  # prompt_toolkit key that cycles the approval mode


class SkillsConfig(BaseModel):
    enabled: bool = True
    # Extra directories to search, in addition to ~/.agent86/skills and ./.agent86/skills.
    paths: list[str] = Field(default_factory=list)


class MCPConfig(BaseModel):
    enabled: bool = True


class AgentsConfig(BaseModel):
    enabled: bool = True  # expose the `delegate` tool for sub-agent spawning
    max_depth: int = 2  # how deep delegation may nest (root=0)


class ObservabilityConfig(BaseModel):
    trace: bool = True  # write the JSONL flight recorder
    path: str = "~/.agent86/traces"
    otel: bool = False  # emit OpenTelemetry spans (requires the 'otel' extra)

    def resolved_path(self) -> Path:
        return Path(os.path.expanduser(self.path))


class MCPServerConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


def _default_providers() -> dict[str, ProviderConfig]:
    return {
        "anthropic": ProviderConfig(api_key_env="ANTHROPIC_API_KEY"),
        "openai": ProviderConfig(
            api_key_env="OPENAI_API_KEY", base_url="https://api.openai.com/v1"
        ),
        # OpenAI-compatible cloud gateways — ready to use once their API key env var is set,
        # e.g. `agent86 -m "openrouter:anthropic/claude-3.7-sonnet"`.
        "openrouter": ProviderConfig(
            api_key_env="OPENROUTER_API_KEY", base_url="https://openrouter.ai/api/v1"
        ),
        "groq": ProviderConfig(
            api_key_env="GROQ_API_KEY", base_url="https://api.groq.com/openai/v1"
        ),
        "ollama": ProviderConfig(base_url="http://localhost:11434", num_ctx=8192),
        "llamacpp": ProviderConfig(base_url="http://localhost:8080"),
    }


class Config(BaseModel):
    """The fully-resolved configuration handed to the harness."""

    model: ModelConfig = Field(default_factory=ModelConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=_default_providers)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)

    # Provenance — which files actually contributed (for `agent86 config path`).
    sources: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Loading & merging
# --------------------------------------------------------------------------- #


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` into ``base`` (returns a new dict)."""
    out = dict(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Malformed config at {path}: {exc}") from exc


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a few TOML spellings onto the pydantic field names."""
    data = dict(raw)
    # `[mcp.servers.NAME]` -> mcp_servers; `[mcp] enabled=...` -> mcp config.
    mcp = data.pop("mcp", None)
    if isinstance(mcp, dict):
        servers = mcp.pop("servers", None)
        if servers is not None:
            data["mcp_servers"] = servers
        if mcp:  # remaining keys (e.g. enabled) form the mcp config
            data["mcp"] = mcp
    return data


def _env_overrides() -> dict[str, Any]:
    """A small, explicit set of AGENT86_* env overrides."""
    over: dict[str, Any] = {}
    if val := os.getenv("AGENT86_MODEL"):
        over.setdefault("model", {})["default"] = val
    if val := os.getenv("AGENT86_SANDBOX"):
        over.setdefault("sandbox", {})["mode"] = val
    if val := os.getenv("AGENT86_APPROVAL"):
        over.setdefault("guardrails", {})["approval"] = val
    return over


def load_config(overrides: dict[str, Any] | None = None) -> Config:
    """Resolve configuration from all layers into a validated :class:`Config`."""
    # Seed with the full defaults so partial overrides deep-merge (e.g. setting one
    # provider's base_url must not wipe that provider's api_key_env or the other providers).
    merged: dict[str, Any] = Config().model_dump(mode="json")
    merged.pop("sources", None)
    sources: list[str] = []

    for path in (USER_CONFIG_PATH, PROJECT_CONFIG_PATH):
        raw = _read_toml(path)
        if raw:
            merged = _deep_merge(merged, _normalize(raw))
            sources.append(str(path))

    merged = _deep_merge(merged, _env_overrides())
    if overrides:
        merged = _deep_merge(merged, overrides)

    config = Config.model_validate(merged)
    config.sources = sources
    return config


def config_paths() -> dict[str, str]:
    """Report where config is (or would be) read from, and whether each exists."""
    return {
        "user": f"{USER_CONFIG_PATH} ({'exists' if USER_CONFIG_PATH.exists() else 'not found'})",
        "project": (
            f"{PROJECT_CONFIG_PATH.resolve()} "
            f"({'exists' if PROJECT_CONFIG_PATH.exists() else 'not found'})"
        ),
    }


__all__ = [
    "Config",
    "ModelConfig",
    "ModelRoute",
    "ProviderConfig",
    "SandboxConfig",
    "GuardrailsConfig",
    "MemoryConfig",
    "LimitsConfig",
    "ObservabilityConfig",
    "UIConfig",
    "SkillsConfig",
    "MCPConfig",
    "AgentsConfig",
    "MCPServerConfig",
    "load_config",
    "config_paths",
    "USER_CONFIG_PATH",
    "PROJECT_CONFIG_PATH",
]
