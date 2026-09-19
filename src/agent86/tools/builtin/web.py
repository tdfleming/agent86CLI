"""Built-in web tool — fetch a URL's text, gated by the sandbox network policy.

Fetching an arbitrary model-chosen URL from the user's machine is an SSRF primitive: the
harness sits *inside* the trust boundary, so `http://169.254.169.254/` (cloud metadata),
`http://localhost:11434/` (the user's own Ollama), and RFC1918 hosts are all reachable unless
something stops them. This module is that something — every hop (the original URL and each
redirect) is re-resolved and every answer address is vetted before a connection is made, the
body is capped while streaming, and the content type must be textual.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

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

#: Hard ceiling on the bytes read off the wire, applied *before* decoding — a 4 GB download
#: must not become a 4 GB string in memory just to be truncated afterwards.
MAX_BODY_BYTES = 2_000_000
#: Redirects are followed manually so every hop can be re-vetted; this bounds the chain.
MAX_REDIRECTS = 5
#: Textual content types web_fetch is willing to decode. Anything else (images, archives,
#: octet-stream) is refused rather than mangled into replacement characters.
_ALLOWED_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml",
    "application/javascript",
    "application/ld+json",
)
_ALLOWED_CT_SUFFIXES = ("+json", "+xml")

_ALLOW_HINT = (
    "Set [tools] web_allow_private = true (or tools.web_allow_private in config) to allow "
    "private/loopback targets."
)


#: Either IP version — the guard treats them uniformly.
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class BlockedURL(ValueError):
    """A URL the SSRF guard refuses to fetch. The message is model-facing."""


def _unwrap(ip: IPAddress) -> IPAddress:
    """Reduce tunnelled/mapped IPv6 forms to the IPv4 address they actually reach.

    ``::ffff:169.254.169.254`` and ``2002:a9fe:a9fe::`` (6to4) both route to 169.254.169.254;
    checking only the outer IPv6 object would call them "global" and let them through.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip.sixtofour is not None:
            return ip.sixtofour
        if ip.teredo is not None:
            return ip.teredo[1]
    return ip


def _block_reason(ip: IPAddress) -> str | None:
    """Return why ``ip`` is off-limits, or None if it is a fine public address."""
    addr = _unwrap(ip)
    checks = (
        ("unspecified", addr.is_unspecified),
        ("loopback", addr.is_loopback),
        ("link-local (cloud metadata range)", addr.is_link_local),
        ("private", addr.is_private),
        ("multicast", addr.is_multicast),
        ("reserved", addr.is_reserved),
    )
    for label, hit in checks:
        if hit:
            extra = f" via {ip}" if addr is not ip else ""
            return f"{label} address {addr}{extra}"
    return None


def _resolve(host: str, port: int) -> list[IPAddress]:
    """Every A/AAAA answer for ``host`` — a hostname is only as safe as its worst answer."""
    try:
        return [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise BlockedURL(f"Could not resolve host '{host}': {exc}") from exc
    addrs: list[IPAddress] = []
    for info in infos:
        sockaddr = info[4]
        try:
            addrs.append(ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0]))
        except ValueError:  # pragma: no cover - getaddrinfo shouldn't produce these
            continue
    if not addrs:
        raise BlockedURL(f"Could not resolve host '{host}' to any address.")
    return addrs


