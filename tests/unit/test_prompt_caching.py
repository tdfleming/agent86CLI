"""Prompt caching and cache accounting.

Two halves. First the shared ``Usage`` fields every provider reports into — the
provider-agnostic contract the loop and the status line read. Then the Anthropic adapter
that actually asks for caching: what ``cache_control`` the request carries, where, when it
is left off, and how the response's cache counts reach ``Usage``.

All of it runs against a fake SDK client — no network, no key.
"""

from __future__ import annotations

import pytest

from agent86.cognitive import anthropic_provider as anthropic_mod
from agent86.cognitive.anthropic_provider import AnthropicProvider
from agent86.config import ProviderConfig
from agent86.types import CompletionRequest, Message, Role, ToolSpec, Usage

# --------------------------------------------------------------------------- #
# Fake Anthropic SDK client
# --------------------------------------------------------------------------- #


def _usage_obj(
    input_tokens: int = 1,
    output_tokens: int = 1,
    cache_read: int | None = None,
    cache_creation: int | None = None,
):
    """A stand-in for the SDK's usage object.

    ``cache_read``/``cache_creation`` left as ``None`` omit the attributes entirely, which
    is what an older SDK — or a response for a request that asked for no caching — looks
    like. The adapter must read those through ``getattr`` and not explode.
    """

    class _Usage:
        pass

    usage = _Usage()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    if cache_read is not None:
        usage.cache_read_input_tokens = cache_read
    if cache_creation is not None:
        usage.cache_creation_input_tokens = cache_creation
    return usage


def _fake_final(text: str = "hi", usage=None, stop_reason: str = "end_turn"):
    block_text, final_usage, final_stop = text, usage or _usage_obj(), stop_reason

    class Block:
        type = "text"
        text = block_text

    class Final:
        content = [Block()]

    Final.usage = final_usage
    Final.stop_reason = final_stop
    return Final()


class _FakeStream:
    """Mimics ``with client.messages.stream(**kwargs) as stream:``."""

    def __init__(self, text: str = "hi", final=None):
        self._text = text
        self._final = final if final is not None else _fake_final()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        yield self._text

    def get_final_message(self):
        return self._final


