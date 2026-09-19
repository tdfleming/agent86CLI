"""Phase 7 — OpenAI-compatible provider (mocked SSE, no network)."""

from __future__ import annotations

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
    assert completion.stop_reason == "stop"


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
