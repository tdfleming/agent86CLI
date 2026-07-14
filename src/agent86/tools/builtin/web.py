"""Built-in web tool — fetch a URL's text, gated by the sandbox network policy."""

from __future__ import annotations

import re

import httpx
from pydantic import BaseModel, Field

from agent86.tools.base import Tool, ToolContext
from agent86.types import ToolResult

_TAG = re.compile(r"<[^>]+>")
# Whole non-content blocks to drop before extracting text (nav bars, page chrome, footnotes,
# tables/figures) — otherwise a page's menus and boilerplate dominate the byte budget.
_DROP_BLOCKS = re.compile(
    r"<(script|style|nav|header|footer|aside|form|noscript|figure|table)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_SUP_REF = re.compile(r"<sup\b[^>]*>.*?</sup>", re.IGNORECASE | re.DOTALL)  # [1], [362] markers
# Isolate the main article region when the page marks one (covers most sites + Wikipedia).
_MAIN_REGIONS = (
    re.compile(r"<main\b[^>]*>(.*?)</main>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<article\b[^>]*>(.*?)</article>", re.IGNORECASE | re.DOTALL),
    re.compile(r'<div\b[^>]*id=["\']mw-content-text["\'][^>]*>(.*)', re.IGNORECASE | re.DOTALL),
)
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


_BOILERPLATE = ("script", "style", "nav", "header", "footer", "aside", "form", "figure", "table",
                "sup")


def _html_to_text(html: str) -> str:
    """Reduce HTML to readable article text.

    Uses BeautifulSoup (the ``web`` extra) when available — it parses the DOM, drops
    navigation/boilerplate, and isolates the main content region, which keeps a page's menus,
    infoboxes, and reference markers out of what the model sees. Falls back to a regex reducer
    when BeautifulSoup isn't installed.
    """
    cleaned = _html_to_text_bs4(html)
    if cleaned is None:
        cleaned = _html_to_text_regex(html)
    return _WS.sub("\n\n", cleaned)


def _html_to_text_bs4(html: str) -> str | None:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.find_all(_BOILERPLATE):
        element.decompose()
    main = (
        soup.find(id="mw-content-text")
        or soup.find("main")
        or soup.find("article")
        or soup.body
        or soup
    )
    lines = [ln.strip() for ln in main.get_text("\n").splitlines() if ln.strip()]
    return "\n".join(lines)


def _html_to_text_regex(html: str) -> str:
    # Prefer the main article region so navigation/sidebars/boilerplate don't dominate.
    for region in _MAIN_REGIONS:
        m = region.search(html)
        if m:
            html = m.group(1)
            break
    html = _DROP_BLOCKS.sub(" ", html)
    html = _SUP_REF.sub(" ", html)  # drop citation superscripts like [362]
    text = _TAG.sub(" ", html)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


__all__ = ["WebFetchTool"]
