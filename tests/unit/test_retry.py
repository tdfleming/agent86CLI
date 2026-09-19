"""Retries with backoff for transient provider failures (v0.7 task 2).

Covers the shared `cognitive/retry.py` decisions in isolation and their wiring into the
streaming providers. Backoff is made instant by monkeypatching `retry.sleep`, so these are
plain fast unit tests — nothing here waits on a real clock or a real socket.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from agent86.cognitive import ollama_provider as ollama_mod
from agent86.cognitive import openai_provider as openai_mod
from agent86.cognitive import retry as retry_mod
from agent86.cognitive.base import ProviderError
from agent86.cognitive.ollama_provider import OllamaProvider
from agent86.cognitive.openai_provider import OpenAIProvider
from agent86.cognitive.retry import (
    DEFAULT_MAX_RETRIES,
    RetryPolicy,
    backoff_delay,
    is_retryable_exception,
    is_retryable_status,
    max_retries_for,
    parse_retry_after,
)
from agent86.config import ProviderConfig
from agent86.types import CompletionRequest, Message, Role

# --- the policy in isolation ------------------------------------------------------------ #


def test_retryable_status_set():
    assert all(is_retryable_status(s) for s in (429, 500, 502, 503, 504))
    assert not any(is_retryable_status(s) for s in (200, 400, 401, 403, 404, 422))


def test_retryable_exceptions():
    assert is_retryable_exception(httpx.ConnectError("refused"))
    assert is_retryable_exception(httpx.RemoteProtocolError("peer closed"))
    assert not is_retryable_exception(httpx.ReadError("boom"))
    assert not is_retryable_exception(ValueError("nope"))


def test_max_retries_for_falls_back_when_config_lacks_the_field():
    # The provider must work both before and after config.py grows `max_retries`.
    assert max_retries_for(ProviderConfig()) in (DEFAULT_MAX_RETRIES, 2)
    assert max_retries_for(object()) == DEFAULT_MAX_RETRIES

    class _WithField:
        max_retries = 5

    assert max_retries_for(_WithField()) == 5


def test_backoff_grows_and_carries_jitter():
    # Deterministic jitter (always the top of the random half) so the curve is assertable.
    top = backoff_delay(0, jitter=lambda lo, hi: hi)
    bottom = backoff_delay(0, jitter=lambda lo, hi: lo)
    assert bottom < top  # the jitter half actually varies the delay
    assert backoff_delay(0, jitter=lambda lo, hi: hi) < backoff_delay(
        3, jitter=lambda lo, hi: hi
    )
    assert backoff_delay(50, jitter=lambda lo, hi: hi) <= 30.0  # capped


def test_parse_retry_after_seconds_and_http_date():
    assert parse_retry_after("2.5") == 2.5
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("not-a-date") is None

    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
    when = format_datetime(now + timedelta(seconds=7))
    assert parse_retry_after(when, now=now) == pytest.approx(7.0, abs=1.0)
    # A date already in the past means "come back now", not a negative sleep.
    past = format_datetime(now - timedelta(seconds=30))
    assert parse_retry_after(past, now=now) == 0.0


def test_policy_stops_at_the_budget_and_never_retries_after_a_delta():
    slept: list[float] = []
    policy = RetryPolicy(2, provider="p", model="m", sleeper=slept.append)

    assert policy.retry_status(503, 0) is True
    assert policy.retry_status(503, 1) is True
    assert policy.retry_status(503, 2) is False  # budget exhausted
    assert policy.retry_status(400, 0) is False  # not retryable
    # Text already streamed: another attempt would duplicate it in the transcript.
    assert policy.retry_status(503, 0, emitted=True) is False
    assert policy.retry_exception(httpx.ConnectError("x"), 0, emitted=True) is False
    assert len(slept) == 2
    assert policy.retries == 2


# --- wired into the OpenAI-compatible provider -------------------------------------------- #


class _Resp:
    """One scripted HTTP response for a single attempt."""

    def __init__(self, status: int = 200, lines: list[str] | None = None,
                 headers: dict[str, str] | None = None, error: BaseException | None = None):
        self.status_code = status
        self.text = "server said no"
        self.headers = headers or {}
        self._lines = lines or []
        self._error = error

    def read(self) -> None:
        pass

    def iter_lines(self):
        yield from self._lines
        if self._error is not None:
            raise self._error


def _script(monkeypatch, module, responses: list[_Resp]) -> dict:
    """Serve `responses` one per attempt, and make backoff instant."""
    state = {"attempts": 0, "slept": []}

    class CM:
        def __enter__(self):
            index = state["attempts"]
            state["attempts"] += 1
            return responses[min(index, len(responses) - 1)]

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(module.httpx, "stream", lambda *a, **k: CM())
    monkeypatch.setattr(retry_mod, "sleep", state["slept"].append)
    return state


def _openai(max_retries: int = 2) -> OpenAIProvider:
    config = ProviderConfig(base_url="http://local/v1")
    provider = OpenAIProvider("test-model", config, require_key=False)
    provider._max_retries = max_retries  # config.max_retries may not exist yet
    return provider


def _sse(obj) -> str:
    return "data: " + json.dumps(obj)


_OK_LINES = [
    _sse({"choices": [{"delta": {"content": "hi"}}, ]}),
    _sse({"choices": [{"delta": {}, "finish_reason": "stop"}],
          "usage": {"prompt_tokens": 1, "completion_tokens": 1}}),
    "data: [DONE]",
]


def test_429_honours_retry_after_then_succeeds(monkeypatch):
    state = _script(
        monkeypatch,
        openai_mod,
        [_Resp(429, headers={"retry-after": "3"}), _Resp(200, _OK_LINES)],
    )
    completion = _openai().complete(
        CompletionRequest(model="test-model", messages=[Message(role=Role.USER, content="x")])
    )
    assert completion.text == "hi"
    assert state["attempts"] == 2
    assert state["slept"] == [3.0]  # the server's Retry-After, not our backoff curve


def test_503_is_retried_then_succeeds(monkeypatch):
    state = _script(monkeypatch, openai_mod, [_Resp(503), _Resp(200, _OK_LINES)])
    completion = _openai().complete(CompletionRequest(model="test-model", messages=[]))
    assert completion.text == "hi"
    assert state["attempts"] == 2
    assert len(state["slept"]) == 1 and state["slept"][0] > 0  # backoff, with jitter


def test_400_is_not_retried(monkeypatch):
    state = _script(monkeypatch, openai_mod, [_Resp(400)])
    with pytest.raises(ProviderError, match="HTTP 400"):
        _openai().complete(CompletionRequest(model="test-model", messages=[]))
    assert state["attempts"] == 1
    assert state["slept"] == []


def test_retry_budget_exhausted_raises_provider_error(monkeypatch):
    state = _script(monkeypatch, openai_mod, [_Resp(503)])
    with pytest.raises(ProviderError, match="HTTP 503"):
        _openai(max_retries=2).complete(CompletionRequest(model="test-model", messages=[]))
    assert state["attempts"] == 3  # the initial try plus two retries
    assert len(state["slept"]) == 2


def test_connect_error_before_any_byte_is_retried(monkeypatch):
    state = {"attempts": 0, "slept": []}
    responses = [httpx.ConnectError("refused"), _Resp(200, _OK_LINES)]

    class CM:
        def __enter__(self):
            index = state["attempts"]
            state["attempts"] += 1
            item = responses[min(index, len(responses) - 1)]
            if isinstance(item, BaseException):
                raise item
            return item

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(openai_mod.httpx, "stream", lambda *a, **k: CM())
    monkeypatch.setattr(retry_mod, "sleep", state["slept"].append)

    completion = _openai().complete(CompletionRequest(model="test-model", messages=[]))
    assert completion.text == "hi"
    assert state["attempts"] == 2


def test_no_retry_once_a_delta_has_been_yielded(monkeypatch):
    """A drop mid-stream must surface, not replay — the text is already on screen."""
    state = _script(
        monkeypatch,
        openai_mod,
        [
            _Resp(200, [_sse({"choices": [{"delta": {"content": "par"}}]})],
                  error=httpx.RemoteProtocolError("peer closed")),
            _Resp(200, _OK_LINES),
        ],
    )
    provider = _openai()
    deltas = []
    with pytest.raises(ProviderError, match="RemoteProtocolError"):
        for delta in provider.stream(CompletionRequest(model="test-model", messages=[])):
            deltas.append(delta)

    assert [d.text for d in deltas] == ["par"]  # emitted once, never duplicated
    assert state["attempts"] == 1
    assert state["slept"] == []


def test_zero_retries_makes_one_attempt(monkeypatch):
    state = _script(monkeypatch, openai_mod, [_Resp(503)])
    with pytest.raises(ProviderError, match="HTTP 503"):
        _openai(max_retries=0).complete(CompletionRequest(model="test-model", messages=[]))
    assert state["attempts"] == 1


# --- wired into the Ollama provider -------------------------------------------------------- #


def _ollama(max_retries: int = 2) -> OllamaProvider:
    provider = OllamaProvider("qwen3.5:4b", ProviderConfig())
    provider._max_retries = max_retries
    return provider


def test_ollama_retries_503_then_succeeds(monkeypatch):
    ok = [json.dumps({"message": {"content": "hi"}, "done": True, "done_reason": "stop"})]
    state = _script(monkeypatch, ollama_mod, [_Resp(503), _Resp(200, ok)])
    completion = _ollama().complete(CompletionRequest(model="qwen3.5:4b", messages=[]))
    assert completion.text == "hi"
    assert state["attempts"] == 2


def test_ollama_404_is_not_retried(monkeypatch):
    state = _script(monkeypatch, ollama_mod, [_Resp(404)])
    with pytest.raises(ProviderError, match="HTTP 404"):
        _ollama().complete(CompletionRequest(model="qwen3.5:4b", messages=[]))
    assert state["attempts"] == 1
