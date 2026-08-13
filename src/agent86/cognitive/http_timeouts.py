"""Shared streaming HTTP timeout helper (Tier 3).

``httpx.stream(..., timeout=None)`` means "no timeout at all" — a server that accepts a
connection and then stops sending blocks the caller's ``recv()`` forever, with nothing to wake
it. That is exactly what caused a real 20+ minute hang: Ollama's keep-alive expired and its
``llama-server`` runner wedged mid-teardown without closing the socket.

This module is the single place that turns a :class:`~agent86.config.ProviderConfig` into a
split :class:`httpx.Timeout` and turns an :class:`httpx.TimeoutException` into an actionable
:class:`~agent86.cognitive.base.ProviderError`, so both streaming providers (Ollama,
OpenAI-compatible) cannot drift and the message logic is unit-testable in isolation.

The critical semantic: ``read`` is the maximum GAP between received chunks, not a total-request
deadline. A long-but-progressing generation is never penalised by it; only a genuinely stalled
socket dies.
"""

from __future__ import annotations

import httpx

from agent86.cognitive.base import ProviderError
from agent86.config import ProviderConfig


def stream_timeout(config: ProviderConfig) -> httpx.Timeout:
    """Split timeout for a streaming request. Never a scalar, never None."""
    return httpx.Timeout(
        connect=config.connect_timeout_s,
        read=config.read_timeout_s,
        write=config.connect_timeout_s,
        pool=config.connect_timeout_s,
    )


def timeout_error(
    exc: httpx.TimeoutException,
    *,
    endpoint: str,
    timeout: httpx.Timeout,
    section: str | None = None,
    connect_hint: str = "",
) -> ProviderError:
    """Convert an httpx timeout into a ProviderError naming the limit that fired."""
    location = f"[providers.{section}]" if section else "the [providers.*] block for this endpoint"

    if isinstance(exc, httpx.ConnectTimeout):
        message = (
            f"Timed out connecting to {endpoint} after {timeout.connect:g}s "
            f"(connect_timeout_s). "
        )
        if connect_hint:
            message += f"{connect_hint} "
        message += f"Raise connect_timeout_s in {location} to allow more time."
        return ProviderError(message)

    message = (
        f"Timed out waiting for {endpoint} after {timeout.read:g}s with no data received "
        f"(read_timeout_s). This is the maximum gap between streamed chunks, not the total "
        f"generation time — a long but still-progressing generation is not affected. "
        f"Raise read_timeout_s in {location} if this endpoint is just slow to respond."
    )
    return ProviderError(message)


__all__ = ["stream_timeout", "timeout_error"]
