"""Sampling-params gating tests for both providers (UAT gap 5, closure plan 03-12).

Anthropic: temperature/top_p/top_k must be omitted entirely for the removed-parameter
families, with a self-correcting one-shot retry when the API itself rejects the parameter.
OpenAI-compatible: behaviour must stay byte-identical for OpenAI/Groq/OpenRouter today, but
route through the same seam so a gateway proxying an Anthropic model gets the correct
omission for free.
"""

from __future__ import annotations

import json

import anthropic
import httpx
import pytest

from agent86.cognitive import capabilities
from agent86.cognitive import openai_provider as openai_mod
from agent86.cognitive.anthropic_provider import AnthropicProvider
from agent86.cognitive.openai_provider import OpenAIProvider
from agent86.config import ProviderConfig
from agent86.types import CompletionRequest, Message, Role


@pytest.fixture(autouse=True)
def _clear_learned():
    capabilities._LEARNED_NO_SAMPLING.clear()
    yield
    capabilities._LEARNED_NO_SAMPLING.clear()


# --------------------------------------------------------------------------- #
# Anthropic — fake client helpers
# --------------------------------------------------------------------------- #


class _FakeStream:
    """Mimics the `with client.messages.stream(**kwargs) as stream:` context manager."""

    def __init__(self, text: str = "hi", final=None, error: Exception | None = None):
        self._text = text
        self._final = final or _fake_final()
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        if self._error is not None:
            raise self._error
        yield self._text

    def get_final_message(self):
        return self._final


def _fake_final(text: str = "hi"):
    block_text = text

    class Block:
        type = "text"
        text = block_text

    class Usage:
        input_tokens = 1
        output_tokens = 1

    class Final:
        content = [Block()]
        usage = Usage()
        stop_reason = "end_turn"

    return Final()


def _api_error(message: str) -> anthropic.APIError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIError(message, req, body=None)


