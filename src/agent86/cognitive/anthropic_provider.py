"""Anthropic (Claude) provider — Messages API with native tool use and streaming."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from agent86.cognitive.base import UNRESOLVED, ModelProvider, ProviderError
from agent86.cognitive.capabilities import (
    apply_sampling_params,
    is_sampling_rejection,
    mark_sampling_unsupported,
)
from agent86.cognitive.pricing import priced_usage
from agent86.cognitive.retry import max_retries_for
from agent86.config import ProviderConfig
from agent86.types import (
    Completion,
    CompletionDelta,
    CompletionRequest,
    Message,
    Role,
    StopReason,
    ToolCall,
    ToolSpec,
)

#: Used when neither the request nor the provider config names an output cap. The Messages
#: API *requires* max_tokens, so unlike the OpenAI-compatible adapters this one always sends
#: a number. 8192 matches `limits.max_output_tokens`'s own fallback, so the floor is the same
#: whichever layer ends up supplying it.
_DEFAULT_MAX_TOKENS = 8192

#: Minimum cacheable prefix, in tokens, per model family (claude-api skill, cached 2026-06-24).
#: A `cache_control` marker on a shorter prefix is not an error — it is silently ignored and
#: `cache_creation_input_tokens` comes back 0 — so marking below the floor buys nothing and
#: spends one of the four breakpoints. The floor is NOT monotonic across generations: 512 on
#: the newest models but 4096 on Opus 4.6/4.5 and Haiku 4.5, so it is matched by prefix.
_CACHE_MINIMUM_TOKENS: tuple[tuple[str, int], ...] = (
    ("claude-opus-5", 512),
    ("claude-fable-5-1", 512),
    ("claude-mythos-5-1", 512),
    ("claude-fable-5", 512),
    ("claude-mythos-5", 512),
    ("claude-opus-4-8", 1024),
    ("claude-sonnet-5", 1024),
    ("claude-sonnet-4-6", 1024),
    ("claude-sonnet-4-5", 1024),
    ("claude-sonnet-4", 1024),
    ("claude-opus-4-1", 1024),
    ("claude-opus-4", 1024),
    ("claude-opus-4-7", 2048),
    ("claude-haiku-3-5", 2048),
    ("claude-opus-4-6", 4096),
    ("claude-opus-4-5", 4096),
    ("claude-haiku-4-5", 4096),
)

#: Conservative floor for a model this table does not know. Over-estimating the minimum only
#: skips a marker that might have cached; under-estimating spends a breakpoint for nothing.
_CACHE_MINIMUM_FALLBACK = 4096

#: Anthropic stop reasons that already match the normalized vocabulary pass straight through;
#: anything else (`pause_turn`, `refusal`, a value added after this was written) is `other`.
_STOP_REASONS: dict[str, str] = {
    "end_turn": StopReason.END_TURN.value,
    "tool_use": StopReason.TOOL_USE.value,
    "max_tokens": StopReason.MAX_TOKENS.value,
    "stop_sequence": StopReason.STOP_SEQUENCE.value,
}


def _cache_minimum_tokens(model: str) -> int:
    """The minimum cacheable prefix length for ``model``, longest-prefix match."""
    ident = model.split(":", 1)[-1].strip().lower()
    best: tuple[int, int] | None = None
    for family, minimum in _CACHE_MINIMUM_TOKENS:
        if ident.startswith(family) and (best is None or len(family) > best[0]):
            best = (len(family), minimum)
    return best[1] if best else _CACHE_MINIMUM_FALLBACK


def _normalize_stop_reason(raw: Any) -> str | None:
    """Map an Anthropic ``stop_reason`` onto the shared :class:`StopReason` vocabulary."""
    if raw is None:
        return None
    return _STOP_REASONS.get(str(raw), StopReason.OTHER.value)


def _approx_tokens(text: str) -> int:
    """Rough token count for a cacheability decision (~4 characters per token).

    Deliberately an estimate: asking the token-counting endpoint would add a network round
    trip to every turn to decide something whose only cost when wrong is a marker the API
    ignores. The estimate is only ever compared against the minimum-prefix floor.
    """
    return len(text) // 4

#: Must match the floor declared in pyproject.toml's `anthropic` extra. Versions below 0.28
#: pass `proxies=` to httpx.Client, which httpx removed in 0.28 — the failure surfaces as an
#: opaque TypeError from inside httpx rather than anything actionable (UAT gap 3).
_MIN_ANTHROPIC_VERSION: tuple[int, ...] = (0, 40)


def _version_tuple(raw: str) -> tuple[int, ...]:
    """Leading numeric components of a version string; stops at the first non-numeric part."""
    parts: list[int] = []
    for chunk in raw.split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


class AnthropicProvider(ModelProvider):
    name = "anthropic"
    supports_native_tools = True

    def __init__(self, model: str, config: ProviderConfig, api_key: Any = UNRESOLVED):
        self.model = model
        self._config = config
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ProviderError(
                "The 'anthropic' package is not installed. Install it with:\n"
                '    pip install "agent86[anthropic]"'
            ) from exc

        installed = getattr(anthropic, "__version__", None)
        if installed:
            found = _version_tuple(installed)
            # An unparseable version is not a reason to refuse to run.
            if found and found < _MIN_ANTHROPIC_VERSION:
                minimum = ".".join(str(n) for n in _MIN_ANTHROPIC_VERSION)
                raise ProviderError(
                    f"The installed 'anthropic' package is {installed}, which is too old for "
                    f"agent86 (needs >= {minimum}). Versions below 0.28 pass a 'proxies=' "
                    "argument that httpx 0.28+ removed, which fails with an opaque TypeError. "
                    "Upgrade it with:\n"
                    '    pip install -U "anthropic>=0.40"\n'
                    "If the old version is held by another package sharing this environment "
                    "(e.g. 'anthropic-tools'), install agent86 into its own virtualenv."
                )

        key_env = config.api_key_env or "ANTHROPIC_API_KEY"
        if api_key is UNRESOLVED:
            from agent86.secrets import resolve_api_key

            api_key = resolve_api_key("anthropic", key_env)
        if not api_key:
            raise ProviderError(
                f"No Anthropic API key found. Set the {key_env} environment variable "
                "or store a key in the OS keyring via /config model."
            )
        kwargs: dict[str, Any] = {"api_key": api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        # The SDK has its own retry layer (429/5xx, Retry-After aware), so this provider
        # configures it rather than using cognitive/retry.py — wrapping a client that already
        # retries would multiply the budget (max_retries * our attempts) behind the user's back.
        kwargs["max_retries"] = max_retries_for(config)
        # D-3: deliberately NOT wiring read_timeout_s/connect_timeout_s here. The SDK applies
        # its own ~600s default, so this path cannot hang unbounded (the bug class this quick
        # task closes doesn't exist for Anthropic). The SDK's timeout= is a total-request
        # budget with its own retry layer, a different meaning than our "max inter-chunk gap" —
        # passing our value would silently change semantics and could kill a legitimate long
        # generation, the exact failure our split timeout exists to prevent. No behaviour change.
        self._client = anthropic.Anthropic(**kwargs)

    # ------------------------------------------------------------------ #
    # Conversion helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]

    # ------------------------------------------------------------------ #
    # Request shaping
    # ------------------------------------------------------------------ #

    def _max_tokens(self, request: CompletionRequest) -> int:
        """The output cap for this call: request, then provider config, then the floor.

        The request wins because it is the per-turn decision (the loop derives it from
        ``limits.max_output_tokens``); the provider config is the standing preference for
        this endpoint.
        """
        if request.max_tokens:
            return int(request.max_tokens)
        if self._config.max_tokens:
            return int(self._config.max_tokens)
        return _DEFAULT_MAX_TOKENS

    @property
    def _prompt_cache_enabled(self) -> bool:
        """``prompt_cache`` from THIS provider's config section (on by default)."""
        return self._config.prompt_cache

    def _apply_prompt_cache(
        self, kwargs: dict[str, Any], system: str | None, tools: list[dict[str, Any]]
    ) -> None:
        """Mark the stable prefix — tool definitions, then the system prompt — as cacheable.

        The API renders ``tools`` -> ``system`` -> ``messages`` and caching is a *prefix*
        match, so a marker on the LAST tool caches the whole tool list, and a marker on the
        system block caches tools + system. Both are stable across a session while the
        conversation after them is not, which is exactly the split caching pays for.

        Each marker is placed only when the prefix it closes is long enough to actually
        cache (see :data:`_CACHE_MINIMUM_TOKENS`); two of the four breakpoints are used at
        most, leaving room for callers that mark message content.
        """
        minimum = _cache_minimum_tokens(self.model)
        # The tool list is rendered as JSON, so its serialized length is what the model reads.
        tools_tokens = _approx_tokens(json.dumps(tools)) if tools else 0
        if tools and tools_tokens >= minimum:
            # Mutating the last tool dict is safe: _to_tools built these for this request.
            tools[-1]["cache_control"] = {"type": "ephemeral"}

        if not system:
            return
        # The system block closes the tools+system prefix, so both count toward the floor.
        if tools_tokens + _approx_tokens(system) < minimum:
            return
        kwargs["system"] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]

    @staticmethod
    def _to_messages(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
        """Split out the system prompt and convert the rest to Anthropic format."""
        system: str | None = None
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == Role.SYSTEM:
                system = m.content
                continue
            if m.role == Role.TOOL:
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id,
                                "content": m.content,
                            }
                        ],
                    }
                )
                continue
            if m.role == Role.ASSISTANT and m.tool_calls:
                content: list[dict[str, Any]] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    content.append(
                        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                    )
                out.append({"role": "assistant", "content": content})
                continue
            out.append({"role": m.role.value, "content": m.content})
        return system, out

    # ------------------------------------------------------------------ #
    # Streaming
    # ------------------------------------------------------------------ #

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        import anthropic

        system, messages = self._to_messages(request.messages)
        base_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self._max_tokens(request),
        }
        if system:
            base_kwargs["system"] = system
        tools = self._to_tools(request.tools) if request.tools else []
        if tools:
            base_kwargs["tools"] = tools
        if self._prompt_cache_enabled:
            self._apply_prompt_cache(base_kwargs, system, tools)

        # temperature/top_p/top_k were REMOVED on Opus 5, Opus 4.8, Opus 4.7, Sonnet 5 and
        # Fable 5 — sending any of them is a 400 with no replacement value, so they must be
        # omitted entirely (UAT gap 5). The gate is on the model, never on the value:
        # CompletionRequest.temperature defaults to 0.0, which is a real value everywhere else.
        kwargs = apply_sampling_params(
            dict(base_kwargs), self.model, temperature=request.temperature
        )

        for attempt in (0, 1):
            emitted = False
            try:
                with self._client.messages.stream(**kwargs) as stream:
                    for text in stream.text_stream:
                        if text:
                            emitted = True
                            yield CompletionDelta(text=text)
                    final = stream.get_final_message()
            except anthropic.APIError as exc:
                # Self-correcting fallback: a model released after capabilities.py was written
                # tells us itself. Only safe before any text has been emitted.
                if attempt == 0 and not emitted and is_sampling_rejection(str(exc)):
                    mark_sampling_unsupported(self.model)
                    kwargs = dict(base_kwargs)
                    continue
                raise ProviderError(f"Anthropic API error: {exc}") from exc
            yield CompletionDelta(done=True, completion=self._final(final))
            return

    def _final(self, message: Any) -> Completion:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {}))
                )
        raw_usage = getattr(message, "usage", None)
        cache_read = int(getattr(raw_usage, "cache_read_input_tokens", 0) or 0)
        cache_creation = int(getattr(raw_usage, "cache_creation_input_tokens", 0) or 0)
        # Anthropic reports `input_tokens` as the *uncached* remainder, with the cached
        # portions counted separately. The harness's contract is that `Usage.input_tokens`
        # is the whole prompt and the cache fields are a breakdown of it — otherwise a
        # well-cached turn would look like it barely used any context. Normalise here, and
        # let pricing.py subtract the breakdown back out to bill each part at its own rate.
        uncached = int(getattr(raw_usage, "input_tokens", 0) or 0)
        usage = priced_usage(
            self.model,
            input_tokens=uncached + cache_read + cache_creation,
            output_tokens=int(getattr(raw_usage, "output_tokens", 0) or 0),
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
        )
        return Completion(
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=_normalize_stop_reason(getattr(message, "stop_reason", None)),
            model=self.model,
        )


__all__ = ["AnthropicProvider"]
