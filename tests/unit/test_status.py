"""v0.2 — status-line logic and approval-mode cycling (pure, headless)."""

from __future__ import annotations

from agent86.config import load_config
from agent86.guardrails.policy import cycle_mode, parse_mode
from agent86.types import ApprovalMode
from agent86.ui.status import (
    UNPRICED_LABEL,
    StatusState,
    context_percent,
    context_window_for,
    format_cost,
    format_status_line,
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