class _RecordingClient:
    """Records the kwargs of every `messages.stream(...)` call; yields queued responses."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

        class _Messages:
            def stream(inner_self, **kwargs):
                self.calls.append(kwargs)
                resp = self._responses.pop(0)
                if isinstance(resp, Exception):
                    return _FakeStream(error=resp)
                return resp

        self.messages = _Messages()


def _provider(model: str) -> AnthropicProvider:
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider.model = model
    provider._config = ProviderConfig()
    return provider


def _drain(gen):
    return list(gen)


# --------------------------------------------------------------------------- #
# Anthropic tests
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "model",
    ["claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-5", "claude-fable-5"],
)
def test_anthropic_stream_omits_sampling_params_for_removed_families(model):
    provider = _provider(model)
    client = _RecordingClient([_FakeStream()])
    provider._client = client

    _drain(provider.stream(CompletionRequest(model=model, messages=[], temperature=0.0)))

    assert len(client.calls) == 1
    kwargs = client.calls[0]
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs


def test_anthropic_stream_keeps_temperature_for_unaffected_model():
    model = "claude-sonnet-4-5"
    provider = _provider(model)
    client = _RecordingClient([_FakeStream()])
    provider._client = client

    _drain(provider.stream(CompletionRequest(model=model, messages=[], temperature=0.0)))

    assert client.calls[0]["temperature"] == 0.0


def test_anthropic_complete_inherits_gating():
    model = "claude-opus-5"
    provider = _provider(model)
    client = _RecordingClient([_FakeStream()])
    provider._client = client

    completion = provider.complete(
        CompletionRequest(model=model, messages=[], temperature=0.0)
    )

    assert "temperature" not in client.calls[0]
    assert completion.text == "hi"


def test_anthropic_self_corrects_on_real_rejection_and_retries_once():
    model = "some-unknown-future-model"
    provider = _provider(model)
    rejection = _api_error("`temperature` is deprecated this model.")
    client = _RecordingClient([rejection, _FakeStream(text="ok")])
    provider._client = client

    deltas = _drain(
        provider.stream(CompletionRequest(model=model, messages=[], temperature=0.0))
    )

    assert len(client.calls) == 2
    assert "temperature" in client.calls[0]
    assert "temperature" not in client.calls[1]
    texts = [d.text for d in deltas if d.text]
    assert texts == ["ok"]
    assert all(not getattr(d, "completion", None) or True for d in deltas)  # no crash
    assert deltas[-1].done is True


def test_anthropic_self_correction_populates_learned_set():
    model = "some-unknown-future-model"
    provider = _provider(model)
    rejection = _api_error("`temperature` is deprecated this model.")
    client = _RecordingClient([rejection, _FakeStream(text="ok")])
    provider._client = client

    _drain(provider.stream(CompletionRequest(model=model, messages=[], temperature=0.0)))

    assert capabilities.supports_sampling_params(model) is False


def test_anthropic_unrelated_error_raises_without_retry():
    from agent86.cognitive.base import ProviderError

    model = "claude-sonnet-4-5"
    provider = _provider(model)
    unrelated = _api_error("model not found")
    client = _RecordingClient([unrelated])
    provider._client = client

    with pytest.raises(ProviderError):
        _drain(provider.stream(CompletionRequest(model=model, messages=[], temperature=0.0)))

    assert len(client.calls) == 1


def test_anthropic_max_tokens_system_tools_unchanged():
    from agent86.types import ToolSpec

    model = "claude-sonnet-4-5"
    provider = _provider(model)
    client = _RecordingClient([_FakeStream()])
    provider._client = client

    request = CompletionRequest(
        model=model,
        messages=[
            Message(role=Role.SYSTEM, content="sys"),
            Message(role=Role.USER, content="hi"),
        ],
        max_tokens=123,
        tools=[ToolSpec(name="t", description="d", parameters={})],
        temperature=0.5,
    )
    _drain(provider.stream(request))

    kwargs = client.calls[0]
    assert kwargs["max_tokens"] == 123
    assert kwargs["system"] == "sys"
    assert kwargs["tools"][0]["name"] == "t"


# --------------------------------------------------------------------------- #
# OpenAI-compatible tests
# --------------------------------------------------------------------------- #


def _openai_provider(model: str) -> OpenAIProvider:
    return OpenAIProvider(model, ProviderConfig(base_url="http://local/v1"), require_key=False)


def _patch_stream_capture(monkeypatch):
    captured: dict = {}

    class Resp:
        status_code = 200
        text = ""

        def read(self):
            pass

        def iter_lines(self):
            yield "data: [DONE]"

    class CM:
        def __enter__(self):
            return Resp()

        def __exit__(self, *a):
            return False

    def fake_stream(method, url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return CM()

    monkeypatch.setattr(openai_mod.httpx, "stream", fake_stream)
    return captured


def test_openai_payload_keeps_temperature_for_gpt(monkeypatch):
    captured = _patch_stream_capture(monkeypatch)
    provider = _openai_provider("gpt-4o")
    _drain(
        provider.stream(
            CompletionRequest(
                model="gpt-4o",
                messages=[Message(role=Role.USER, content="hi")],
                temperature=0.0,
            )
        )
    )
    assert captured["payload"]["temperature"] == 0.0


def test_openai_payload_omits_temperature_for_removed_family(monkeypatch):
    captured = _patch_stream_capture(monkeypatch)
    provider = _openai_provider("claude-opus-5")
    _drain(
        provider.stream(
            CompletionRequest(
                model="claude-opus-5",
                messages=[Message(role=Role.USER, content="hi")],
                temperature=0.0,
            )
        )
    )
    assert "temperature" not in captured["payload"]


def test_openai_payload_other_keys_unchanged(monkeypatch):
    from agent86.types import ToolSpec

    captured = _patch_stream_capture(monkeypatch)
    provider = _openai_provider("gpt-4o")
    _drain(
        provider.stream(
            CompletionRequest(
                model="gpt-4o",
                messages=[Message(role=Role.USER, content="hi")],
                max_tokens=50,
                tools=[ToolSpec(name="t", description="d", parameters={})],
                temperature=0.7,
            )
        )
    )
    payload = captured["payload"]
    assert payload["model"] == "gpt-4o"
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["max_tokens"] == 50
    assert payload["tool_choice"] == "auto"
    assert payload["tools"][0]["function"]["name"] == "t"
