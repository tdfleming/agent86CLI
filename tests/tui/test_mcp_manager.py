"""Wave 0 scaffolds for MCP-01: `MCPManagerModal` / `MCPServerFormModal` Pilot tests and the
full-app `/config mcp` chain.

Implemented by plans 04-05 and 04-08. Follows the `_PickerHost` shape from
`tests/tui/test_provider_manager.py` and the full-app fake-provider harness in
`tests/tui/test_app.py`.

Every import of a not-yet-implemented module is deferred inside a test body so collection
succeeds; the module-level xfail marker (not a collection error) is what records the pending
status. These scaffolds encode the exact interfaces, widget ids and dismissal contracts that
plans 04-05 / 04-08 must satisfy.
"""

from __future__ import annotations

import asyncio

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, OptionList, RichLog, Static, TextArea

from agent86.config import Config, MCPServerConfig, load_config
from agent86.orchestration.loop import Harness
from agent86.tui.app import Agent86App
from agent86.types import ApprovalMode
from agent86.ui.repl import _Repl
from tests.support import make_text_provider


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met within timeout")


class _PickerHost(App):
    """Minimal host app: pushes a given modal screen on mount, records the dismissed value."""

    def __init__(self, screen) -> None:
        super().__init__()
        self._screen = screen
        self.result: object = "__unset__"

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(self._screen, self._store)

    def _store(self, value) -> None:
        self.result = value


def _make_repl(tmp_path, provider, approval=ApprovalMode.AUTO):
    cfg = load_config()
    cfg.guardrails.approval = approval
    harness = Harness(cfg, provider=provider, memory=None, workspace=tmp_path)
    return _Repl(cfg, resume=None, harness=harness)


def _cfg_with_servers() -> Config:
    cfg = load_config()
    cfg.mcp_servers = {
        "alpha": MCPServerConfig(command="npx", args=["-y", "srv"]),
        "remote": MCPServerConfig(url="https://x/mcp"),
        "off": MCPServerConfig(command="uvx", args=["thing"], enabled=False),
    }
    return cfg


# ---- mcp_server_rows (D-01) ---------------------------------------------------------------- #


async def test_mcp_server_rows_lists_every_configured_server():
    from agent86.tui.screens.mcp_manager import mcp_server_rows

    rows = mcp_server_rows(_cfg_with_servers())
    assert [r.name for r in rows] == ["alpha", "remote", "off"]
    assert all(r.transport in {"stdio", "http", "sse"} for r in rows)
    assert rows[0].endpoint == "npx -y srv"
    assert rows[1].endpoint == "https://x/mcp"
    assert rows[0].status == "enabled"
    assert rows[2].status == "disabled"


# ---- MCPManagerModal (D-08, D-01) ---------------------------------------------------------- #


async def test_mcp_manager_list_spawns_no_subprocess(monkeypatch):
    """D-08: opening the list is a pure config read — it must never start a server."""
    import subprocess

    import agent86.tools.mcp_client as mcp_client
    from agent86.tui.screens.mcp_manager import MCPManagerModal, mcp_server_rows

    def _boom(*a, **k):
        raise AssertionError("the manager list must not spawn a server")

    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(mcp_client, "_open_transport", _boom, raising=False)

    cfg = _cfg_with_servers()
    host = _PickerHost(MCPManagerModal(mcp_server_rows(cfg)))
    async with host.run_test() as pilot:
        await pilot.pause()
        option_list = host.screen.query_one("#mcp-server-list", OptionList)
        # one row per server, plus the two "add" rows
        assert option_list.option_count == len(cfg.mcp_servers) + 2


async def test_mcp_manager_selecting_a_server_dismisses_with_edit_action():
    from agent86.tui.screens.mcp_manager import MCPManagerAction, MCPManagerModal, mcp_server_rows

    host = _PickerHost(MCPManagerModal(mcp_server_rows(_cfg_with_servers())))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert host.result == MCPManagerAction(kind="edit", name="alpha")


