"""Phase 7 — OpenAI-compatible provider (mocked SSE, no network)."""

from __future__ import annotations

import json

from agent86.cognitive import openai_provider as mod
from agent86.cognitive.openai_provider import OpenAIProvider
from agent86.config import ProviderConfig
from agent86.types import CompletionRequest, Message, Role, ToolCall


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
