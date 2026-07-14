"""Phase 3 — tools, sandbox policy, registry, and approval gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent86.config import load_config
from agent86.guardrails.policy import ApprovalGate
from agent86.tools.base import ToolContext
from agent86.tools.builtin.files import ListDirTool, ReadFileTool, WriteFileTool
from agent86.tools.registry import default_registry
from agent86.tools.sandbox.policy import PolicyError, SandboxPolicy, default_policy
from agent86.types import ApprovalMode, ToolCall


def _ctx(tmp_path: Path) -> ToolContext:
    cfg = load_config()
    policy = default_policy(cfg, tmp_path)
    return ToolContext(workspace=policy.workspace, policy=policy, config=cfg)


# ---- sandbox policy ---------------------------------------------------- #


def test_path_jail_allows_inside_and_blocks_outside(tmp_path):
    policy = SandboxPolicy(workspace=tmp_path)
    inside = policy.resolve_within("sub/file.txt")
    assert tmp_path in inside.parents
    with pytest.raises(PolicyError):
        policy.resolve_within("../escape.txt")


def test_web_fetch_sends_descriptive_user_agent(tmp_path, monkeypatch):
    import agent86.tools.builtin.web as web
    from agent86.tools.builtin.web import WebFetchTool

    captured: dict = {}

    class FakeResp:
        status_code = 200
        is_success = True
        headers = {"content-type": "text/plain"}
        text = "hello"

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeResp()

    monkeypatch.setattr(web.httpx, "get", fake_get)
    WebFetchTool().run(
        ToolCall(id="1", name="web_fetch", arguments={"url": "https://example.com"}), _ctx(tmp_path)
    )
    ua = captured["headers"]["User-Agent"]
    # Descriptive UA with a contact URL — required by sites like Wikipedia (a generic UA 403s).
    assert ua.startswith("agent86/") and "github.com/tdfleming/agent86CLI" in ua


def test_web_fetch_caps_extracted_text(tmp_path, monkeypatch):
    import agent86.tools.builtin.web as web
    from agent86.tools.builtin.web import WebFetchTool

    class FakeResp:
        status_code = 200
        is_success = True
        headers = {"content-type": "text/plain"}
        text = "word " * 5000  # ~25k chars, far over the default cap

    monkeypatch.setattr(web.httpx, "get", lambda *a, **k: FakeResp())
    ctx = _ctx(tmp_path)
    ctx.config.tools.web_max_chars = 500
    res = WebFetchTool().run(
        ToolCall(id="1", name="web_fetch", arguments={"url": "https://example.com"}), ctx
    )
    assert res.ok
    assert "[truncated to 500 chars]" in res.content
    # body (excluding the HTTP header + truncation note) is bounded by the cap
    assert len(res.content) < 800


def test_web_fetch_sets_error_on_non_2xx(tmp_path, monkeypatch):
    import agent86.tools.builtin.web as web
    from agent86.tools.builtin.web import WebFetchTool

    class FakeResp:
        status_code = 403
        is_success = False
        headers = {"content-type": "text/html"}
        text = "<html>Forbidden</html>"

    monkeypatch.setattr(web.httpx, "get", lambda *a, **k: FakeResp())
    res = WebFetchTool().run(
        ToolCall(id="1", name="web_fetch", arguments={"url": "https://example.com"}), _ctx(tmp_path)
    )
    assert res.ok is False
    assert res.error and "403" in res.error  # a failed fetch now carries a usable error string


_SAMPLE_HTML = """
<html><head><title>t</title><style>.x{}</style></head>
<body>
  <nav>Home About Login Donate</nav>
  <header>Site chrome</header>
  <main>
    <h1>Jane Doe</h1>
    <p>Jane Doe was a pioneering scientist.<sup>[1]</sup></p>
    <table class="infobox"><tr><td>Born</td><td>1900</td></tr></table>
  </main>
  <footer>Copyright</footer>