def _vet_url(url: str, allow_private: bool) -> None:
    """Raise :class:`BlockedURL` unless ``url`` is an http(s) URL to a public address."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise BlockedURL(
            f"Refusing to fetch '{url}': only http and https URLs are allowed "
            f"(got '{scheme or 'no scheme'}')."
        )
    host = parts.hostname
    if not host:
        raise BlockedURL(f"Refusing to fetch '{url}': no host in URL.")
    if allow_private:
        return
    port = parts.port or (443 if scheme == "https" else 80)
    for ip in _resolve(host, port):
        reason = _block_reason(ip)
        if reason is not None:
            raise BlockedURL(
                f"Refusing to fetch '{url}': host '{host}' resolves to a {reason}, which is "
                f"inside the local trust boundary. {_ALLOW_HINT}"
            )


def _content_type_ok(content_type: str) -> bool:
    ct = content_type.split(";", 1)[0].strip().lower()
    if not ct:
        return True  # no declaration — give the page the benefit of the doubt
    return ct.startswith(_ALLOWED_CONTENT_TYPES) or ct.endswith(_ALLOWED_CT_SUFFIXES)


class WebFetchTool(Tool["WebFetchTool.Args"]):
    name = "web_fetch"
    description = (
        "Fetch a public URL over HTTP(S) and return its text content (HTML is reduced to text). "
        "Read-only, but requires network access to be enabled. Private, loopback, and "
        "link-local addresses are refused."
    )
    side_effecting = False

    class Args(BaseModel):
        url: str = Field(..., description="Absolute http(s) URL to fetch.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        ctx.policy.require_network()  # raises PolicyError -> surfaced as ToolResult by run()
        allow_private = bool(getattr(ctx.config.tools, "web_allow_private", False))
        headers = {"User-Agent": ctx.config.tools.web_user_agent}

        try:
            with httpx.Client(
                timeout=ctx.policy.timeout_s, follow_redirects=False, headers=headers
            ) as client:
                final_url, status, content_type, body = _fetch(client, args.url, allow_private)
        except BlockedURL as exc:
            return ToolResult(call_id="", name=self.name, ok=False, error=str(exc))
        except httpx.HTTPError as exc:
            return ToolResult(call_id="", name=self.name, ok=False, error=f"Fetch failed: {exc}")

        text = body
        if "html" in content_type.lower() or text.lstrip().lower().startswith("<!doctype html"):
            text = _html_to_text(text)
        text = text.strip()
        # Keep the observation to a size a model can actually attend to — the lead/main content
        # is what matters; a full long article otherwise drowns it and biases the answer to the
        # tail. Users can raise or disable (0) the cap via [tools] web_max_chars.
        cap = ctx.config.tools.web_max_chars
        if cap and len(text) > cap:
            text = text[:cap].rstrip() + f"\n\n... [truncated to {cap} chars]"
        ok = 200 <= status < 300
        header = f"HTTP {status} {final_url} ({content_type})\n\n"
        return ToolResult(
            call_id="", name=self.name, ok=ok,
            content=ctx.policy.truncate(header + text),
            error=None if ok else f"HTTP {status} ({final_url})",
        )


def _fetch(client: Any, url: str, allow_private: bool) -> tuple[str, int, str, str]:
    """Follow redirects manually, vetting every hop; return (url, status, ctype, text).

    Automatic redirect following is disabled because httpx would chase a 302 from a public
    host straight to ``http://169.254.169.254/`` without ever asking us again.
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _vet_url(current, allow_private)
        with client.stream("GET", current) as resp:
            location = resp.headers.get("location")
            if resp.status_code in (301, 302, 303, 307, 308) and location:
                nxt = urljoin(current, location)
                if nxt == current:
                    raise BlockedURL(f"Refusing to fetch '{url}': redirect loop at '{current}'.")
                current = nxt
                continue
            content_type = resp.headers.get("content-type", "")
            if not _content_type_ok(content_type):
                raise BlockedURL(
                    f"Refusing to read '{current}': content type '{content_type}' is not text. "
                    "web_fetch only returns text/HTML/JSON/XML content."
                )
            body, truncated = _read_capped(resp)
            text = body.decode(_charset(resp, content_type), errors="replace")
            if truncated:
                text += f"\n\n... [body truncated at {MAX_BODY_BYTES} bytes]"
            return current, resp.status_code, content_type, text
    raise BlockedURL(
        f"Refusing to fetch '{url}': more than {MAX_REDIRECTS} redirects (last: '{current}')."
    )


def _read_capped(resp: Any) -> tuple[bytes, bool]:
    """Stream the body, stopping at :data:`MAX_BODY_BYTES` — before any decoding happens."""
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= MAX_BODY_BYTES:
            return b"".join(chunks)[:MAX_BODY_BYTES], True
    return b"".join(chunks), False


def _charset(resp: Any, content_type: str) -> str:
    encoding = getattr(resp, "encoding", None)
    if encoding:
        return str(encoding)
    if "charset=" in content_type.lower():
        return content_type.lower().split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
    return "utf-8"


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


__all__ = ["WebFetchTool", "BlockedURL", "MAX_BODY_BYTES", "MAX_REDIRECTS"]