async def test_mcp_manager_remove_binding_dismisses_with_remove_action():
    from agent86.tui.screens.mcp_manager import MCPManagerModal, mcp_server_rows

    host = _PickerHost(MCPManagerModal(mcp_server_rows(_cfg_with_servers())))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
    assert host.result.kind == "remove"
    assert host.result.name == "alpha"


async def test_mcp_manager_toggle_binding_dismisses_with_toggle_action():
    from agent86.tui.screens.mcp_manager import MCPManagerModal, mcp_server_rows

    host = _PickerHost(MCPManagerModal(mcp_server_rows(_cfg_with_servers())))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
    assert host.result.kind == "toggle"
    assert host.result.name == "alpha"


async def test_mcp_manager_add_json_option_dismisses_with_add_json():
    from agent86.tui.screens.mcp_manager import MCPManagerModal, mcp_server_rows

    rows = mcp_server_rows(_cfg_with_servers())
    host = _PickerHost(MCPManagerModal(rows))
    async with host.run_test() as pilot:
        await pilot.pause()
        option_list = host.screen.query_one("#mcp-server-list", OptionList)
        option_list.highlighted = len(rows)  # first row after the servers
        option_list.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert host.result.kind == "add_json"
    assert host.result.name is None


async def test_mcp_manager_escape_dismisses_none():
    from agent86.tui.screens.mcp_manager import MCPManagerModal, mcp_server_rows

    host = _PickerHost(MCPManagerModal(mcp_server_rows(_cfg_with_servers())))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert host.result is None


# ---- parse_server_json (D-02, D-05) -------------------------------------------------------- #


async def test_parse_server_json_accepts_bare_object():
    from agent86.tui.screens.mcp_manager import parse_server_json

    name, cfg = parse_server_json('{"command":"npx","args":["-y","srv"]}', name_hint="alpha")
    assert name == "alpha"
    assert cfg.transport == "stdio"
    assert cfg.command == "npx"
    assert cfg.args == ["-y", "srv"]


async def test_parse_server_json_accepts_wrapped_mcp_servers_form():
    from agent86.tui.screens.mcp_manager import parse_server_json

    raw = '{"mcpServers":{"github":{"url":"https://api.githubcopilot.com/mcp/"}}}'
    name, cfg = parse_server_json(raw, name_hint="ignored")
    assert name == "github"  # the wrapped name wins over the hint
    assert cfg.transport == "http"


async def test_parse_server_json_invalid_json_raises_value_error():
    from agent86.tui.screens.mcp_manager import parse_server_json

    with pytest.raises(ValueError) as exc:
        parse_server_json("{not json", name_hint="alpha")
    assert "json" in str(exc.value).lower()


async def test_parse_server_json_invalid_config_surfaces_validator_message():
    """D-05: the verbatim MCPServerConfig validator message reaches the user."""
    from agent86.tui.screens.mcp_manager import parse_server_json

    with pytest.raises(ValueError) as exc:
        parse_server_json('{"command":"npx","url":"https://x"}', name_hint="alpha")
    assert "use one transport" in str(exc.value)


# ---- build_manual_config / parse_kv_list (D-03, D-06) -------------------------------------- #


async def test_build_manual_config_shlex_splits_command_line():
    from agent86.tui.screens.mcp_manager import build_manual_config

    cfg = build_manual_config(
        "npx -y @modelcontextprotocol/server-filesystem /tmp", "", "", "", None
    )
    assert cfg.command == "npx"
    assert cfg.args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]


async def test_build_manual_config_url_transport_toggle():
    from agent86.tui.screens.mcp_manager import build_manual_config

    assert build_manual_config("", "https://x/mcp", "", "", "sse").transport == "sse"
    assert build_manual_config("", "https://x/mcp", "", "", None).transport == "http"


async def test_parse_kv_list_parses_env_and_headers():
    from agent86.tui.screens.mcp_manager import parse_kv_list

    assert parse_kv_list("TOKEN=${GH}, OTHER=x") == {"TOKEN": "${GH}", "OTHER": "x"}
    assert parse_kv_list("") == {}
    with pytest.raises(ValueError):
        parse_kv_list("no-equals-sign")


