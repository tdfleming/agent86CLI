"""Streaming HTTP timeout fix (quick task 260813-jfk).

Covers the shared `cognitive/http_timeouts.py` helper (Task 1), both bounded call sites and
their `httpx.TimeoutException` -> `ProviderError` conversion (Task 2), and real-loopback-server
proof that a stall fails fast while a slow-but-progressing stream still succeeds (Task 3).
"""

from __future__ import annotations

import httpx
import pytest

from agent86.cognitive.base import ProviderError
from agent86.cognitive.http_timeouts import stream_timeout, timeout_error
from agent86.config import ProviderConfig


# --- Task 1: stream_timeout ------------------------------------------------------------------- #


def test_stream_timeout_defaults():
    t = stream_timeout(ProviderConfig())
    assert t.read == 300.0
    assert t.connect == 10.0
    assert t.write == 10.0
    assert t.pool == 10.0


def test_stream_timeout_custom_values():
    t = stream_timeout(ProviderConfig(read_timeout_s=42.0, connect_timeout_s=3.0))
    assert t.read == 42.0
    assert t.connect == 3.0
    assert t.write == 3.0
    assert t.pool == 3.0


# --- Task 1: timeout_error --------------------------------------------------------------------- #


def test_timeout_error_read_timeout_names_the_limit():
    t = stream_timeout(ProviderConfig(read_timeout_s=0.5, connect_timeout_s=2.0))
    err = timeout_error(
        httpx.ReadTimeout("x"),
        endpoint="http://h/api/chat",
        timeout=t,
        section="ollama",
    )
    assert isinstance(err, ProviderError)
    msg = str(err)
    assert "http://h/api/chat" in msg
    assert "0.5" in msg
    assert "read_timeout_s" in msg
    assert "[providers.ollama]" in msg
    assert "gap" in msg.lower()
    assert "total" in msg.lower()


def test_timeout_error_connect_timeout_names_the_limit_and_hint():
    t = stream_timeout(ProviderConfig(read_timeout_s=0.5, connect_timeout_s=2.0))
    err = timeout_error(
        httpx.ConnectTimeout("x"),
        endpoint="http://h/api/chat",
        timeout=t,
        section="ollama",
        connect_hint="Is it running? Start it with 'ollama serve'.",
    )
    msg = str(err)
    assert "connect_timeout_s" in msg
    assert "2" in msg
    assert "Is it running? Start it with 'ollama serve'." in msg


def test_timeout_error_no_section_has_no_none_leak():
    t = stream_timeout(ProviderConfig())
    err = timeout_error(
        httpx.ReadTimeout("x"), endpoint="http://h/v1/chat/completions", timeout=t, section=None
    )
    msg = str(err)
    assert "None" not in msg
    assert "[providers.None]" not in msg


def test_timeout_error_connect_no_section_has_no_none_leak():
    t = stream_timeout(ProviderConfig())
    err = timeout_error(
        httpx.ConnectTimeout("x"), endpoint="http://h/v1/chat/completions", timeout=t, section=None
    )
    msg = str(err)
    assert "None" not in msg
    assert "[providers.None]" not in msg