class _RecordingClient:
    """Records the kwargs of every ``messages.stream(...)`` call."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

        class _Messages:
            def stream(inner_self, **kwargs):
                self.calls.append(kwargs)
                return self._responses.pop(0)

        self.messages = _Messages()


def _provider(model: str = "claude-opus-5", config: ProviderConfig | None = None):
    """An AnthropicProvider with the constructor (SDK import, key resolution) bypassed."""
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider.model = model
    provider._config = config if config is not None else ProviderConfig()
    return provider


def test_usage_cache_fields_default_to_zero() -> None:
    """A provider with no cache at all must still produce a valid Usage."""
    usage = Usage(input_tokens=10, output_tokens=3)
    assert usage.cache_read_tokens == 0
    assert usage.cache_creation_tokens == 0


def test_usage_add_accumulates_cache_fields() -> None:
    """Accumulation across steps has to carry the cache breakdown, not drop it."""
    a = Usage(
        input_tokens=100,
        output_tokens=10,
        cost_usd=0.5,
        cache_read_tokens=80,
        cache_creation_tokens=20,
    )
    b = Usage(
        input_tokens=200,
        output_tokens=20,
        cost_usd=1.5,
        cache_read_tokens=150,
        cache_creation_tokens=0,
    )
    total = a + b
    assert total.input_tokens == 300
    assert total.output_tokens == 30
    assert total.cost_usd == 2.0
    assert total.cache_read_tokens == 230
    assert total.cache_creation_tokens == 20


def test_usage_sum_starts_from_empty() -> None:
    """``sum(..., Usage())`` is how the loop folds per-step usage — keep it working."""
    steps = [
        Usage(input_tokens=1, cache_read_tokens=1),
        Usage(input_tokens=2, cache_creation_tokens=4),
    ]
    total = Usage()
    for s in steps:
        total = total + s
    assert (total.cache_read_tokens, total.cache_creation_tokens) == (1, 4)


def test_completion_request_exposes_max_tokens() -> None:
    """The loop feature-detects this field by name; it must exist and default to None."""
    assert "max_tokens" in CompletionRequest.model_fields
    req = CompletionRequest(model="m", messages=[])
    assert req.max_tokens is None
    assert CompletionRequest(model="m", messages=[], max_tokens=512).max_tokens == 512


# --------------------------------------------------------------------------- #
# Anthropic prompt caching — what the request actually carries
# --------------------------------------------------------------------------- #

#: ~1000 tokens at the ~4-chars-per-token estimate the provider uses: comfortably over the
#: 512-token floor for claude-opus-5, comfortably under the 4096-token floor for opus-4-6.
_LONG_SYSTEM = "You are a careful assistant. " * 143


def _tool(name: str, description: str = "d") -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
    )


def _big_tools(count: int = 12) -> list[ToolSpec]:
    """Enough tool schema to clear the 512-token minimum on its own."""
    return [_tool(f"tool_{i}", "does a thing in a long-winded way. " * 12) for i in range(count)]


def _kwargs_for(
    model: str = "claude-opus-5",
    *,
    system: str | None = _LONG_SYSTEM,
    tools: list[ToolSpec] | None = None,
    config: ProviderConfig | None = None,
    usage=None,
) -> dict:
    """Run one stream against the fake SDK client and return the request kwargs."""
    provider = _provider(model, config)
    client = _RecordingClient([_FakeStream(final=_fake_final(usage=usage))])
    provider._client = client
    messages = []
    if system is not None:
        messages.append(Message(role=Role.SYSTEM, content=system))
    messages.append(Message(role=Role.USER, content="hi"))
    list(provider.stream(CompletionRequest(model=model, messages=messages, tools=tools or [])))
    return client.calls[0]


def test_system_prompt_becomes_a_cacheable_block():
    kwargs = _kwargs_for()
    assert kwargs["system"] == [
        {"type": "text", "text": _LONG_SYSTEM, "cache_control": {"type": "ephemeral"}}
    ]


def test_last_tool_carries_the_breakpoint_so_the_whole_list_is_cached():
    kwargs = _kwargs_for(tools=_big_tools())
    tools = kwargs["tools"]
    assert tools[-1]["cache_control"] == {"type": "ephemeral"}
    # Exactly one marker on the tool list: the API renders tools as a prefix, so marking
    # the last one already covers every tool before it.
    assert [t for t in tools if "cache_control" in t] == [tools[-1]]


def test_at_most_two_breakpoints_are_spent():
    # The API allows four; leaving two free is what lets a caller mark message content.
    kwargs = _kwargs_for(tools=_big_tools())
    marked = sum(1 for t in kwargs["tools"] if "cache_control" in t)
    marked += sum(1 for b in kwargs["system"] if "cache_control" in b)
    assert marked == 2


def test_short_system_prompt_is_left_as_a_plain_string():
    # Below the minimum cacheable prefix the marker is silently ignored by the API, so
    # spending a breakpoint on it buys nothing.
    kwargs = _kwargs_for(system="be brief")
    assert kwargs["system"] == "be brief"


def test_short_tool_list_gets_no_breakpoint():
    kwargs = _kwargs_for(tools=[_tool("t")])
    assert all("cache_control" not in t for t in kwargs["tools"])


def test_tools_count_toward_the_system_prefix():
    # A system prompt too short on its own still caches when the tools before it are long:
    # the system block closes the tools+system prefix, and that is what the floor measures.
    kwargs = _kwargs_for(system="be brief", tools=_big_tools())
    assert isinstance(kwargs["system"], list)
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_model_with_a_higher_floor_is_not_marked():
    # Opus 4.6's minimum is 4096 tokens — eight times opus-5's — and the floor is not
    # monotonic across generations, so it has to be matched per model, not assumed.
    kwargs = _kwargs_for("claude-opus-4-6")
    assert kwargs["system"] == _LONG_SYSTEM


def test_unknown_model_falls_back_to_the_conservative_floor():
    kwargs = _kwargs_for("claude-something-unreleased")
    assert kwargs["system"] == _LONG_SYSTEM


@pytest.mark.parametrize(
    ("model", "minimum"),
    [
        ("claude-opus-5", 512),
        ("claude-opus-5-20260401", 512),
        ("anthropic:claude-fable-5-1", 512),
        ("claude-opus-4-8", 1024),
        ("claude-sonnet-5", 1024),
        ("claude-opus-4-7", 2048),
        ("claude-opus-4-6", 4096),
        ("claude-haiku-4-5", 4096),
        ("claude-brand-new", 4096),
    ],
)
def test_minimum_cacheable_prefix_table(model, minimum):
    assert anthropic_mod._cache_minimum_tokens(model) == minimum


def test_caching_is_omitted_when_the_provider_config_disables_it():
    config = ProviderConfig()
    if not hasattr(config, "prompt_cache"):
        pytest.skip("config.py has not grown ProviderConfig.prompt_cache yet")
    config.prompt_cache = False
    kwargs = _kwargs_for(tools=_big_tools(), config=config)
    assert kwargs["system"] == _LONG_SYSTEM
    assert all("cache_control" not in t for t in kwargs["tools"])


def test_caching_is_on_for_a_config_that_predates_the_flag():
    # ProviderConfig grows `prompt_cache` in another agent's commit; until then the
    # getattr default has to keep caching on rather than silently off.
    assert isinstance(_kwargs_for(config=ProviderConfig())["system"], list)


def test_a_request_with_no_system_prompt_is_untouched():
    kwargs = _kwargs_for(system=None)
    assert "system" not in kwargs


# --------------------------------------------------------------------------- #
# Cache usage accounting
# --------------------------------------------------------------------------- #


def test_cache_usage_fields_are_read_from_the_response():
    usage = _usage_obj(input_tokens=200, output_tokens=10, cache_read=800, cache_creation=1000)
    provider = _provider("claude-opus-5")
    provider._client = _RecordingClient([_FakeStream(final=_fake_final(usage=usage))])
    completion = provider.complete(CompletionRequest(model="claude-opus-5", messages=[]))
    assert completion.usage.cache_read_tokens == 800
    assert completion.usage.cache_creation_tokens == 1000
    # Anthropic reports input_tokens as the UNCACHED remainder; the harness's Usage carries
    # the whole prompt, so a well-cached turn still shows its real context size.
    assert completion.usage.input_tokens == 2000
    assert completion.usage.output_tokens == 10


def test_cost_prices_the_cached_portions_apart():
    usage = _usage_obj(input_tokens=0, output_tokens=0, cache_read=1_000_000, cache_creation=0)
    provider = _provider("claude-opus-5")
    provider._client = _RecordingClient([_FakeStream(final=_fake_final(usage=usage))])
    completion = provider.complete(CompletionRequest(model="claude-opus-5", messages=[]))
    # A million cache-read tokens on a $5/MTok model costs $0.50, not $5.00.
    assert completion.usage.cost_usd == pytest.approx(0.50)


def test_a_response_without_cache_fields_reports_zeros():
    provider = _provider("claude-opus-5")
    provider._client = _RecordingClient([_FakeStream(final=_fake_final())])
    completion = provider.complete(CompletionRequest(model="claude-opus-5", messages=[]))
    assert completion.usage.cache_read_tokens == 0
    assert completion.usage.cache_creation_tokens == 0
    assert completion.usage.input_tokens == 1


# --------------------------------------------------------------------------- #
# max_tokens and the normalized stop_reason
# --------------------------------------------------------------------------- #


def test_request_max_tokens_is_honoured():
    provider = _provider("claude-opus-5")
    provider._client = client = _RecordingClient([_FakeStream()])
    list(
        provider.stream(
            CompletionRequest(model="claude-opus-5", messages=[], max_tokens=1234)
        )
    )
    assert client.calls[0]["max_tokens"] == 1234


def test_default_max_tokens_when_nobody_asked():
    # The Messages API requires max_tokens, so this adapter always sends a number. 8192
    # matches limits.max_output_tokens' own fallback.
    provider = _provider("claude-opus-5")
    provider._client = client = _RecordingClient([_FakeStream()])
    list(provider.stream(CompletionRequest(model="claude-opus-5", messages=[])))
    assert client.calls[0]["max_tokens"] == 8192


def test_provider_config_max_tokens_is_the_standing_preference():
    config = ProviderConfig()
    if not hasattr(config, "max_tokens"):
        pytest.skip("config.py has not grown ProviderConfig.max_tokens yet")
    config.max_tokens = 4096
    provider = _provider("claude-opus-5", config)
    provider._client = client = _RecordingClient([_FakeStream()])
    list(provider.stream(CompletionRequest(model="claude-opus-5", messages=[])))
    assert client.calls[0]["max_tokens"] == 4096
    # ...but the per-turn request still wins over it.
    provider._client = client = _RecordingClient([_FakeStream()])
    list(provider.stream(CompletionRequest(model="claude-opus-5", messages=[], max_tokens=77)))
    assert client.calls[0]["max_tokens"] == 77


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("end_turn", "end_turn"),
        ("tool_use", "tool_use"),
        ("max_tokens", "max_tokens"),
        ("stop_sequence", "stop_sequence"),
        ("pause_turn", "other"),
        ("refusal", "other"),
        (None, None),
    ],
)
def test_anthropic_stop_reason_normalization(raw, expected):
    assert anthropic_mod._normalize_stop_reason(raw) == expected


def test_stop_reason_reaches_the_completion():
    provider = _provider("claude-opus-5")
    provider._client = _RecordingClient(
        [_FakeStream(final=_fake_final(stop_reason="max_tokens"))]
    )
    completion = provider.complete(CompletionRequest(model="claude-opus-5", messages=[]))
    assert completion.stop_reason == "max_tokens"
