"""OpenAI-compatible provider (Tier 3).

One httpx-based adapter for the OpenAI Chat Completions API and every service that speaks it:
OpenAI, Azure OpenAI, Together, Groq, OpenRouter, vLLM — and local servers (llama.cpp,
LM Studio, Ollama's ``/v1``). Streaming tool calls arrive as fragments across SSE chunks and
are accumulated by index into whole :class:`ToolCall` objects.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from agent86.cognitive.base import UNRESOLVED, ModelProvider, ProviderError
from agent86.cognitive.capabilities import apply_sampling_params
from agent86.cognitive.http_timeouts import stream_timeout, timeout_error
from agent86.cognitive.pricing import priced_usage
from agent86.cognitive.retry import RetryPolicy, max_retries_for, retry_after_header
from agent86.config import ProviderConfig
from agent86.types import (
    INVALID_TOOL_ARGS_KEY,
    Completion,
    CompletionDelta,
    CompletionRequest,
    Message,
    Role,
    StopReason,
    ToolCall,
    ToolSpec,
)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"

#: OpenAI renamed the output cap to `max_completion_tokens` and rejects the old `max_tokens`
#: on its reasoning models; most OpenAI-*compatible* endpoints (Groq, OpenRouter, vLLM,
#: llama.cpp) only know the old name. There is no way to tell from the base URL which dialect
#: an endpoint speaks, so the adapter sends the new name and learns from a 400 — the same
#: shape as capabilities.py's sampling-parameter fallback, but keyed by ENDPOINT rather than
#: model, because the name a server accepts is a property of the server.
_LEGACY_MAX_TOKENS_ENDPOINTS: set[str] = set()

#: Words a server uses when it refuses a parameter name outright.
_PARAM_REJECTION_WORDS: tuple[str, ...] = (
    "unsupported",
    "unrecognized",
    "unrecognised",
    "not supported",
    "unknown",
    "unexpected",
    "invalid",
    "extra field",
    "additional propert",
    "not permitted",
    "no longer",
    "deprecat",
)

#: OpenAI `finish_reason` -> the shared normalized vocabulary.
_STOP_REASONS: dict[str, str] = {
    "stop": StopReason.END_TURN.value,
    "tool_calls": StopReason.TOOL_USE.value,
    "function_call": StopReason.TOOL_USE.value,
    "length": StopReason.MAX_TOKENS.value,
    "max_tokens": StopReason.MAX_TOKENS.value,
    "content_filter": StopReason.OTHER.value,
}


def uses_legacy_max_tokens(url: str) -> bool:
    """True when ``url`` has already told us it only understands ``max_tokens``."""
    return url in _LEGACY_MAX_TOKENS_ENDPOINTS


def mark_legacy_max_tokens(url: str) -> None:
    """Record, for this session, that ``url`` rejected ``max_completion_tokens``."""
    _LEGACY_MAX_TOKENS_ENDPOINTS.add(url)


def is_max_tokens_rejection(body: str) -> bool:
    """True when an error body says ``max_completion_tokens`` is not a parameter it knows."""
    low = (body or "").lower()
    return "max_completion_tokens" in low and any(w in low for w in _PARAM_REJECTION_WORDS)


def normalize_stop_reason(raw: Any, *, has_tool_calls: bool = False) -> str | None:
    """Map an OpenAI ``finish_reason`` onto the shared :class:`StopReason` vocabulary.

    ``has_tool_calls`` covers the compatible servers (llama.cpp among them) that report a
    plain ``stop`` on a turn that did emit tool calls: the harness is about to run a tool,
    so calling that ``end_turn`` would be wrong.
    """
    if raw is None:
        return StopReason.TOOL_USE.value if has_tool_calls else None
    mapped = _STOP_REASONS.get(str(raw), StopReason.OTHER.value)
    if has_tool_calls and mapped == StopReason.END_TURN.value:
        return StopReason.TOOL_USE.value
    return mapped


class OpenAIProvider(ModelProvider):
    name = "openai"
    supports_native_tools = True

    def __init__(
        self,
        model: str,
        config: ProviderConfig,
        require_key: bool = True,
        api_key: Any = UNRESOLVED,
    ):
        self.model = model
        self._config = config
        base = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")
        # Tolerate a base_url given with or without the /v1 suffix.
        self._url = base + ("" if base.endswith("/v1") else "/v1") + "/chat/completions"
        self._timeout = stream_timeout(config)
        self._max_retries = max_retries_for(config)

        if api_key is UNRESOLVED:
            from agent86.secrets import resolve_api_key

            api_key = resolve_api_key(self.name, config.api_key_env)
        self._api_key = api_key or None
        if require_key and not self._api_key:
            env = config.api_key_env or "OPENAI_API_KEY"
            raise ProviderError(
                f"No API key found. Set the {env} environment variable "
                "or store a key in the OS keyring via /config model."
            )

    # ------------------------------------------------------------------ #
    # Request shaping
    # ------------------------------------------------------------------ #

    def _max_tokens(self, request: CompletionRequest) -> int | None:
        """The output cap for this call, or ``None`` to let the endpoint decide.

        The request wins (the loop derives it from ``limits.max_output_tokens``), then the
        provider config's standing preference. ``None`` deliberately sends no cap at all
        rather than inventing one: these adapters also front local servers, where a guessed
        ceiling would truncate a long generation that runs free today.
        """
        if request.max_tokens:
            return int(request.max_tokens)
        configured = self._config.max_tokens
        return int(configured) if configured else None

    # ------------------------------------------------------------------ #
    # Conversion
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    @staticmethod
    def _to_messages(messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == Role.TOOL:
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
            elif m.role == Role.ASSISTANT and m.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in m.tool_calls
                        ],
                    }
                )
            else:
                out.append({"role": m.role.value, "content": m.content})
        return out

    # ------------------------------------------------------------------ #
    # Streaming
    # ------------------------------------------------------------------ #

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_messages(request.messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        # Same seam as the Anthropic path (UAT gap 5). This is behaviour-identical for
        # OpenAI/Groq/OpenRouter today — no OpenAI-family model is in the removed-parameter
        # list — but a gateway proxying an Anthropic model through an OpenAI-compatible
        # endpoint gets the correct omission for free.
        apply_sampling_params(payload, self.model, temperature=request.temperature)
        max_tokens = self._max_tokens(request)
        if max_tokens:
            # New name first, unless this endpoint has already refused it this session.
            key = "max_tokens" if uses_legacy_max_tokens(self._url) else "max_completion_tokens"
            payload[key] = max_tokens
        if request.tools:
            payload["tools"] = self._to_tools(request.tools)
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        policy = RetryPolicy(self._max_retries, provider=self.name, model=self.model)
        # A plain `for attempt in policy.attempts()` cannot express the parameter-name swap:
        # that retry must not consume the transient-failure budget (it is a deterministic
        # correction, not a flaky endpoint), and it must still be available when retries are
        # configured off. The counter is advanced only where a retry was actually granted.
        attempt = 0
        swapped = False
        while True:
            # Per-attempt state: a retry must not inherit half a response from the last try.
            text_parts: list[str] = []
            tool_frags: dict[int, dict[str, str]] = {}
            prompt_tokens = 0
            completion_tokens = 0
            cached_tokens = 0
            finish_reason: str | None = None
            # Once a delta has reached the consumer, retrying would duplicate that text in
            # the transcript — so from here on a failure is surfaced, never retried.
            emitted = False

            try:
                with httpx.stream(
                    "POST", self._url, json=payload, headers=headers, timeout=self._timeout
                ) as resp:
                    if resp.status_code != 200:
                        resp.read()
                        if (
                            resp.status_code == 400
                            and not swapped
                            and "max_completion_tokens" in payload
                            and is_max_tokens_rejection(resp.text)
                        ):
                            # Self-correcting: this endpoint speaks the older dialect. Retry
                            # once under the old name and remember it for the rest of the
                            # session, so only the first call of a run pays for the probe.
                            swapped = True
                            mark_legacy_max_tokens(self._url)
                            payload["max_tokens"] = payload.pop("max_completion_tokens")
                            continue
                        if policy.retry_status(
                            resp.status_code, attempt, retry_after=retry_after_header(resp)
                        ):
                            attempt += 1
                            continue
                        raise ProviderError(f"HTTP {resp.status_code}: {resp.text.strip()[:400]}")
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        if usage := chunk.get("usage"):
                            prompt_tokens = (
                                usage.get("prompt_tokens", prompt_tokens) or prompt_tokens
                            )
                            completion_tokens = (
                                usage.get("completion_tokens", completion_tokens)
                                or completion_tokens
                            )
                            # OpenAI reports the cached slice of the prompt here. It is a
                            # SUBSET of prompt_tokens (unlike Anthropic, which reports the
                            # uncached remainder), which is the convention Usage follows.
                            details = usage.get("prompt_tokens_details") or {}
                            if isinstance(details, dict):
                                cached_tokens = (
                                    details.get("cached_tokens", cached_tokens) or cached_tokens
                                )
                        for choice in chunk.get("choices", []):
                            delta = choice.get("delta", {})
                            piece = delta.get("content")
                            if piece:
                                text_parts.append(piece)
                                emitted = True
                                yield CompletionDelta(text=piece)
                            for frag in delta.get("tool_calls", []) or []:
                                self._accumulate(tool_frags, frag)
                            if choice.get("finish_reason"):
                                finish_reason = choice["finish_reason"]
            except httpx.ConnectError as exc:
                if policy.retry_exception(exc, attempt, emitted=emitted):
                    attempt += 1
                    continue
                raise ProviderError(f"Cannot reach {self._url}: {exc}") from exc
            except httpx.TimeoutException as exc:
                if policy.retry_exception(exc, attempt, emitted=emitted):
                    attempt += 1
                    continue
                raise timeout_error(
                    exc,
                    endpoint=self._url,
                    timeout=self._timeout,
                    section=None,
                ) from exc
            except json.JSONDecodeError as exc:
                # A truncated or non-SSE line. Left raw, this surfaced to the loop as a bare
                # JSONDecodeError with no hint about which endpoint produced it.
                raise ProviderError(
                    f"{self.name}: {self._url} returned a malformed streaming chunk for model "
                    f"{self.model!r} — could not parse the SSE 'data:' line as JSON ({exc}). "
                    "The stream was probably truncated, or the endpoint is not OpenAI-compatible."
                ) from exc
            except httpx.HTTPError as exc:
                # RemoteProtocolError / ReadError / anything else transport-level: the
                # connection died part-way through the response.
                if policy.retry_exception(exc, attempt, emitted=emitted):
                    attempt += 1
                    continue
                raise ProviderError(
                    f"{self.name}: the connection to {self._url} failed while streaming model "
                    f"{self.model!r} — {type(exc).__name__}: {exc}. The server closed the stream "
                    "early; retry, or check the endpoint and network."
                ) from exc

            tool_calls = self._assemble(tool_frags)
            yield CompletionDelta(
                done=True,
                completion=Completion(
                    text="".join(text_parts),
                    tool_calls=tool_calls,
                    usage=priced_usage(
                        self.model,
                        prompt_tokens,
                        completion_tokens,
                        cache_read_tokens=cached_tokens,
                    ),
                    stop_reason=normalize_stop_reason(
                        finish_reason, has_tool_calls=bool(tool_calls)
                    ),
                    model=self.model,
                ),
            )
            return

    @staticmethod
    def _accumulate(frags: dict[int, dict[str, str]], frag: dict[str, Any]) -> None:
        idx = frag.get("index", 0)
        slot = frags.setdefault(idx, {"id": "", "name": "", "args": ""})
        if frag.get("id"):
            slot["id"] = frag["id"]
        fn = frag.get("function") or {}
        if fn.get("name"):
            slot["name"] = fn["name"]
        if fn.get("arguments"):
            slot["args"] += fn["arguments"]

    @staticmethod
    def _assemble(frags: dict[int, dict[str, str]]) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for idx in sorted(frags):
            slot = frags[idx]
            if not slot["name"]:
                continue
            try:
                args = json.loads(slot["args"]) if slot["args"].strip() else {}
            except json.JSONDecodeError:
                # Carry the raw text instead of {}: an empty object makes the schema
                # validator report a missing required field, sending the model to fix an
                # argument when the actual bug is its own JSON. The loop intercepts this.
                args = {INVALID_TOOL_ARGS_KEY: slot["args"]}
            if not isinstance(args, dict):  # a bare string / array / number is not arguments
                args = {INVALID_TOOL_ARGS_KEY: slot["args"]}
            calls.append(
                ToolCall(id=slot["id"] or f"call_{idx}", name=slot["name"], arguments=args)
            )
        return calls


__all__ = [
    "OpenAIProvider",
    "is_max_tokens_rejection",
    "mark_legacy_max_tokens",
    "normalize_stop_reason",
    "uses_legacy_max_tokens",
]