# ---- MCPServerFormModal (D-04, D-05, D-07) ------------------------------------------------- #


async def test_form_shows_validator_error_inline_and_disables_continue():
    """D-05: an invalid draft is reported inline and never discards the typed text."""
    from agent86.tui.screens.mcp_manager import MCPServerFormModal

    host = _PickerHost(MCPServerFormModal(mode="json"))
    async with host.run_test() as pilot:
        await pilot.pause()
        json_input = host.screen.query_one("#mcp-json")
        json_input.focus()
        await pilot.pause()
        await pilot.press(*"{bad")
        await pilot.pause()
        error = host.screen.query_one("#mcp-form-error", Static)
        assert str(error.render()).strip() != ""
        assert host.screen.query_one("#mcp-form-continue", Button).disabled is True
        typed_text = json_input.text if hasattr(json_input, "text") else json_input.value
        assert "{bad" in typed_text


async def test_form_name_collision_blocks():
    """D-04: a duplicate server name is refused before it can clobber an existing entry."""
    from agent86.tui.screens.mcp_manager import MCPServerFormModal

    host = _PickerHost(MCPServerFormModal(mode="manual", existing_names={"alpha"}))
    async with host.run_test() as pilot:
        await pilot.pause()
        name_input = host.screen.query_one("#mcp-name", Input)
        name_input.focus()
        await pilot.pause()
        await pilot.press(*"alpha")
        await pilot.pause()
        error = host.screen.query_one("#mcp-form-error", Static)
        assert "already" in str(error.render()).lower()
        assert host.screen.query_one("#mcp-form-continue", Button).disabled is True


async def test_form_prefilled_for_edit():
    """D-07: editing an existing server opens the form pre-populated."""
    from agent86.tui.screens.mcp_manager import MCPServerDraft, MCPServerFormModal

    draft = MCPServerDraft(
        name="alpha",
        cfg=MCPServerConfig(command="npx", args=["-y", "srv"]),
        original_name="alpha",
    )
    host = _PickerHost(MCPServerFormModal(mode="manual", draft=draft))
    async with host.run_test() as pilot:
        await pilot.pause()
        assert host.screen.query_one("#mcp-name", Input).value == "alpha"
        assert "npx" in host.screen.query_one("#mcp-command", Input).value


# ---- /config mcp command registration and full-app chain (D-21, plan 04-08) ---------------- #


async def test_config_mcp_command_is_in_registry():
    from agent86.tui.commands import find_command, find_command_for_line

    entry = find_command("/config mcp")
    assert entry is not None
    assert entry.needs_choice == "config_mcp"
    match = find_command_for_line("/config mcp")
    assert match is not None
    assert match[0] is entry


async def test_config_mcp_opens_manager_modal_in_full_app(tmp_path):
    from agent86.tui.screens.mcp_manager import MCPManagerModal

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "/config mcp"
        await pilot.press("enter")
        await _wait_until(lambda: isinstance(app.screen_stack[-1], MCPManagerModal))
        assert isinstance(app.screen_stack[-1], MCPManagerModal)


# ---- full-app /config mcp add/edit/remove/toggle chain (plan 04-08) ------------------------ #


class _FakeMCPTool:
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description


class _FakeMCPManager:
    """Stands in for `MCPManager` on `harness.mcp` — never spawns a real transport.

    Mirrors `tests/tui/test_mcp_test_modal.py`'s `_FakeManager`, extended with `tools_for` and
    a `servers` dict so `Harness.add_mcp_server`/`remove_mcp_server` work against it unchanged.
    """

    def __init__(self, *, fail: str | None = None) -> None:
        self.servers: dict[str, MCPServerConfig] = {}
        self.note: str | None = None
        self._fail = fail
        self.start_calls: list[dict] = []
        self.stop_calls: list[str] = []
        self._tools: dict[str, list[_FakeMCPTool]] = {}

    def start_server(self, name, cfg, timeout=30.0, overrides=None):
        self.start_calls.append({"name": name, "cfg": cfg, "overrides": overrides})
        if self._fail:
            raise RuntimeError(self._fail)
        tools = [
            _FakeMCPTool(f"mcp__{name}__search", "search"),
            _FakeMCPTool(f"mcp__{name}__fetch", "fetch"),
        ]
        self._tools[name] = tools
        return tools

    def stop_server(self, name, timeout=10.0):
        self.stop_calls.append(name)
        self._tools.pop(name, None)

    def tools_for(self, name):
        return list(self._tools.get(name, []))


