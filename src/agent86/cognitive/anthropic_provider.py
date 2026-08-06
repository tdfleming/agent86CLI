"""Anthropic (Claude) provider — Messages API with native tool use and streaming."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from agent86.cognitive.base import UNRESOLVED, ModelProvider, ProviderError
from agent86.cognitive.capabilities import (
    apply_sampling_params,
    is_sampling_rejection,
    mark_sampling_unsupported,
)
from agent86.cognitive.pricing import priced_usage
from agent86.config import ProviderConfig
from agent86.types import (
    Completion,
    CompletionDelta,
    CompletionRequest,
    Message,
    Role,
    ToolCall,
    ToolSpec,
)

_DEFAULT_MAX_TOKENS = 4096

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
            "max_tokens": request.max_tokens or _DEFAULT_MAX_TOKENS,
        }
        if system:
            base_kwargs["system"] = system
        if request.tools:
            base_kwargs["tools"] = self._to_tools(request.tools)

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
        usage = priced_usage(
            self.model,
            input_tokens=getattr(message.usage, "input_tokens", 0),
            output_tokens=getattr(message.usage, "output_tokens", 0),
        )
        return Completion(
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=message.stop_reason,
            model=self.model,
        )


__all__ = ["AnthropicProvider"]
