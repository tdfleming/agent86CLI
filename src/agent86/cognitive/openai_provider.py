"""OpenAI-compatible provider (Tier 3).

One httpx-based adapter for the OpenAI Chat Completions API and every service that speaks it:
OpenAI, Azure OpenAI, Together, Groq, OpenRouter, vLLM — and local servers (llama.cpp,
LM Studio, Ollama's ``/v1``). Streaming tool calls arrive as fragments across SSE chunks and
are accumulated by index into whole :class:`ToolCall` objects.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import httpx

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

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(ModelProvider):
    name = "openai"
    supports_native_tools = True

    def __init__(self, model: str, config: ProviderConfig, require_key: bool = True):
        self.model = model
        base = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")
        # Tolerate a base_url given with or without the /v1 suffix.
        self._url = base + ("" if base.endswith("/v1") else "/v1") + "/chat/completions"

        self._api_key = os.getenv(config.api_key_env) if config.api_key_env else None
        if require_key and not self._api_key:
            env = config.api_key_env or "OPENAI_API_KEY"
            raise ProviderError(f"No API key found. Set the {env} environment variable.")

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
            "temperature": request.temperature,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        if request.tools:
            payload["tools"] = self._to_tools(request.tools)
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        text_parts: list[str] = []
        tool_frags: dict[int, dict[str, str]] = {}
        prompt_tokens = 0
        completion_tokens = 0
        finish_reason: str | None = None

        try:
            with httpx.stream(
                "POST", self._url, json=payload, headers=headers, timeout=None
            ) as resp:
                if resp.status_code != 200:
                    resp.read()
                    raise ProviderError(f"HTTP {resp.status_code}: {resp.text.strip()[:400]}")
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if usage := chunk.get("usage"):
                        prompt_tokens = usage.get("prompt_tokens", prompt_tokens) or prompt_tokens
                        completion_tokens = (
                            usage.get("completion_tokens", completion_tokens) or completion_tokens
                        )
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {})
                        piece = delta.get("content")
                        if piece:
                            text_parts.append(piece)
                            yield CompletionDelta(text=piece)
                        for frag in delta.get("tool_calls", []) or []:
                            self._accumulate(tool_frags, frag)
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
        except httpx.ConnectError as exc:
            raise ProviderError(f"Cannot reach {self._url}: {exc}") from exc

        yield CompletionDelta(
            done=True,
            completion=Completion(
                text="".join(text_parts),
                tool_calls=self._assemble(tool_frags),
                usage=priced_usage(self.model, prompt_tokens, completion_tokens),
                stop_reason=finish_reason,
                model=self.model,
            ),
        )

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
                args = {}
            calls.append(
                ToolCall(id=slot["id"] or f"call_{idx}", name=slot["name"], arguments=args)
            )
        return calls


__all__ = ["OpenAIProvider"]
