"""Phase 7 — OpenAI-compatible provider (mocked SSE, no network)."""

from __future__ import annotations

import copy
import json

import httpx
import pytest

from agent86.cognitive import openai_provider as mod
from agent86.cognitive.base import ProviderError
from agent86.cognitive.openai_provider import OpenAIProvider
from agent86.config import ProviderConfig
from agent86.types import (
    INVALID_TOOL_ARGS_KEY,
    CompletionRequest,
    Message,
    Role,
    ToolCall,
)


def _provider() -> OpenAIProvider:
    return OpenAIProvider(
        "test-model", ProviderConfig(base_url="http://local/v1"), require_key=False
    )


def _patch_stream(monkeypatch, lines: list[str]) -> None:
    class Resp:
        status_code = 200
        text = ""

        def read(self):
            pass

        def iter_lines(self):
            yield from lines

    class CM:
        def __enter__(self):
            return Resp()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mod.httpx, "stream", lambda *a, **k: CM())


def _sse(obj) -> str:
    return "data: " + json.dumps(obj)


def _drain(gen) -> list:
    return list(gen)


def test_text_streaming_and_usage(monkeypatch):
    lines = [
        _sse({"choices": [{"delta": {"content": "Hel"}}]}),
        _sse({"choices": [{"delta": {"content": "lo"}}]}),
        _sse({
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }),
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, lines)
    completion = _provider().complete(
        CompletionRequest(model="test-model", messages=[Message(role=Role.USER, content="hi")])
    )
    assert completion.text == "Hello"
    assert completion.usage.input_tokens == 5
    assert completion.usage.output_tokens == 2
    # Normalized, not OpenAI's raw "stop" — the loop must not need a per-provider test.
    assert completion.stop_reason == "end_turn"


def test_tool_call_accumulation_across_chunks(monkeypatch):
    lines = [
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "function": {"name": "get_sum", "arguments": '{"a": 21, '}}
        ]}}]}),
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '"b": 21}'}}
        ]}}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, lines)
    completion = _provider().complete(CompletionRequest(model="test-model", messages=[]))
    assert len(completion.tool_calls) == 1
    tc = completion.tool_calls[0]
    assert tc.name == "get_sum"
    assert tc.arguments == {"a": 21, "b": 21}
    assert tc.id == "call_1"


def test_unparseable_tool_arguments_carry_the_raw_string(monkeypatch):
    # `{}` used to be substituted here, so the model was told a required field was missing
    # when the real problem was its own JSON.
    lines = [
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "function": {"name": "write_file",
                                                      "arguments": '{"path": "a.txt", '}}
        ]}}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, lines)
    completion = _provider().complete(CompletionRequest(model="test-model", messages=[]))

    tc = completion.tool_calls[0]
    assert tc.invalid_arguments == '{"path": "a.txt", '
    assert tc.arguments == {INVALID_TOOL_ARGS_KEY: '{"path": "a.txt", '}


def test_non_object_tool_arguments_are_treated_as_invalid(monkeypatch):
    # Valid JSON, but not an arguments object — a tool cannot be called with a bare string.
    lines = [
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "c1", "function": {"name": "t", "arguments": '"just a string"'}}
        ]}}]}),
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, lines)
    completion = _provider().complete(CompletionRequest(model="test-model", messages=[]))
    assert completion.tool_calls[0].invalid_arguments == '"just a string"'


def test_message_conversion():
    msgs = [
        Message(role=Role.SYSTEM, content="sys"),
        Message(role=Role.USER, content="hi"),
        Message(
            role=Role.ASSISTANT, content="",
            tool_calls=[ToolCall(id="c1", name="t", arguments={"x": 1})],
        ),
        Message(role=Role.TOOL, content="result", tool_call_id="c1", name="t"),
    ]
    out = OpenAIProvider._to_messages(msgs)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1] == {"role": "user", "content": "hi"}
    assert out[2]["role"] == "assistant"
    fn = out[2]["tool_calls"][0]["function"]
    assert fn["name"] == "t"
    assert json.loads(fn["arguments"]) == {"x": 1}
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "result"}


def test_malformed_sse_chunk_becomes_provider_error(monkeypatch):
    # A truncated SSE line used to escape as a bare json.JSONDecodeError, which names
    # neither the endpoint nor the model.
    _patch_stream(monkeypatch, [_sse({"choices": [{"delta": {"content": "hi"}}]}), "data: {oops"])
    with pytest.raises(ProviderError) as excinfo:
        _provider().complete(CompletionRequest(model="test-model", messages=[]))
    message = str(excinfo.value)
    assert "malformed streaming chunk" in message
    assert "http://local/v1" in message
    assert "test-model" in message


