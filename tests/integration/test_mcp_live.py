"""Live MCP transport test — connects agent86 to a real MCP server over HTTP and SSE.

Unlike ``test_mcp_client.py`` (which mocks the manager), this spins up an actual FastMCP server
in a subprocess and drives ``MCPManager`` against it end-to-end: connect, ``list_tools``, and a
real ``call_tool`` round trip. It exercises the remote-transport code (``_streamable_http`` /
``sse_client``) that unit tests cannot reach.

Requires the ``mcp`` extra (which brings the FastMCP server + uvicorn); the whole module is
skipped when it is not installed — e.g. CI's minimal ``.[dev]`` install.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp.server.fastmcp", reason="requires the 'mcp' extra (FastMCP server)")

from agent86.config import Config, MCPServerConfig  # noqa: E402
from agent86.tools.mcp_client import build_mcp  # noqa: E402

_SERVER = Path(__file__).with_name("live_mcp_server.py")

# Each case is a single (FastMCP transport, URL path, explicit agent86 transport) tuple —
# passed whole to the indirect `live_server` fixture.
_CASES = [
    pytest.param(("streamable-http", "/mcp", None), id="http"),
    pytest.param(("sse", "/sse", "sse"), id="sse"),
]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.5)
            try:
                s.connect(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.2)
    raise RuntimeError(f"server on port {port} did not come up within {timeout}s")


@pytest.fixture
def live_server(request):
    """Launch the FastMCP server subprocess for a transport; yield its base URL."""
    fastmcp_transport, path, _ = request.param
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(_SERVER), fastmcp_transport, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        yield f"http://127.0.0.1:{port}{path}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _build_ready_manager(cfg: Config, tries: int = 15):
    """Build the manager, retrying briefly for the ASGI app to finish starting up."""
    last = None
    for _ in range(tries):
        mgr = build_mcp(cfg)
        assert mgr is not None
        if mgr.tools():
            return mgr
        last = mgr.note
        mgr.close()
        time.sleep(0.3)
    raise AssertionError(f"no tools discovered from live server (last note: {last})")


@pytest.mark.parametrize("live_server", _CASES, indirect=True)
def test_live_transport_lists_and_calls_tools(live_server, request):
    _, _, explicit_transport = request.node.callspec.params["live_server"]
    cfg = Config(
        mcp_servers={
            "live": MCPServerConfig(url=live_server, transport=explicit_transport),
        }
    )
    # The transport is inferred to "http" for the streamable-HTTP case, explicit for SSE.
    assert cfg.mcp_servers["live"].transport == (explicit_transport or "http")

    mgr = _build_ready_manager(cfg)
    try:
        names = {t.name for t in mgr.tools()}
        assert names == {"mcp__live__add", "mcp__live__shout"}

        # Real call round trips over the live transport.
        assert mgr.call_tool("live", "add", {"a": 40, "b": 2}).strip() == "42"
        assert mgr.call_tool("live", "shout", {"text": "it works"}).strip() == "IT WORKS"
    finally:
        mgr.close()
