"""Streaming HTTP timeout fix (quick task 260813-jfk).

Covers the shared `cognitive/http_timeouts.py` helper (Task 1), both bounded call sites and
their `httpx.TimeoutException` -> `ProviderError` conversion (Task 2), and real-loopback-server
proof that a stall fails fast while a slow-but-progressing stream still succeeds (Task 3).
"""

from __future__ import annotations

import concurrent.futures
import http.server
import json
import threading
import time

import httpx
import pytest

from agent86.cognitive import ollama_provider as ollama_mod
from agent86.cognitive import openai_provider as openai_mod
from agent86.cognitive.base import ProviderError
from agent86.cognitive.http_timeouts import stream_timeout, timeout_error
from agent86.cognitive.llamacpp_provider import LlamaCppProvider
from agent86.cognitive.ollama_provider import OllamaProvider
from agent86.cognitive.openai_provider import OpenAIProvider
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


# --- Task 2: both call sites are bounded, never timeout=None ----------------------------------- #


def _ndjson_ok_lines():
    return [
        json.dumps(
            {
                "message": {"content": "hi"},
                "done": True,
                "prompt_eval_count": 3,
                "eval_count": 1,
                "done_reason": "stop",
            }
        )
    ]


class _FakeStreamCM:
    """Minimal `with httpx.stream(...) as resp:` fake. Either yields NDJSON/SSE lines or raises."""

    def __init__(self, lines=None, status_code=200, raise_exc=None):
        self._lines = lines or []
        self.status_code = status_code
        self.text = ""
        self._raise_exc = raise_exc

    def __enter__(self):
        if self._raise_exc is not None:
            raise self._raise_exc
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        pass

    def iter_lines(self):
        yield from self._lines


def _patch_capture(monkeypatch, mod, lines=None, raise_exc=None):
    captured: dict = {}

    def fake_stream(*args, **kwargs):
        captured.update(kwargs)
        return _FakeStreamCM(lines=lines, raise_exc=raise_exc)

    monkeypatch.setattr(mod.httpx, "stream", fake_stream)
    return captured


def test_ollama_passes_default_timeout_never_none(monkeypatch):
    captured = _patch_capture(monkeypatch, ollama_mod, lines=_ndjson_ok_lines())
    provider = OllamaProvider("m", ProviderConfig())
    provider.complete(_req())
    t = captured["timeout"]
    assert t is not None
    assert t.read == 300.0
    assert t.connect == 10.0


def test_ollama_passes_overridden_timeout(monkeypatch):
    captured = _patch_capture(monkeypatch, ollama_mod, lines=_ndjson_ok_lines())
    provider = OllamaProvider("m", ProviderConfig(read_timeout_s=900.0, connect_timeout_s=3.0))
    provider.complete(_req())
    t = captured["timeout"]
    assert t.read == 900.0
    assert t.connect == 3.0


