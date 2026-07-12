"""Status-line logic (v0.2).

Pure, unit-testable helpers behind the persistent bottom status line: per-model context-window
lookup, context-fill percentage, and formatting. The prompt_toolkit wiring that renders this
lives in ``ui.repl`` and stays thin so this logic can be tested headlessly.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent86.config import Config

# Default when a model isn't recognized and no override is set.
_DEFAULT_WINDOW = 8_192

# Substring -> context window (tokens). Matched against the full "provider:model" ref,
# lowercased. First match wins, so order more specific keys before generic ones.
_WINDOWS: list[tuple[str, int]] = [
    ("claude", 200_000),
    ("gpt-4o", 128_000),
    ("gpt-4.1", 1_000_000),
    ("gpt-4", 128_000),
    ("o1", 200_000),
    ("o3", 200_000),
    ("qwen2.5", 32_768),
    ("qwen3", 32_768),
    ("llama3.1", 131_072),
    ("llama3.2", 131_072),
    ("llama3", 8_192),
    ("mistral", 32_768),
    ("mixtral", 32_768),
    ("gemma", 8_192),
    ("phi", 16_384),
]


def context_window_for(model_ref: str, config: Config) -> int:
    """Resolve the context window (tokens) for a ``provider:model`` ref."""
    override = config.model.context_window.get(model_ref)
    if override:
        return int(override)
    ref = model_ref.lower()
    for needle, window in _WINDOWS:
        if needle in ref:
            return window
    return _DEFAULT_WINDOW


def context_percent(used: int, window: int) -> int:
    """Percent of the context window filled, clamped to 0..100."""
    if window <= 0:
        return 0
    return max(0, min(100, round(100 * used / window)))


def human_tokens(n: int) -> str:
    """Compact token count: 512 -> '512', 1234 -> '1.2k', 32768 -> '33k'."""
    if n < 1000:
        return str(n)
    if n < 10_000:
        return f"{n / 1000:.1f}k"
    return f"{round(n / 1000)}k"


@dataclass
class StatusState:
    model: str
    used_tokens: int
    window: int
    output_tokens: int
    cost_usd: float
    sandbox: str
    approval: str
    working: bool = False  # a turn is in flight
    phase: str = ""  # e.g. "thinking", "running tool: python_exec"
    hotkey_hint: str = "Shift+Tab"


def format_status_line(state: StatusState) -> str:
    """Render the persistent status line as plain text."""
    if state.working:
        label = state.phase or "working"
        left = f"{state.model} · {label}…"
    else:
        pct = context_percent(state.used_tokens, state.window)
        left = (
            f"{state.model} · ctx {pct}% "
            f"({human_tokens(state.used_tokens)}/{human_tokens(state.window)}) · "
            f"{human_tokens(state.output_tokens)} out · ${state.cost_usd:.4f}"
        )
    return f"{left} · sbx {state.sandbox} · mode: {state.approval}  [{state.hotkey_hint}]"


__all__ = [
    "StatusState",
    "context_window_for",
    "context_percent",
    "human_tokens",
    "format_status_line",
]
