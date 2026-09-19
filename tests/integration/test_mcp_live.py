"""Live MCP transport test — connects agent86 to a real MCP server over HTTP and SSE.

Unlike ``test_mcp_client.py`` (which mocks the manager), this spins up an actual MCP server in
a subprocess (``live_mcp_server.py``) and drives ``MCPManager`` against it end-to-end: connect,
``list_tools``, and a real ``call_tool`` round trip. It exercises the remote-transport code
(``_streamable_http`` / ``sse_client``) that unit tests cannot reach.

This module was permanently skipped for a while: it probed ``mcp.server.fastmcp``, which mcp
2.0 removed when FastMCP moved out of the SDK, so the skip fired on every machine including
ones with the extra installed. It now probes what it actually needs — the SDK's own
``MCPServer`` and the uvicorn it serves its ASGI apps with — so it runs wherever the ``mcp``
extra is present, and still skips cleanly on CI's minimal ``.[dev]`` install.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

_EXTRA = "requires the 'mcp' extra (MCP server + uvicorn)"
pytest.importorskip("mcp.server.mcpserver", reason=_EXTRA)
pytest.importorskip("uvicorn", reason=_EXTRA)

from agent86.config import Config, MCPServerConfig  # noqa: E402
from agent86.tools.mcp_client import build_mcp  # noqa: E402

_SERVER = Path(__file__).with_name("live_mcp_server.py")

# Each case is a single (server transport, URL path, explicit agent86 transport) tuple —
# passed whole to the indirect `live_server` fixture. Streamable HTTP is inferred from the
# URL; SSE has to be named.
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
def live_server(request, tmp_path):
    """Launch the live MCP server subprocess for a transport; yield its endpoint URL."""
    server_transport, path, _ = request.param
    port = _free_port()
    # Kept rather than devnull'd: when the SDK's server API shifts again, the traceback in
    # here is the difference between "did not come up within 15s" and an actionable error.
    log = tmp_path / f"live-mcp-{server_transport}.log"
    with log.open("wb") as sink:
        proc = subprocess.Popen(
            [sys.executable, str(_SERVER), server_transport, str(port)],
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
        try:
            try:
                _wait_for_port(port)
            except RuntimeError as exc:
                output = log.read_text(encoding="utf-8", errors="replace").strip()
                raise RuntimeError(f"{exc}\n--- server output ---\n{output}") from exc
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
