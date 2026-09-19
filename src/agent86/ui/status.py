"""Status-line logic.

Pure, unit-testable helpers behind the persistent status line: per-model context-window
lookup, context-fill percentage, and formatting. The widget that renders this lives in
``agent86.tui.widgets.status_footer`` and stays thin so this logic can be tested headlessly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent86.cognitive.pricing import is_priced
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
    """Resolve the context window (tokens) for a ``provider:model`` ref.

    Delegates to ``cognitive.capabilities`` — the same resolution the harness budgets and
    compacts against — so the gauge and the budget can never disagree (it knows, for
    instance, that an Ollama window is whatever ``num_ctx`` asks for, not what the model
    name suggests). The table below is the fallback for a tree without that module.
    """
    try:
        from agent86.cognitive.capabilities import context_window_for as _capability_window
    except ImportError:  # pragma: no cover - older tree
        pass
    else:
        return _capability_window(model_ref, config)
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


#: Shown instead of a dollar figure when no price is known for the model. A running total of
#: ``$0.0000`` on an unpriced model is a lie — it reads as "this turn was free" when the truth
#: is "we have no idea what this cost", and it is the same string the cost cap silently sees.
UNPRICED_LABEL = "cost n/a (unpriced model)"


def format_cost(cost_usd: float, model_ref: str) -> str:
    """Render accumulated cost for ``model_ref``, or :data:`UNPRICED_LABEL` if unknown.

    Local models (Ollama, llama.cpp) *are* priced — at zero — so they keep showing ``$0.0000``
    rather than "n/a". ``model_ref`` should be the full ``provider:model`` ref when available;
    a bare model id still resolves for cloud models that are in the price table.
    """
    return f"${cost_usd:.4f}" if is_priced(model_ref) else UNPRICED_LABEL


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _int(obj: Any, field: str) -> int:
    """Read an int field off a summary that may predate this milestone."""
    value = getattr(obj, field, 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return 0


def _float(obj: Any, field: str) -> float:
    value = getattr(obj, field, 0.0)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return 0.0


def format_turn_summary(summary: Any, model_ref: str) -> str:
    """One dim line summarising a finished turn, shared by every surface.

    Reads a ``TurnSummary``-shaped object (``orchestration.state``) entirely through
    ``getattr`` so a surface never crashes on an older state object, or on a summary that
    grows a field later. The cached parenthetical is dropped when nothing was cached — a
    provider with no prompt cache should not pay for a permanent ``(0 cached)``.

    Example: ``— 3 steps · 2 tools · 4.1k in / 612 out (1.9k cached) · $0.0123 · 8.2s``
    """
    cached = _int(summary, "cache_read_tokens") + _int(summary, "cache_creation_tokens")
    tokens = (
        f"{human_tokens(_int(summary, 'input_tokens'))} in / "
        f"{human_tokens(_int(summary, 'output_tokens'))} out"
    )
    if cached:
        tokens += f" ({human_tokens(cached)} cached)"
    parts = [
        _plural(_int(summary, "steps"), "step"),
        _plural(_int(summary, "tool_calls"), "tool"),
        tokens,
        format_cost(_float(summary, "cost_usd"), model_ref),
        f"{_float(summary, 'duration_s'):.1f}s",
    ]
    compactions = _int(summary, "compactions")
    if compactions:
        parts.append(_plural(compactions, "compaction"))
    continuations = _int(summary, "continuations")
    if continuations:
        parts.append(_plural(continuations, "continuation"))
    return "— " + " · ".join(parts)


def format_last_turn(state: Any, model_ref: str) -> str | None:
    """``format_turn_summary`` for ``state.last_turn``, or ``None`` when there isn't one.

    The one place the ``last_turn`` contract is probed, so the TUI, the plain loop and
    ``agent86 run`` all print the same line — and all print nothing when the loop hasn't
    populated it (an older state, a turn that raised before the summary was set).
    """
    summary = getattr(state, "last_turn", None)
    if summary is None:
        return None
    return format_turn_summary(summary, model_ref)


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
    #: Full ``provider:model`` ref, used only for price lookup (``model`` stays the short
    #: label that is displayed). Empty falls back to ``model``, which resolves for cloud
    #: models but cannot tell a *local* model from an unpriced one — set it where you can.
    model_ref: str = ""
    #: Cumulative prompt-cache traffic this session. Both stay 0 on providers with no cache,
    #: and the tokens segment then says nothing about caching at all.
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def price_ref(self) -> str:
        return self.model_ref or self.model

    @property
    def cached_tokens(self) -> int:
        return self.cache_read_tokens + self.cache_creation_tokens


@dataclass(frozen=True)
class StatusSegment:
    """One labelled piece of the status line.

    ``key`` is what a surface sheds by under width pressure (see
    ``agent86.tui.widgets.status_footer.fit_status_line``); ``text`` is what it renders.
    """

    key: str
    text: str


def status_segments(state: StatusState) -> list[StatusSegment]:
    """The status line broken into its labelled parts, in display order.

    The pure half of the footer's width policy: this decides *what* the line says, the
    widget decides how much of it fits. ``format_status_line`` joins them all, which is what
    every non-width-aware surface renders.
    """
    segments: list[StatusSegment] = [StatusSegment("model", state.model)]
    if state.working:
        segments.append(StatusSegment("phase", f"{state.phase or 'working'}…"))
    else:
        pct = context_percent(state.used_tokens, state.window)
        segments.append(
            StatusSegment(
                "ctx",
                f"ctx {pct}% "
                f"({human_tokens(state.used_tokens)}/{human_tokens(state.window)})",
            )
        )
        tokens = f"tok {human_tokens(state.used_tokens)}/{human_tokens(state.output_tokens)}"
        if state.cached_tokens:
            tokens += f" ({human_tokens(state.cached_tokens)} cached)"
        segments.append(StatusSegment("tok", tokens))
        segments.append(
            StatusSegment("cost", format_cost(state.cost_usd, state.price_ref))
        )
    segments.append(StatusSegment("sbx", f"sbx {state.sandbox}"))
    segments.append(StatusSegment("mode", f"mode: {state.approval}"))
    if state.hotkey_hint:
        segments.append(StatusSegment("hint", f"[{state.hotkey_hint}]"))
    return segments


def join_segments(segments: list[StatusSegment]) -> str:
    """Render segments as one line: ``·``-separated, with the key hint set off at the end."""
    body = " · ".join(s.text for s in segments if s.key != "hint")
    hint = next((s.text for s in segments if s.key == "hint"), "")
    return f"{body}  {hint}" if hint else body


def format_status_line(state: StatusState) -> str:
    """Render the full persistent status line as plain text (no width policy)."""
    return join_segments(status_segments(state))


__all__ = [
    "UNPRICED_LABEL",
    "StatusSegment",
    "StatusState",
    "context_window_for",
    "context_percent",
    "human_tokens",
    "format_cost",
    "format_last_turn",
    "format_status_line",
    "format_turn_summary",
    "join_segments",
    "status_segments",
]
