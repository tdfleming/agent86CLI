"""Anthropic (Claude) provider — Messages API with native tool use and streaming."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

from agent86.cognitive.base import ModelProvider, ProviderError
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


class AnthropicProvider(ModelProvider):
    name = "anthropic"
    supports_native_tools = True

    def __init__(self, model: str, config: ProviderConfig):
        self.model = model
        self._config = config
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ProviderError(
                "The 'anthropic' package is not installed. Install it with:\n"
                '    pip install "agent86[anthropic]"'
            ) from exc

        key_env = config.api_key_env or "ANTHROPIC_API_KEY"
        api_key = os.getenv(key_env)
        if not api_key:
            raise ProviderError(
                f"No Anthropic API key found. Set the {key_env} environment variable."
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
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_tokens or _DEFAULT_MAX_TOKENS,
            "temperature": request.temperature,
        }
        if system:
            kwargs["system"] = system
        if request.tools:
            kwargs["tools"] = self._to_tools(request.tools)

        try:
            with self._client.messages.stream(**kwargs) as stream:
                for text in stream.text_stream:
                    if text:
                        yield CompletionDelta(text=text)
                final = stream.get_final_message()
        except anthropic.APIError as exc:
            raise ProviderError(f"Anthropic API error: {exc}") from exc

        yield CompletionDelta(done=True, completion=self._final(final))

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
