"""Ollama provider — local models via the /api/chat HTTP endpoint.

Supports native tool calling for models that advertise it (e.g. llama3.1, qwen2.5).
Local inference has no token cost, so usage carries token counts with cost 0.0.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from agent86.cognitive.base import ModelProvider, ProviderError
from agent86.config import ProviderConfig
from agent86.types import (
    Completion,
    CompletionDelta,
    CompletionRequest,
    Message,
    Role,
    ToolCall,
    ToolSpec,
    Usage,
)

_DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider(ModelProvider):
    name = "ollama"
    supports_native_tools = True  # depends on the model; tools are passed through

    def __init__(self, model: str, config: ProviderConfig):
        self.model = model
        self._base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")

    # ------------------------------------------------------------------ #
    # Conversion helpers
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
                out.append({"role": "tool", "content": m.content, "name": m.name})
                continue
            entry: dict[str, Any] = {"role": m.role.value, "content": m.content}
            if m.role == Role.ASSISTANT and m.tool_calls:
                entry["tool_calls"] = [
                    {"function": {"name": tc.name, "arguments": tc.arguments}}
                    for tc in m.tool_calls
                ]
            out.append(entry)
        return out

    # ------------------------------------------------------------------ #
    # Streaming
    # ------------------------------------------------------------------ #

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_messages(request.messages),
            "stream": True,
            "options": {"temperature": request.temperature},
        }
        if request.tools:
            payload["tools"] = self._to_tools(request.tools)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        prompt_tokens = 0
        eval_tokens = 0
        stop_reason: str | None = None

        try:
            with httpx.stream(
                "POST", f"{self._base_url}/api/chat", json=payload, timeout=None
            ) as resp:
                if resp.status_code != 200:
                    resp.read()
                    raise ProviderError(
                        f"Ollama returned HTTP {resp.status_code}: {resp.text.strip()}"
                    )
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise ProviderError(f"Ollama error: {chunk['error']}")
                    msg = chunk.get("message") or {}
                    piece = msg.get("content") or ""
                    if piece:
                        text_parts.append(piece)
                        yield CompletionDelta(text=piece)
                    for tc in msg.get("tool_calls") or []:
                        fn = tc.get("function") or {}
                        tool_calls.append(
                            ToolCall(
                                id=f"ollama-{len(tool_calls)}",
                                name=fn.get("name", ""),
                                arguments=_as_dict(fn.get("arguments")),
                            )
                        )
                    if chunk.get("done"):
                        prompt_tokens = chunk.get("prompt_eval_count", 0) or 0
                        eval_tokens = chunk.get("eval_count", 0) or 0
                        stop_reason = chunk.get("done_reason")
        except httpx.ConnectError as exc:
            raise ProviderError(
                f"Cannot reach Ollama at {self._base_url}. Is it running? "
                "Start it with 'ollama serve'."
            ) from exc

        completion = Completion(
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=Usage(input_tokens=prompt_tokens, output_tokens=eval_tokens, cost_usd=0.0),
            stop_reason=stop_reason,
            model=self.model,
        )
        yield CompletionDelta(done=True, completion=completion)


def _as_dict(arguments: Any) -> dict[str, Any]:
    """Ollama returns tool arguments as an object; tolerate a JSON string too."""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"value": arguments}
    return {}


__all__ = ["OllamaProvider"]