def test_transport_failure_mid_stream_becomes_provider_error(monkeypatch):
    class Resp:
        status_code = 200
        text = ""

        def read(self):
            pass

        def iter_lines(self):
            yield _sse({"choices": [{"delta": {"content": "hi"}}]})
            raise httpx.RemoteProtocolError("peer closed connection without response")

    class CM:
        def __enter__(self):
            return Resp()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mod.httpx, "stream", lambda *a, **k: CM())

    with pytest.raises(ProviderError, match="RemoteProtocolError"):
        _provider().complete(CompletionRequest(model="test-model", messages=[]))


# --------------------------------------------------------------------------- #
# v0.8 — output cap, cached prompt tokens, and the normalized stop_reason
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _forget_legacy_endpoints():
    """The legacy-dialect memo is module state; a test must not leak it into the next."""
    mod._LEGACY_MAX_TOKENS_ENDPOINTS.clear()
    yield
    mod._LEGACY_MAX_TOKENS_ENDPOINTS.clear()


def _capture_payload(monkeypatch, lines=None, statuses=None):
    """Record every request payload; optionally script a sequence of HTTP statuses."""
    payloads: list[dict] = []
    scripted = list(statuses or [])
    body = lines if lines is not None else ["data: [DONE]"]

    class Resp:
        def __init__(self, status: int, text: str = ""):
            self.status_code = status
            self.text = text
            self.headers: dict[str, str] = {}

        def read(self):
            pass

        def iter_lines(self):
            yield from body

    class CM:
        def __init__(self, resp):
            self._resp = resp

        def __enter__(self):
            return self._resp

        def __exit__(self, *a):
            return False

    def fake_stream(*args, **kwargs):
        payloads.append(copy.deepcopy(kwargs["json"]))
        if scripted:
            status, text = scripted.pop(0)
            return CM(Resp(status, text))
        return CM(Resp(200))

    monkeypatch.setattr(mod.httpx, "stream", fake_stream)
    return payloads


_REJECTION_BODY = (
    '{"error": {"message": "Unrecognized request argument supplied: '
    'max_completion_tokens", "type": "invalid_request_error"}}'
)


def test_request_max_tokens_uses_the_current_openai_name(monkeypatch):
    payloads = _capture_payload(monkeypatch)
    _drain(_provider().stream(CompletionRequest(model="test-model", messages=[], max_tokens=64)))
    assert payloads[0]["max_completion_tokens"] == 64
    assert "max_tokens" not in payloads[0]


def test_no_cap_sent_when_nobody_asked_for_one(monkeypatch):
    payloads = _capture_payload(monkeypatch)
    _drain(_provider().stream(CompletionRequest(model="test-model", messages=[])))
    assert "max_completion_tokens" not in payloads[0]
    assert "max_tokens" not in payloads[0]


def test_openai_provider_config_max_tokens_used_when_request_is_silent(monkeypatch):
    config = ProviderConfig(base_url="http://local/v1")
    if not hasattr(config, "max_tokens"):
        pytest.skip("config.py has not grown ProviderConfig.max_tokens yet")
    config.max_tokens = 1234
    payloads = _capture_payload(monkeypatch)
    provider = OpenAIProvider("test-model", config, require_key=False)
    _drain(provider.stream(CompletionRequest(model="test-model", messages=[])))
    assert payloads[0]["max_completion_tokens"] == 1234


def test_legacy_endpoint_gets_one_retry_under_the_old_name(monkeypatch):
    # Groq / OpenRouter / vLLM only know `max_tokens`. One 400, then the swap.
    payloads = _capture_payload(monkeypatch, statuses=[(400, _REJECTION_BODY), (200, "")])
    completion = _provider().complete(
        CompletionRequest(model="test-model", messages=[], max_tokens=64)
    )
    assert len(payloads) == 2
    assert payloads[0]["max_completion_tokens"] == 64
    assert payloads[1]["max_tokens"] == 64
    assert "max_completion_tokens" not in payloads[1]
    assert completion.text == ""


def test_the_swap_is_remembered_for_the_rest_of_the_session(monkeypatch):
    _capture_payload(monkeypatch, statuses=[(400, _REJECTION_BODY), (200, "")])
    _provider().complete(CompletionRequest(model="test-model", messages=[], max_tokens=64))

    # A fresh provider against the same endpoint must not pay for the probe again.
    payloads = _capture_payload(monkeypatch)
    _drain(_provider().stream(CompletionRequest(model="test-model", messages=[], max_tokens=64)))
    assert payloads[0]["max_tokens"] == 64
    assert "max_completion_tokens" not in payloads[0]