def _fill_json_form(screen, name: str, json_body: str) -> None:
    screen.query_one("#mcp-name", Input).value = name
    screen.query_one("#mcp-json", TextArea).text = json_body
    screen._revalidate()


async def _wait_for_mcp_test_ready(app, pilot, tries: int = 50) -> None:
    """Poll via `pilot.pause` (not a bare `asyncio.sleep` loop) so Textual's own mount/refresh
    machinery gets a chance to settle before we query button children — mirrors the proven
    pattern in `tests/tui/test_mcp_test_modal.py`; a tight asyncio-only poll can observe
    `#mcp-test-buttons.display is True` before its Button children finish mounting.
    """
    for _ in range(tries):
        try:
            buttons = app.screen.query_one("#mcp-test-buttons")
            if buttons.display and list(buttons.children):
                return
        except Exception:
            pass
        await pilot.pause(0.05)
    raise AssertionError("mcp test buttons never became ready")


async def _open_mcp_manager(app, pilot) -> None:
    from agent86.tui.screens.mcp_manager import MCPManagerModal

    prompt = app.query_one("#prompt", Input)
    prompt.value = "/config mcp"
    await pilot.press("enter")
    await _wait_until(lambda: isinstance(app.screen, MCPManagerModal))


async def test_add_json_chain_reaches_save_diff(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer
    from agent86.tui.screens.mcp_manager import MCPServerFormModal
    from agent86.tui.screens.mcp_test import MCPTestModal
    from agent86.tui.screens.save_diff import SaveDiffModal

    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", tmp_path / "config.toml")
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.mcp = _FakeMCPManager()
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _open_mcp_manager(app, pilot)

        option_list = app.screen.query_one("#mcp-server-list", OptionList)
        option_list.highlighted = 0  # no configured servers -> add_json is the first option
        option_list.focus()
        await pilot.pause()
        await pilot.press("enter")
        await _wait_until(lambda: isinstance(app.screen, MCPServerFormModal))

        _fill_json_form(
            app.screen, "alpha", '{"command": "npx", "args": ["-y", "alpha-server"]}'
        )
        await pilot.pause()
        await pilot.click("#mcp-form-continue")
        await _wait_until(lambda: isinstance(app.screen, MCPTestModal))
        await _wait_for_mcp_test_ready(app, pilot)
        await pilot.pause()
        await pilot.click("#mcp-test-continue")
        await _wait_until(lambda: isinstance(app.screen, SaveDiffModal))
        await _wait_until(lambda: bool(app.screen.query("#save-confirm")))
        await pilot.pause()

        body = app.screen.query_one("#save-diff-body", Static)
        assert "[mcp.servers." in str(body.render())


async def test_unresolved_var_chains_into_key_entry(tmp_path, monkeypatch):
    from agent86.tui.screens.key_entry import KeyEntryModal
    from agent86.tui.screens.mcp_manager import MCPServerFormModal

    monkeypatch.delenv("A86_TEST_TOKEN", raising=False)
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    fake = _FakeMCPManager()
    repl.harness.mcp = fake
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _open_mcp_manager(app, pilot)

        option_list = app.screen.query_one("#mcp-server-list", OptionList)
        option_list.highlighted = 0
        option_list.focus()
        await pilot.pause()
        await pilot.press("enter")
        await _wait_until(lambda: isinstance(app.screen, MCPServerFormModal))

        _fill_json_form(
            app.screen,
            "alpha",
            '{"url": "https://x/mcp", '
            '"headers": {"Authorization": "Bearer ${A86_TEST_TOKEN}"}}',
        )
        await pilot.pause()
        await pilot.click("#mcp-form-continue")
        await _wait_until(lambda: isinstance(app.screen, KeyEntryModal))

        await pilot.click("#key-input")
        for ch in "typed-value":
            await pilot.press(ch)
        await pilot.press("enter")
        await _wait_until(lambda: fake.start_calls)

    assert fake.start_calls[0]["overrides"] == {"A86_TEST_TOKEN": "typed-value"}


async def test_cancelling_key_entry_aborts_the_add(tmp_path, monkeypatch):
    from agent86.tui.screens.key_entry import KeyEntryModal
    from agent86.tui.screens.mcp_manager import MCPServerFormModal

    monkeypatch.delenv("A86_TEST_TOKEN", raising=False)
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    fake = _FakeMCPManager()
    repl.harness.mcp = fake
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _open_mcp_manager(app, pilot)

        option_list = app.screen.query_one("#mcp-server-list", OptionList)
        option_list.highlighted = 0
        option_list.focus()
        await pilot.pause()
        await pilot.press("enter")
        await _wait_until(lambda: isinstance(app.screen, MCPServerFormModal))

        _fill_json_form(
            app.screen,
            "alpha",
            '{"url": "https://x/mcp", '
            '"headers": {"Authorization": "Bearer ${A86_TEST_TOKEN}"}}',
        )
        await pilot.pause()
        await pilot.click("#mcp-form-continue")
        await _wait_until(lambda: isinstance(app.screen, KeyEntryModal))
        await pilot.press("escape")
        await pilot.pause()

    assert fake.start_calls == []


async def test_failed_test_without_override_never_opens_save_diff(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer
    from agent86.tui.screens.mcp_manager import MCPServerFormModal
    from agent86.tui.screens.mcp_test import MCPTestModal
    from agent86.tui.screens.save_diff import SaveDiffModal

    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", tmp_path / "config.toml")
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.mcp = _FakeMCPManager(fail="boom")
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _open_mcp_manager(app, pilot)

        option_list = app.screen.query_one("#mcp-server-list", OptionList)
        option_list.highlighted = 0
        option_list.focus()
        await pilot.pause()
        await pilot.press("enter")
        await _wait_until(lambda: isinstance(app.screen, MCPServerFormModal))

        _fill_json_form(
            app.screen, "alpha", '{"command": "npx", "args": ["-y", "alpha-server"]}'
        )
        await pilot.pause()
        await pilot.click("#mcp-form-continue")
        await _wait_until(lambda: isinstance(app.screen, MCPTestModal))
        await _wait_for_mcp_test_ready(app, pilot)
        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app.screen, SaveDiffModal)


async def test_cancelling_save_diff_stops_the_started_server(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer
    from agent86.tui.screens.mcp_manager import MCPServerFormModal
    from agent86.tui.screens.mcp_test import MCPTestModal
    from agent86.tui.screens.save_diff import SaveDiffModal

    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", tmp_path / "config.toml")
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    fake = _FakeMCPManager()
    repl.harness.mcp = fake
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _open_mcp_manager(app, pilot)

        option_list = app.screen.query_one("#mcp-server-list", OptionList)
        option_list.highlighted = 0
        option_list.focus()
        await pilot.pause()
        await pilot.press("enter")
        await _wait_until(lambda: isinstance(app.screen, MCPServerFormModal))

        _fill_json_form(
            app.screen, "alpha", '{"command": "npx", "args": ["-y", "alpha-server"]}'
        )
        await pilot.pause()
        await pilot.click("#mcp-form-continue")
        await _wait_until(lambda: isinstance(app.screen, MCPTestModal))
        await _wait_for_mcp_test_ready(app, pilot)
        await pilot.pause()
        await pilot.click("#mcp-test-continue")
        await _wait_until(lambda: isinstance(app.screen, SaveDiffModal))
        await pilot.press("escape")
        await pilot.pause()

    assert fake.stop_calls == ["alpha"]


async def test_confirmed_save_mounts_tools_live(tmp_path, monkeypatch):
    import agent86.config_writer as config_writer
    from agent86.tui.screens.mcp_manager import MCPServerFormModal
    from agent86.tui.screens.mcp_test import MCPTestModal
    from agent86.tui.screens.save_diff import SaveDiffModal

    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", tmp_path / "config.toml")
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.mcp = _FakeMCPManager()
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _open_mcp_manager(app, pilot)

        option_list = app.screen.query_one("#mcp-server-list", OptionList)
        option_list.highlighted = 0
        option_list.focus()
        await pilot.pause()
        await pilot.press("enter")
        await _wait_until(lambda: isinstance(app.screen, MCPServerFormModal))

        _fill_json_form(
            app.screen, "alpha", '{"command": "npx", "args": ["-y", "alpha-server"]}'
        )
        await pilot.pause()
        await pilot.click("#mcp-form-continue")
        await _wait_until(lambda: isinstance(app.screen, MCPTestModal))
        await _wait_for_mcp_test_ready(app, pilot)
        await pilot.pause()
        await pilot.click("#mcp-test-continue")
        await _wait_until(lambda: isinstance(app.screen, SaveDiffModal))
        await _wait_until(lambda: bool(app.screen.query("#save-confirm")))
        await pilot.pause()
        await pilot.click("#save-confirm")
        await pilot.pause()

    names = repl.harness.registry.names()
    assert "mcp__alpha__search" in names
    assert "mcp__alpha__fetch" in names


async def test_mount_failure_after_successful_save_reports_both(tmp_path, monkeypatch):
    """The `override` path (D-13): the test failed but was saved anyway, so nothing is mounted."""
    import agent86.config_writer as config_writer
    from agent86.tui.screens.mcp_manager import MCPServerFormModal
    from agent86.tui.screens.mcp_test import MCPTestModal
    from agent86.tui.screens.save_diff import SaveDiffModal

    monkeypatch.setattr(config_writer, "USER_CONFIG_PATH", tmp_path / "config.toml")
    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    repl.harness.mcp = _FakeMCPManager(fail="boom")
    app = Agent86App(repl)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        await _open_mcp_manager(app, pilot)

        option_list = app.screen.query_one("#mcp-server-list", OptionList)
        option_list.highlighted = 0
        option_list.focus()
        await pilot.pause()
        await pilot.press("enter")
        await _wait_until(lambda: isinstance(app.screen, MCPServerFormModal))

        _fill_json_form(
            app.screen, "alpha", '{"command": "npx", "args": ["-y", "alpha-server"]}'
        )
        await pilot.pause()
        await pilot.click("#mcp-form-continue")
        await _wait_until(lambda: isinstance(app.screen, MCPTestModal))
        await _wait_for_mcp_test_ready(app, pilot)
        await pilot.pause()
        await pilot.click("#mcp-save-anyway")
        await _wait_until(lambda: isinstance(app.screen, SaveDiffModal))
        await _wait_until(lambda: bool(app.screen.query("#save-confirm")))
        await pilot.pause()
        await pilot.click("#save-confirm")
        await pilot.pause()

        transcript = app.query_one("#transcript", RichLog)
        lines = "\n".join(str(line) for line in transcript.lines)
    assert "available next launch" in lines


async def test_headers_are_written_as_individual_key_paths(tmp_path):
    from agent86.config import MCPServerConfig
    from agent86.tui.screens.mcp_manager import MCPServerDraft

    repl = _make_repl(tmp_path, make_text_provider("hello world"))
    app = Agent86App(repl)
    draft = MCPServerDraft(
        name="alpha",
        cfg=MCPServerConfig(
            url="https://x/mcp", headers={"Authorization": "Bearer ${A86_TEST_TOKEN}"}
        ),
    )
    changes = app._mcp_changes(draft)
    assert (["mcp", "servers", "alpha", "headers", "Authorization"], "Bearer ${A86_TEST_TOKEN}") in changes
    assert not any(path == ["mcp", "servers", "alpha", "headers"] for path, _ in changes)