def _sse_ok_lines():
    return [
        "data: " + json.dumps({"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}),
        "data: [DONE]",
    ]


def test_openai_passes_default_timeout_never_none(monkeypatch):
    captured = _patch_capture(monkeypatch, openai_mod, lines=_sse_ok_lines())
    provider = OpenAIProvider("m", ProviderConfig(base_url="http://local/v1"), require_key=False)
    provider.complete(_req())
    t = captured["timeout"]
    assert t is not None
    assert t.read == 300.0
    assert t.connect == 10.0


def test_openai_passes_overridden_timeout(monkeypatch):
    captured = _patch_capture(monkeypatch, openai_mod, lines=_sse_ok_lines())
    provider = OpenAIProvider(
        "m",
        ProviderConfig(base_url="http://local/v1", read_timeout_s=900.0, connect_timeout_s=3.0),
        require_key=False,
    )
    provider.complete(_req())
    t = captured["timeout"]
    assert t.read == 900.0
    assert t.connect == 3.0


def test_llamacpp_preserves_timeout_fields_with_no_base_url(monkeypatch):
    captured = _patch_capture(monkeypatch, openai_mod, lines=_sse_ok_lines())
    provider = LlamaCppProvider("m", ProviderConfig(read_timeout_s=900.0))
    provider.complete(_req())
    t = captured["timeout"]
    assert t.read == 900.0


def _req():
    from agent86.types import CompletionRequest, Message, Role

    return CompletionRequest(model="m", messages=[Message(role=Role.USER, content="hi")])


# --- Task 2: httpx.TimeoutException -> ProviderError -------------------------------------------- #


def test_ollama_read_timeout_surfaces_as_provider_error(monkeypatch):
    _patch_capture(monkeypatch, ollama_mod, raise_exc=httpx.ReadTimeout("stalled"))
    provider = OllamaProvider("m", ProviderConfig(read_timeout_s=0.5))
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(_req())
    msg = str(exc_info.value)
    assert "read_timeout_s" in msg
    assert "0.5" in msg


def test_ollama_connect_timeout_surfaces_as_provider_error(monkeypatch):
    _patch_capture(monkeypatch, ollama_mod, raise_exc=httpx.ConnectTimeout("no route"))
    provider = OllamaProvider("m", ProviderConfig())
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(_req())
    msg = str(exc_info.value)
    assert "connect_timeout_s" in msg
    assert "Start it with 'ollama serve'" in msg


def test_ollama_connect_error_message_unchanged(monkeypatch):
    _patch_capture(monkeypatch, ollama_mod, raise_exc=httpx.ConnectError("refused"))
    provider = OllamaProvider("m", ProviderConfig(base_url="http://x"))
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(_req())
    assert str(exc_info.value) == (
        "Cannot reach Ollama at http://x. Is it running? Start it with 'ollama serve'."
    )


def test_openai_read_timeout_surfaces_as_provider_error(monkeypatch):
    _patch_capture(monkeypatch, openai_mod, raise_exc=httpx.ReadTimeout("stalled"))
    provider = OpenAIProvider(
        "m", ProviderConfig(base_url="http://local/v1", read_timeout_s=0.5), require_key=False
    )
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(_req())
    msg = str(exc_info.value)
    assert "read_timeout_s" in msg
    assert "0.5" in msg


def test_openai_connect_timeout_surfaces_as_provider_error(monkeypatch):
    _patch_capture(monkeypatch, openai_mod, raise_exc=httpx.ConnectTimeout("no route"))
    provider = OpenAIProvider(
        "m", ProviderConfig(base_url="http://local/v1"), require_key=False
    )
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(_req())
    msg = str(exc_info.value)
    assert "connect_timeout_s" in msg


def test_openai_connect_error_message_startswith(monkeypatch):
    _patch_capture(monkeypatch, openai_mod, raise_exc=httpx.ConnectError("refused"))
    provider = OpenAIProvider(
        "m", ProviderConfig(base_url="http://local/v1"), require_key=False
    )
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(_req())
    assert str(exc_info.value).startswith("Cannot reach http://local/v1/chat/completions")


# --- Task 3: real loopback server -- stall fails, slow-but-progressing succeeds ----------------- #
#
# The D-1 guarantee (a stalled socket dies, a slow-but-progressing one doesn't) is a property of
# REAL httpx, so it cannot be proved by the hand-rolled fakes above -- that would be circular.
# These tests drive both providers against a real HTTP/1.0, connection-close-delimited loopback
# server, which lets us dribble chunks out without hand-rolling chunked transfer encoding.


class _ServerState:
    def __init__(self) -> None:
        self.mode = "stall"  # "stall" | "slow_drip"
        self.pieces: list[str] = []
        self.gap = 0.0
        # Set only in fixture teardown -- lets a "stall" handler thread unblock and exit instead
        # of leaking a thread that waits on the socket forever.
        self.release_event = threading.Event()


def _handler_factory(state: _ServerState) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        # HTTP/1.0 (the class default) delimits the body by connection close rather than
        # Content-Length, which is what lets us dribble chunks out with plain writes.
        protocol_version = "HTTP/1.0"

        def log_message(self, *_args: object) -> None:
            pass  # keep suite output clean

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's naming convention
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length:
                self.rfile.read(length)  # drain the request body or the client can block on write

            is_ollama = self.path == "/api/chat"
            self.send_response(200)
            self.send_header(
                "Content-Type", "application/x-ndjson" if is_ollama else "text/event-stream"
            )
            self.end_headers()
            try:
                self.wfile.flush()
            except OSError:
                return

            if state.mode == "stall":
                # Headers arrived (httpx.stream's `with` block is entered) and then not one
                # further byte ever comes -- the incident, reproduced.
                state.release_event.wait()
                return

            n = len(state.pieces)
            for i, piece in enumerate(state.pieces):
                is_last = i == n - 1
                if is_ollama:
                    chunk: dict = {"message": {"content": piece}, "done": is_last}
                    if is_last:
                        chunk.update(
                            {"prompt_eval_count": 3, "eval_count": n, "done_reason": "stop"}
                        )
                    line = (json.dumps(chunk) + "\n").encode()
                else:
                    delta = {
                        "choices": [
                            {
                                "delta": {"content": piece},
                                "finish_reason": "stop" if is_last else None,
                            }
                        ]
                    }
                    line = ("data: " + json.dumps(delta) + "\n\n").encode()
                try:
                    self.wfile.write(line)
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(state.gap)
            if not is_ollama:
                try:
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except OSError:
                    pass

    return Handler


@pytest.fixture
def loopback_server():
    state = _ServerState()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler_factory(state))
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", state
    finally:
        state.release_event.set()
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _call_with_hard_timeout(fn, hard_s: float):
    """Run ``fn()`` on a worker thread with a hard wall-clock budget.

    No `pytest-timeout` plugin is installed in this project (and none should be added -- see
    pyproject.toml). A `concurrent.futures.TimeoutError` here means the streaming-timeout fix has
    regressed and the client is blocking forever, so the test FAILS with a clear message instead
    of hanging the whole suite. Deliberately not used as a context manager: `__exit__` would call
    `shutdown(wait=True)`, which would itself block forever joining the very thread we're trying
    to time out on.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=hard_s)
    except concurrent.futures.TimeoutError:
        pytest.fail(
            f"provider call did not return within the {hard_s}s hard test timeout -- the "
            "streaming timeout fix has regressed (a stalled socket is blocking forever instead "
            "of failing fast)"
        )


def test_stalled_ollama_stream_raises_provider_error(loopback_server):
    base_url, state = loopback_server
    state.mode = "stall"
    provider = OllamaProvider(
        "m", ProviderConfig(base_url=base_url, read_timeout_s=0.5, connect_timeout_s=2.0)
    )
    start = time.monotonic()
    with pytest.raises(ProviderError) as exc_info:
        _call_with_hard_timeout(lambda: provider.complete(_req()), hard_s=15.0)
    elapsed = time.monotonic() - start
    assert "read_timeout_s" in str(exc_info.value)
    assert elapsed < 5.0  # comfortably under the 15s hard budget: it failed fast, not eventually


def test_stalled_openai_stream_raises_provider_error(loopback_server):
    base_url, state = loopback_server
    state.mode = "stall"
    provider = OpenAIProvider(
        "m",
        ProviderConfig(base_url=base_url + "/v1", read_timeout_s=0.5, connect_timeout_s=2.0),
        require_key=False,
    )
    start = time.monotonic()
    with pytest.raises(ProviderError) as exc_info:
        _call_with_hard_timeout(lambda: provider.complete(_req()), hard_s=15.0)
    elapsed = time.monotonic() - start
    assert "read_timeout_s" in str(exc_info.value)
    assert elapsed < 5.0


@pytest.mark.parametrize("provider_kind", ["ollama", "openai"])
def test_slow_but_progressing_stream_succeeds_past_the_read_timeout(loopback_server, provider_kind):
    base_url, state = loopback_server
    state.mode = "slow_drip"
    state.pieces = ["chunk-0 ", "chunk-1 ", "chunk-2 ", "chunk-3 ", "chunk-4 ", "chunk-5"]
    state.gap = 0.25  # 6 chunks * 0.25s ~= 1.5s total -- generous 2x+ headroom over the gap limit
    read_timeout_s = 0.6

    if provider_kind == "ollama":
        provider = OllamaProvider(
            "m",
            ProviderConfig(base_url=base_url, read_timeout_s=read_timeout_s, connect_timeout_s=2.0),
        )
    else:
        provider = OpenAIProvider(
            "m",
            ProviderConfig(
                base_url=base_url + "/v1", read_timeout_s=read_timeout_s, connect_timeout_s=2.0
            ),
            require_key=False,
        )

    start = time.monotonic()
    completion = _call_with_hard_timeout(lambda: provider.complete(_req()), hard_s=15.0)
    elapsed = time.monotonic() - start

    assert completion.text == "".join(state.pieces)  # nothing truncated
    # THE KEY GUARANTEE: total duration (~1.5s) exceeds read_timeout_s (0.6s) yet the call still
    # succeeds, because httpx's read timeout bounds the gap BETWEEN chunks (max 0.25s here), never
    # the total request duration. Without this explicit assertion the test could silently degrade
    # into a fast path and prove nothing.
    assert elapsed > read_timeout_s


def test_stall_is_not_masked_by_a_generous_connect_timeout(loopback_server):
    base_url, state = loopback_server
    state.mode = "stall"
    provider = OllamaProvider(
        "m", ProviderConfig(base_url=base_url, read_timeout_s=0.5, connect_timeout_s=5.0)
    )
    start = time.monotonic()
    with pytest.raises(ProviderError):
        _call_with_hard_timeout(lambda: provider.complete(_req()), hard_s=15.0)
    elapsed = time.monotonic() - start
    assert elapsed < 5.0  # proves the read limit fired, not the much longer connect limit
