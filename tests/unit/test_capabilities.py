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
