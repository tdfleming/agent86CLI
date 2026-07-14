"""Built-in web tool — fetch a URL's text, gated by the sandbox network policy."""

from __future__ import annotations

import re

import httpx
from pydantic import BaseModel, Field

from agent86.tools.base import Tool, ToolContext
from agent86.types import ToolResult

_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WS = re.compile(r"\n{3,}")


class WebFetchTool(Tool["WebFetchTool.Args"]):
    name = "web_fetch"
    description = (
        "Fetch a URL over HTTP(S) and return its text content (HTML is reduced to text). "
        "Read-only, but requires network access to be enabled."
    )
    side_effecting = False

    class Args(BaseModel):
        url: str = Field(..., description="Absolute http(s) URL to fetch.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        ctx.policy.require_network()  # raises PolicyError -> surfaced as ToolResult by run()
        if not args.url.lower().startswith(("http://", "https://")):
            return ToolResult(call_id="", name=self.name, ok=False, error="URL must be http(s).")
        try:
            resp = httpx.get(
                args.url,
                timeout=ctx.policy.timeout_s,
                follow_redirects=True,
                headers={"User-Agent": ctx.config.tools.web_user_agent},
            )
        except httpx.HTTPError as exc:
            return ToolResult(call_id="", name=self.name, ok=False, error=f"Fetch failed: {exc}")

        content_type = resp.headers.get("content-type", "")
        text = resp.text
        if "html" in content_type or text.lstrip().lower().startswith("<!doctype html"):
            text = _html_to_text(text)
        header = f"HTTP {resp.status_code} {args.url} ({content_type})\n\n"
        return ToolResult(
            call_id="", name=self.name, ok=resp.is_success,
            content=ctx.policy.truncate(header + text.strip()),
            error=None if resp.is_success else f"HTTP {resp.status_code} ({args.url})",
        )


def _html_to_text(html: str) -> str:
    html = _SCRIPT_STYLE.sub(" ", html)
    text = _TAG.sub(" ", html)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return _WS.sub("\n\n", text)


__all__ = ["WebFetchTool"]
