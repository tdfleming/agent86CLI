"""v0.2 — status-line logic and approval-mode cycling (pure, headless)."""

from __future__ import annotations

from types import SimpleNamespace

from agent86.config import load_config
from agent86.guardrails.policy import cycle_mode, parse_mode
from agent86.types import ApprovalMode
from agent86.ui.status import (
    UNPRICED_LABEL,
    StatusState,
    context_percent,
    context_window_for,
    format_cost,
    format_last_turn,
    format_status_line,
    format_turn_summary,
    human_tokens,
)

# ---- context window --------------------------------------------------- #


def test_context_window_known_models():
    cfg = load_config()
    assert context_window_for("anthropic:claude-opus-4-8", cfg) == 200_000
    assert context_window_for("openai:gpt-4o", cfg) == 128_000
    assert context_window_for("ollama:qwen2.5:3b", cfg) == 32_768


def test_context_window_unknown_falls_back():
    assert context_window_for("mystery:model-x", load_config()) == 8_192


def test_context_window_config_override():
    cfg = load_config()
    cfg.model.context_window = {"ollama:qwen2.5:3b": 16_384}
    assert context_window_for("ollama:qwen2.5:3b", cfg) == 16_384


def test_context_percent_clamps():
    assert context_percent(0, 8000) == 0
    assert context_percent(4000, 8000) == 50
    assert context_percent(9000, 8000) == 100  # over -> clamped
    assert context_percent(100, 0) == 0  # guard divide-by-zero


def test_human_tokens():
    assert human_tokens(512) == "512"
    assert human_tokens(1234) == "1.2k"
    assert human_tokens(32768) == "33k"


# ---- status line formatting ------------------------------------------- #


def _state(**over) -> StatusState:
    base = dict(
        model="qwen2.5:3b", used_tokens=1100, window=8192, output_tokens=320,
        cost_usd=0.0, sandbox="subprocess", approval="ask",
        model_ref="ollama:qwen2.5:3b",
    )
    base.update(over)
    return StatusState(**base)


def test_status_line_idle():
    line = format_status_line(_state())
    assert "qwen2.5:3b" in line
    assert "ctx 13%" in line  # 1100/8192
    assert "1.1k/8.2k" in line
    assert "320 out" in line
    assert "$0.0000" in line  # local model: free is the *real* price, not an unknown one
    assert "sbx subprocess" in line
    assert "mode: ask" in line
    assert "[Shift+Tab]" in line


# ---- cost display ------------------------------------------------------ #


def test_format_cost_priced_model():
    assert format_cost(0.1234, "anthropic:claude-opus-4-8") == "$0.1234"


def test_format_cost_local_model_is_free_not_unknown():
    assert format_cost(0.0, "ollama:qwen2.5:3b") == "$0.0000"


def test_format_cost_unknown_model_says_na():
    assert format_cost(0.0, "groq:llama-3.3-70b-versatile") == UNPRICED_LABEL


def test_status_line_unpriced_model_shows_na_not_zero():
    line = format_status_line(_state(model="llama-3.3-70b-versatile", model_ref="groq:llama-3.3"))
    assert UNPRICED_LABEL in line
    assert "$0.0000" not in line


def test_status_state_price_ref_falls_back_to_model():
    assert _state(model_ref="").price_ref == "qwen2.5:3b"
    assert _state().price_ref == "ollama:qwen2.5:3b"


def test_status_line_working_shows_phase():
    line = format_status_line(_state(working=True, phase="running tool: python_exec"))
    assert "running tool: python_exec…" in line
    assert "ctx" not in line  # stats hidden while working
    assert "mode: ask" in line  # mode still shown


# ---- per-turn summary line --------------------------------------------- #


def _summary(**over):
    """A ``TurnSummary``-shaped stub (the real model lives in orchestration/state.py)."""
    base = dict(
        input_tokens=4100,
        output_tokens=612,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        cost_usd=0.0123,
        steps=3,
        tool_calls=2,
        duration_s=8.23,
        compactions=0,
        continuations=0,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_turn_summary_line_shape():
    line = format_turn_summary(_summary(), "anthropic:claude-opus-4-8")
    assert line == "— 3 steps · 2 tools · 4.1k in / 612 out · $0.0123 · 8.2s"


def test_turn_summary_includes_cached_tokens_when_present():
    line = format_turn_summary(
        _summary(cache_read_tokens=1900, cache_creation_tokens=0), "anthropic:claude-opus-4-8"
    )
    assert "4.1k in / 612 out (1.9k cached)" in line
    # reads and writes are both cache traffic and are summed into the one figure
    both = format_turn_summary(
        _summary(cache_read_tokens=1000, cache_creation_tokens=900), "anthropic:claude-opus-4-8"
    )
    assert "(1.9k cached)" in both


def test_turn_summary_omits_cached_when_zero():
    assert "cached" not in format_turn_summary(_summary(), "anthropic:claude-opus-4-8")


def test_turn_summary_singular_units():
    line = format_turn_summary(_summary(steps=1, tool_calls=1), "anthropic:claude-opus-4-8")
    assert "1 step ·" in line and "1 tool ·" in line


def test_turn_summary_unpriced_model_says_na():
    line = format_turn_summary(_summary(), "groq:llama-3.3-70b-versatile")
    assert UNPRICED_LABEL in line
    assert "$0.0123" not in line


def test_turn_summary_reports_compaction_and_continuation():
    line = format_turn_summary(
        _summary(compactions=2, continuations=1), "anthropic:claude-opus-4-8"
    )
    assert "2 compactions" in line and "1 continuation" in line


def test_turn_summary_tolerates_a_summary_missing_fields():
    """Every field is read with a getattr fallback — a partial summary must still render."""
    line = format_turn_summary(SimpleNamespace(steps=1), "ollama:qwen2.5:3b")
    assert line == "— 1 step · 0 tools · 0 in / 0 out · $0.0000 · 0.0s"


def test_format_last_turn_absent_returns_none():
    assert format_last_turn(SimpleNamespace(), "anthropic:claude-opus-4-8") is None
    assert format_last_turn(SimpleNamespace(last_turn=None), "anthropic:claude-opus-4-8") is None


def test_format_last_turn_uses_state_summary():
    state = SimpleNamespace(last_turn=_summary())
    assert format_last_turn(state, "anthropic:claude-opus-4-8").startswith("— 3 steps")


# ---- approval mode cycling -------------------------------------------- #


def test_cycle_mode():
    assert cycle_mode(ApprovalMode.ASK) is ApprovalMode.AUTO
    assert cycle_mode(ApprovalMode.AUTO) is ApprovalMode.DENY
    assert cycle_mode(ApprovalMode.DENY) is ApprovalMode.ASK


def test_parse_mode():
    assert parse_mode("auto") is ApprovalMode.AUTO
    assert parse_mode("  ASK ") is ApprovalMode.ASK
    assert parse_mode("deny") is ApprovalMode.DENY
    assert parse_mode("nonsense") is None
