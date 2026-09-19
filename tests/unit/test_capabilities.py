"""Unit tests for the sampling-params capability seam (UAT gap 5, closure plan 03-12)."""

from __future__ import annotations

import pytest

from agent86.cognitive import capabilities


@pytest.fixture(autouse=True)
def _clear_learned():
    """Ensure the session-scoped learned set never leaks between tests."""
    capabilities._LEARNED_NO_SAMPLING.clear()
    yield
    capabilities._LEARNED_NO_SAMPLING.clear()


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-5",
        "claude-opus-5-20260101",
        "claude-opus-5-latest",
        "anthropic:claude-opus-5",
        "Claude-Opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-5",
        "claude-fable-5",
    ],
)
def test_supports_sampling_params_false_for_removed_families(model):
    assert capabilities.supports_sampling_params(model) is False


@pytest.mark.parametrize(
    "model",
    [
        "claude-sonnet-4-5",
        "claude-opus-4-5",
        "gpt-4o",
        "llama3.1:8b",
        "openai:gpt-4o",
    ],
)
def test_supports_sampling_params_true_for_unaffected_models(model):
    assert capabilities.supports_sampling_params(model) is True


def test_apply_sampling_params_omits_temperature_for_removed_model():
    result = capabilities.apply_sampling_params({}, "claude-opus-5", temperature=0.0)
    assert "temperature" not in result
    assert result == {}


def test_apply_sampling_params_sends_zero_temperature_for_legal_model():
    result = capabilities.apply_sampling_params({}, "gpt-4o", temperature=0.0)
    assert result == {"temperature": 0.0}


def test_apply_sampling_params_none_means_no_value():
    result = capabilities.apply_sampling_params({}, "gpt-4o", temperature=None)
    assert result == {}


def test_apply_sampling_params_includes_top_p_and_top_k_when_supported():
    result = capabilities.apply_sampling_params(
        {}, "gpt-4o", temperature=0.5, top_p=0.9, top_k=40
    )
    assert result == {"temperature": 0.5, "top_p": 0.9, "top_k": 40}


def test_apply_sampling_params_mutates_and_returns_same_dict():
    kwargs = {"model": "gpt-4o"}
    result = capabilities.apply_sampling_params(kwargs, "gpt-4o", temperature=0.0)
    assert result is kwargs


def test_mark_sampling_unsupported_learns_for_session():
    assert capabilities.supports_sampling_params("some-new-model") is True
    capabilities.mark_sampling_unsupported("some-new-model")
    assert capabilities.supports_sampling_params("some-new-model") is False


def test_mark_sampling_unsupported_normalizes_model_id():
    capabilities.mark_sampling_unsupported("anthropic:Some-New-Model")
    assert capabilities.supports_sampling_params("some-new-model") is False


@pytest.mark.parametrize(
    "message,expected",
    [
        ("`temperature` is deprecated this model.", True),
        ("model not found", False),
        ("top_p is not supported", True),
        ("top_k parameter removed for this model", True),
        ("Invalid API key", False),
    ],
)
def test_is_sampling_rejection(message, expected):
    assert capabilities.is_sampling_rejection(message) is expected


# ---- context windows ------------------------------------------------------ #


def _cfg():
    from agent86.config import load_config

    return load_config()


def test_context_window_known_families():
    cfg = _cfg()
    win = capabilities.context_window_for
    assert win("anthropic:claude-opus-4-8", cfg) == 200_000
    assert win("anthropic:claude-sonnet-5-20260101", cfg) == 200_000
    assert win("openai:gpt-4o", cfg) == 128_000
    assert win("openai:gpt-4.1", cfg) == 1_047_576
    assert win("openai:gpt-5", cfg) == 400_000
    assert win("openai:o3-mini", cfg) == 200_000
    # An OpenAI-compatible gateway carries the upstream model id; the family still resolves.
    assert win("openai:anthropic/claude-3.7-sonnet", cfg) == 200_000


def test_context_window_ollama_follows_num_ctx():
    cfg = _cfg()
    assert cfg.providers["ollama"].num_ctx == 8192
    assert capabilities.context_window_for("ollama:qwen2.5:3b", cfg) == 8192
    cfg.providers["ollama"].num_ctx = 32_768
    # The SERVER owns an Ollama window, not the model name — num_ctx wins over the table.
    assert capabilities.context_window_for("ollama:qwen2.5:3b", cfg) == 32_768
    cfg.providers["ollama"].num_ctx = None
    assert capabilities.context_window_for("ollama:qwen2.5:3b", cfg) == 8_192


def test_context_window_llamacpp_and_unknown_fall_back():
    cfg = _cfg()
    assert capabilities.context_window_for("llamacpp:any-gguf", cfg) == 8_192
    assert capabilities.context_window_for("mystery:model-x", cfg) == 8_192


def test_context_window_config_override_wins():
    cfg = _cfg()
    cfg.model.context_window = {"ollama:qwen2.5:3b": 16_384}
    assert capabilities.context_window_for("ollama:qwen2.5:3b", cfg) == 16_384
    # The override beats a known family too, and a bare model id is accepted as the key.
    cfg.model.context_window = {"claude-opus-4-8": 42_000}
    assert capabilities.context_window_for("anthropic:claude-opus-4-8", cfg) == 42_000


def test_max_output_tokens_precedence():
    cfg = _cfg()
    out = capabilities.max_output_tokens_for
    assert out("anthropic:claude-opus-4-8", cfg) == cfg.limits.max_output_tokens == 8192
    cfg.providers["anthropic"].max_tokens = 2048
    assert out("anthropic:claude-opus-4-8", cfg) == 2048
    # A provider with no block of its own falls back to the limits default.
    assert out("mystery:model-x", cfg) == 8192
