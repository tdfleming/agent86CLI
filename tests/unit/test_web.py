"""v0.7 — web_fetch SSRF guard, redirect re-vetting, and body/content-type caps.

Every test here is offline: DNS resolution and the httpx client are both faked, so the
guard's decisions are exercised without a socket ever being opened.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

import agent86.tools.builtin.web as web
from agent86.config import load_config
from agent86.tools.base import ToolContext
from agent86.tools.builtin.web import WebFetchTool
from agent86.tools.sandbox.policy import default_policy
from agent86.types import ToolCall

PUBLIC_IP = "93.184.216.34"


def _set_flag(model, name: str, value) -> None:
    """Set a config field that may not exist yet (the config agent adds it concurrently)."""
    try:
        setattr(model, name, value)
    except (ValueError, AttributeError):
        object.__setattr__(model, name, value)


def _ctx(tmp_path: Path, **tools_overrides) -> ToolContext:
    cfg = load_config()
    for key, value in tools_overrides.items():
        _set_flag(cfg.tools, key, value)
    policy = default_policy(cfg, tmp_path)
    return ToolContext(workspace=policy.workspace, policy=policy, config=cfg)


# ---- fakes ------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, status_code: int = 200, headers: dict | None = None, body: bytes = b"hi"):
        self.status_code = status_code
        self.headers = headers if headers is not None else {"content-type": "text/plain"}
        self._body = body
        self.encoding = "utf-8"
        self.closed = False
        self.yielded = 0

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc) -> bool:
        self.closed = True
        return False

    def iter_bytes(self):
        for i in range(0, len(self._body), 65536):
            chunk = self._body[i : i + 65536]
            self.yielded += len(chunk)
            yield chunk


class FakeClient:
    """Stands in for httpx.Client: records every request and replays scripted responses."""

    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.requests: list[str] = []
        FakeClient.instances.append(self)

    responses: dict = {}

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def stream(self, method: str, url: str):
        self.requests.append(url)
        resp = self.responses.get(url) or self.responses.get("*")
        if resp is None:
            raise AssertionError(f"unexpected request to {url}")
        return resp


@pytest.fixture
def net(monkeypatch):
    """Fake DNS + fake httpx client. Returns a handle the test scripts."""

    class Net:
        def __init__(self):
            self.dns: dict[str, list[str]] = {}
            self.responses: dict[str, FakeResponse] = {}

        def resolves(self, host: str, *ips: str) -> None:
            self.dns[host] = list(ips)

        def serves(self, url: str, resp: FakeResponse) -> None:
            self.responses[url] = resp

        @property
        def requests(self) -> list[str]:
            return [u for c in FakeClient.instances for u in c.requests]

    handle = Net()

    def fake_getaddrinfo(host, port, *a, **kw):
        ips = handle.dns.get(host)
        if ips is None:
            raise OSError(f"no fake DNS entry for {host!r}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 80)) for ip in ips]

    FakeClient.instances = []
    FakeClient.responses = handle.responses
    monkeypatch.setattr(web.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(web.httpx, "Client", FakeClient)
    return handle


def _fetch(url: str, ctx: ToolContext):
    return WebFetchTool().run(ToolCall(id="1", name="web_fetch", arguments={"url": url}), ctx)


# ---- SSRF refusals ------------------------------------------------------ #


def test_refuses_cloud_metadata_ip(tmp_path, net):
    res = _fetch("http://169.254.169.254/latest/meta-data/", _ctx(tmp_path))
    assert not res.ok
    assert "link-local" in (res.error or "")
    assert "web_allow_private" in (res.error or "")
    assert net.requests == []  # never connected


def test_refuses_localhost_ollama(tmp_path, net):
    net.resolves("localhost", "127.0.0.1")
    res = _fetch("http://localhost:11434/api/tags", _ctx(tmp_path))
    assert not res.ok and "loopback" in (res.error or "")
    assert net.requests == []


def test_refuses_private_range_behind_a_hostname(tmp_path, net):
    net.resolves("intranet.example.com", "10.0.0.5")
    res = _fetch("https://intranet.example.com/secrets", _ctx(tmp_path))
    assert not res.ok and "private" in (res.error or "")


def test_refuses_when_any_dns_answer_is_private(tmp_path, net):
    """A hostname is only as safe as its worst answer (DNS round-robin to 127.0.0.1)."""
    net.resolves("mixed.example.com", PUBLIC_IP, "127.0.0.1")
    res = _fetch("https://mixed.example.com/", _ctx(tmp_path))
    assert not res.ok and "loopback" in (res.error or "")


def test_refuses_ipv4_mapped_ipv6_metadata(tmp_path, net):
    res = _fetch("http://[::ffff:169.254.169.254]/latest/", _ctx(tmp_path))
    assert not res.ok and "link-local" in (res.error or "")


def test_refuses_non_http_scheme(tmp_path, net):
    res = _fetch("file:///etc/passwd", _ctx(tmp_path))
    assert not res.ok
    assert "only http and https" in (res.error or "")


def test_allow_flag_permits_localhost(tmp_path, net):
    net.serves("http://localhost:11434/api/tags", FakeResponse(body=b'{"models": []}'))
    ctx = _ctx(tmp_path, web_allow_private=True)
    res = _fetch("http://localhost:11434/api/tags", ctx)
    assert res.ok, res.error
    assert '{"models": []}' in (res.content or "")


# ---- redirects ---------------------------------------------------------- #


def test_redirect_to_private_address_is_refused(tmp_path, net):
    net.resolves("example.com", PUBLIC_IP)
    net.serves(
        "https://example.com/go",
        FakeResponse(status_code=302, headers={"location": "http://169.254.169.254/"}),
    )
    res = _fetch("https://example.com/go", _ctx(tmp_path))
    assert not res.ok and "link-local" in (res.error or "")
    assert net.requests == ["https://example.com/go"]  # the second hop never happened


def test_redirect_to_public_address_is_followed(tmp_path, net):
    net.resolves("example.com", PUBLIC_IP)
    net.resolves("elsewhere.example.org", PUBLIC_IP)
    net.serves(
        "https://example.com/go",
        FakeResponse(status_code=301, headers={"location": "https://elsewhere.example.org/page"}),
    )
    net.serves("https://elsewhere.example.org/page", FakeResponse(body=b"landed"))
    res = _fetch("https://example.com/go", _ctx(tmp_path))
    assert res.ok, res.error
    assert "landed" in (res.content or "")
    assert "https://elsewhere.example.org/page" in (res.content or "")


def test_redirect_chain_is_bounded(tmp_path, net):
    net.resolves("example.com", PUBLIC_IP)
    for i in range(20):
        net.serves(
            f"https://example.com/{i}",
            FakeResponse(status_code=302, headers={"location": f"https://example.com/{i + 1}"}),
        )
    res = _fetch("https://example.com/0", _ctx(tmp_path))
    assert not res.ok and "redirects" in (res.error or "")
    assert len(net.requests) <= web.MAX_REDIRECTS + 1


# ---- body + content type ------------------------------------------------ #


def test_oversize_body_is_capped_while_streaming(tmp_path, net):
    net.resolves("example.com", PUBLIC_IP)
    resp = FakeResponse(body=b"x" * (web.MAX_BODY_BYTES + 5_000_000))
    net.serves("https://example.com/big", resp)
    ctx = _ctx(tmp_path, web_max_chars=0)  # isolate the byte cap from the char cap
    res = _fetch("https://example.com/big", ctx)
    assert res.ok, res.error
    # Reading stopped at the cap: the remaining ~5 MB never came off the wire, and nothing
    # that large was ever decoded.
    assert resp.yielded < web.MAX_BODY_BYTES + 100_000
    assert len(res.content or "") <= ctx.policy.max_output_bytes + 200


def test_oversize_body_marker_when_output_limit_is_generous(tmp_path, net):
    net.resolves("example.com", PUBLIC_IP)
    net.serves("https://example.com/big", FakeResponse(body=b"x" * (web.MAX_BODY_BYTES + 10)))
    ctx = _ctx(tmp_path, web_max_chars=0)
    ctx.policy.max_output_bytes = 10_000_000
    res = _fetch("https://example.com/big", ctx)
    assert res.ok, res.error
    assert "body truncated" in (res.content or "")


def test_non_text_content_type_is_refused(tmp_path, net):
    net.resolves("example.com", PUBLIC_IP)
    net.serves(
        "https://example.com/logo.png",
        FakeResponse(headers={"content-type": "image/png"}, body=b"\x89PNG"),
    )
    res = _fetch("https://example.com/logo.png", _ctx(tmp_path))
    assert not res.ok and "not text" in (res.error or "")


def test_json_content_type_is_allowed(tmp_path, net):
    net.resolves("api.example.com", PUBLIC_IP)
    net.serves(
        "https://api.example.com/v1",
        FakeResponse(headers={"content-type": "application/vnd.api+json"}, body=b'{"ok":true}'),
    )
    res = _fetch("https://api.example.com/v1", _ctx(tmp_path))
    assert res.ok and '{"ok":true}' in (res.content or "")


# ---- behaviour preserved from v0.6 -------------------------------------- #


def test_sends_descriptive_user_agent(tmp_path, net):
    net.resolves("example.com", PUBLIC_IP)
    net.serves("https://example.com/", FakeResponse(body=b"hello"))
    _fetch("https://example.com/", _ctx(tmp_path))
    ua = FakeClient.instances[0].kwargs["headers"]["User-Agent"]
    # Descriptive UA with a contact URL — required by sites like Wikipedia (a generic UA 403s).
    assert ua.startswith("agent86/") and "github.com/tdfleming/agent86CLI" in ua
    assert FakeClient.instances[0].kwargs["follow_redirects"] is False


def test_caps_extracted_text(tmp_path, net):
    net.resolves("example.com", PUBLIC_IP)
    body = ("<html><body><p>" + ("lorem ipsum " * 500) + "</p></body></html>").encode()
    net.serves(
        "https://example.com/", FakeResponse(headers={"content-type": "text/html"}, body=body)
    )
    res = _fetch("https://example.com/", _ctx(tmp_path, web_max_chars=500))
    assert res.ok
    assert "truncated to 500 chars" in (res.content or "")
    assert len(res.content or "") < 900


def test_sets_error_on_non_2xx(tmp_path, net):
    net.resolves("example.com", PUBLIC_IP)
    net.serves("https://example.com/missing", FakeResponse(status_code=404, body=b"nope"))
    res = _fetch("https://example.com/missing", _ctx(tmp_path))
    assert not res.ok
    assert "404" in (res.error or "")
    assert "nope" in (res.content or "")


def test_network_disabled_is_refused(tmp_path, net):
    ctx = _ctx(tmp_path)
    ctx.policy.network = False
    res = _fetch("https://example.com/", ctx)
    assert not res.ok and "Network access is disabled" in (res.error or "")
