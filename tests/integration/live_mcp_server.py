"""A minimal live MCP server used by the live-transport integration test.

Run as a subprocess: ``python live_mcp_server.py <transport> <port>`` where transport is a
FastMCP transport name (``streamable-http`` or ``sse``). Exposes two trivial tools so the test
can assert both tool discovery and a real call round trip over the wire.
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP


def main() -> None:
    transport, port = sys.argv[1], int(sys.argv[2])
    mcp = FastMCP("agent86-live-test", host="127.0.0.1", port=port)

    @mcp.tool()
    def add(a: int, b: int) -> int:
        """Add two integers and return the sum."""
        return a + b

    @mcp.tool()
    def shout(text: str) -> str:
        """Uppercase the given text."""
        return text.upper()

    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