def test_the_swap_survives_retries_being_switched_off(monkeypatch):
    # The swap is a deterministic correction, not a flaky endpoint: it must not come out
    # of the transient-failure budget, which max_retries=0 sets to nothing.
    config = ProviderConfig(base_url="http://local/v1", max_retries=0)
    payloads = _capture_payload(monkeypatch, statuses=[(400, _REJECTION_BODY), (200, "")])
    provider = OpenAIProvider("test-model", config, require_key=False)
    provider.complete(CompletionRequest(model="test-model", messages=[], max_tokens=64))
    assert len(payloads) == 2
    assert payloads[1]["max_tokens"] == 64


def test_an_unrelated_400_is_not_swapped(monkeypatch):
    payloads = _capture_payload(
        monkeypatch, statuses=[(400, '{"error": {"message": "model not found"}}')]
    )
    with pytest.raises(ProviderError, match="model not found"):
        _provider().complete(CompletionRequest(model="test-model", messages=[], max_tokens=64))
    assert len(payloads) == 1


def test_the_swap_is_attempted_only_once(monkeypatch):
    # A server that 400s both spellings must surface the error, not loop.
    payloads = _capture_payload(
        monkeypatch, statuses=[(400, _REJECTION_BODY), (400, _REJECTION_BODY)]
    )
    with pytest.raises(ProviderError):
        _provider().complete(CompletionRequest(model="test-model", messages=[], max_tokens=64))
    assert len(payloads) == 2


def test_stream_options_requests_usage(monkeypatch):
    # Without this, a streamed response carries no token counts at all and every cost
    # figure for a streaming run would be zero.
    payloads = _capture_payload(monkeypatch)
    _drain(_provider().stream(CompletionRequest(model="test-model", messages=[])))
    assert payloads[0]["stream_options"] == {"include_usage": True}


def test_cached_prompt_tokens_land_in_usage(monkeypatch):
    lines = [
        _sse(
            {
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 10,
                    "prompt_tokens_details": {"cached_tokens": 768},
                },
            }
        ),
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, lines)
    usage = _provider().complete(CompletionRequest(model="test-model", messages=[])).usage
    # OpenAI's cached_tokens is a SUBSET of prompt_tokens, so input_tokens stays the whole
    # prompt and the cache field is the breakdown.
    assert usage.input_tokens == 1000
    assert usage.cache_read_tokens == 768
    assert usage.cache_creation_tokens == 0


def test_usage_without_cache_details_is_unchanged(monkeypatch):
    lines = [
        _sse(
            {
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            }
        ),
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, lines)
    usage = _provider().complete(CompletionRequest(model="test-model", messages=[])).usage
    assert (usage.input_tokens, usage.output_tokens) == (12, 3)
    assert usage.cache_read_tokens == 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stop", "end_turn"),
        ("tool_calls", "tool_use"),
        ("function_call", "tool_use"),
        ("length", "max_tokens"),
        ("content_filter", "other"),
        ("something-new", "other"),
        (None, None),
    ],
)
def test_finish_reason_normalization_table(raw, expected):
    assert mod.normalize_stop_reason(raw) == expected


def test_truncation_is_reported_as_max_tokens(monkeypatch):
    lines = [
        _sse({"choices": [{"delta": {"content": "half a th"}, "finish_reason": "length"}]}),
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, lines)
    completion = _provider().complete(CompletionRequest(model="test-model", messages=[]))
    assert completion.stop_reason == "max_tokens"


def test_tool_calls_override_a_plain_stop(monkeypatch):
    # llama.cpp and friends report "stop" on a turn that did emit tool calls.
    lines = [
        _sse(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "c1",
                                    "function": {"name": "t", "arguments": "{}"},
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, lines)
    completion = _provider().complete(CompletionRequest(model="test-model", messages=[]))
    assert completion.stop_reason == "tool_use"


def test_llamacpp_inherits_the_openai_output_cap(monkeypatch):
    from agent86.cognitive.llamacpp_provider import LlamaCppProvider

    payloads = _capture_payload(monkeypatch)
    provider = LlamaCppProvider("local-model", ProviderConfig())
    _drain(provider.stream(CompletionRequest(model="local-model", messages=[], max_tokens=128)))
    assert payloads[0]["max_completion_tokens"] == 128


def test_rejection_predicate_needs_both_the_name_and_a_refusal():
    assert mod.is_max_tokens_rejection(_REJECTION_BODY)
    assert not mod.is_max_tokens_rejection('{"error": "rate limited"}')
    # Mentioning the parameter in passing is not a refusal of it.
    assert not mod.is_max_tokens_rejection("max_completion_tokens was 64")