</body></html>
"""


def test_html_to_text_drops_boilerplate_and_keeps_article():
    from agent86.tools.builtin.web import _html_to_text

    text = _html_to_text(_SAMPLE_HTML)
    assert "Jane Doe was a pioneering scientist." in text
    # navigation / chrome / footer / reference markers are stripped
    assert "Donate" not in text and "Site chrome" not in text and "Copyright" not in text
    assert "[1]" not in text


def test_html_to_text_regex_fallback_without_bs4():
    # The regex fallback (no BeautifulSoup) still removes chrome and keeps the article.
    from agent86.tools.builtin.web import _html_to_text_regex

    text = _html_to_text_regex(_SAMPLE_HTML)
    assert "Jane Doe was a pioneering scientist." in text
    assert "Donate" not in text and "Copyright" not in text


def test_env_is_scrubbed_of_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = SandboxPolicy(workspace=tmp_path).scrubbed_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "PATH" in env


def test_truncate_caps_output(tmp_path):
    policy = SandboxPolicy(workspace=tmp_path, max_output_bytes=10)
    out = policy.truncate("x" * 50)
    assert out.startswith("x" * 10)
    assert "truncated" in out


# ---- file tools -------------------------------------------------------- #


def test_write_then_read_roundtrip(tmp_path):
    ctx = _ctx(tmp_path)
    w = WriteFileTool().run(
        ToolCall(id="1", name="write_file", arguments={"path": "a.txt", "content": "hello"}), ctx
    )
    assert w.ok
    assert (tmp_path / "a.txt").read_text() == "hello"

    r = ReadFileTool().run(ToolCall(id="2", name="read_file", arguments={"path": "a.txt"}), ctx)
    assert r.ok and r.content == "hello"


def test_read_missing_file_is_soft_error(tmp_path):
    ctx = _ctx(tmp_path)
    r = ReadFileTool().run(ToolCall(id="1", name="read_file", arguments={"path": "nope.txt"}), ctx)
    assert not r.ok and "No such file" in (r.error or "")


def test_invalid_arguments_return_soft_error(tmp_path):
    ctx = _ctx(tmp_path)
    # missing required 'content'
    r = WriteFileTool().run(ToolCall(id="1", name="write_file", arguments={"path": "a.txt"}), ctx)
    assert not r.ok and "Invalid arguments" in (r.error or "")


def test_list_dir(tmp_path):
    (tmp_path / "one.txt").write_text("1")
    (tmp_path / "sub").mkdir()
    ctx = _ctx(tmp_path)
    r = ListDirTool().run(ToolCall(id="1", name="list_dir", arguments={"path": "."}), ctx)
    assert r.ok and "one.txt" in r.content and "sub/" in r.content


def test_path_jail_enforced_through_tool(tmp_path):
    ctx = _ctx(tmp_path)
    r = ReadFileTool().run(
        ToolCall(id="1", name="read_file", arguments={"path": "../../secret"}), ctx
    )
    assert not r.ok and "jail" in (r.error or "").lower()


# ---- registry ---------------------------------------------------------- #


def test_registry_has_builtins_and_specs():
    reg = default_registry(load_config())
    assert {"read_file", "write_file", "edit_file", "list_dir", "run_command", "python_exec",
            "web_fetch"}.issubset(set(reg.names()))
    specs = reg.specs()
    assert all(s.parameters.get("type") == "object" for s in specs)


def test_registry_unknown_tool(tmp_path):
    reg = default_registry(load_config())
    res = reg.dispatch(ToolCall(id="1", name="does_not_exist", arguments={}), _ctx(tmp_path))
    assert not res.ok and "Unknown tool" in (res.error or "")


# ---- approval gate ----------------------------------------------------- #


def test_gate_readonly_always_approved():
    gate = ApprovalGate(ApprovalMode.DENY)
    call = ToolCall(id="1", name="read_file", arguments={"path": "a"})
    assert gate.decide(ReadFileTool(), call).approved


def test_gate_side_effecting_modes():
    call = ToolCall(id="1", name="write_file", arguments={"path": "a", "content": "b"})
    assert ApprovalGate(ApprovalMode.AUTO).decide(WriteFileTool(), call).approved
    assert not ApprovalGate(ApprovalMode.DENY).decide(WriteFileTool(), call).approved
    # ASK with no prompt -> safe decline
    assert not ApprovalGate(ApprovalMode.ASK).decide(WriteFileTool(), call).approved
    # ASK with an approving callback
    gate = ApprovalGate(ApprovalMode.ASK, prompt=lambda name, preview: True)
    assert gate.decide(WriteFileTool(), call).approved
