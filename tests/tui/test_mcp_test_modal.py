"""`MCPTestModal` Pilot tests (D-18/D-19/D-20).

Implemented by plan 04-07. Mirrors `tests/tui/test_connection_test.py`: a `_PickerHost` pushes
the modal, a fake manager stands in for the real `MCPManager` so no subprocess is ever spawned,
and the modal's dismissal value is the assertion surface.
"""

from __future__ import annotations

import threading

from textual.app import App, ComposeResult
from textual.widgets import Static

from agent86.config import MCPServerConfig


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


class _FakeTool:
    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description


class _FakeManager:
    """Stands in for `MCPManager`: records how `start_server` was called, never spawns."""

    def __init__(self, *, tools=None, error=None, block_event=None) -> None:
        self._tools = tools or []
        self._error = error
        self._block_event = block_event
        self.calls: list[dict] = []

    def start_server(self, name, cfg, timeout=30.0, overrides=None):
        self.calls.append({"name": name, "timeout": timeout, "overrides": overrides})
        if self._block_event is not None:
            self._block_event.wait(5)
        if self._error is not None:
            raise self._error
        return list(self._tools)

    def stop_server(self, name, timeout=10.0):
        return None


def _cfg() -> MCPServerConfig:
    return MCPServerConfig(command="npx", args=["-y", "srv"])


async def _settle(host, pilot, tries: int = 30) -> None:
    for _ in range(tries):
        if host.result != "__unset__":
            return
        await pilot.pause(0.1)


async def test_mcp_test_modal_lists_tool_names_on_success():
    """D-19: a successful test shows what the server actually offers before anything is saved."""
    from agent86.tui.screens.mcp_test import MCPTestModal, MCPTestOutcome

    tools = [_FakeTool("mcp__a__add", "adds"), _FakeTool("mcp__a__shout", "shouts")]
    manager = _FakeManager(tools=tools)
    host = _PickerHost(MCPTestModal(manager, "a", _cfg()))
    async with host.run_test() as pilot:
        await pilot.pause()
        for _ in range(30):
            try:
                rendered = str(host.screen.query_one("#mcp-test-tools", Static).render())
            except Exception:
                rendered = ""
            if "mcp__a__add" in rendered:
                break
            await pilot.pause(0.1)
        assert "mcp__a__add" in rendered
        assert "mcp__a__shout" in rendered
        assert "2 tools" in rendered
        await pilot.click("#mcp-test-continue")
        await pilot.pause()
    assert host.result == MCPTestOutcome(
        ok=True,
        tools=(("mcp__a__add", "adds"), ("mcp__a__shout", "shouts")),
    )


async def test_mcp_test_modal_default_timeout_is_30s():
    """D-20: MCP servers can be slow to cold-start (npx/uvx download) — 30s, not the 10s
    used for a plain HTTP model ping."""
    from agent86.tui.screens.mcp_test import MCPTestModal

    assert MCPTestModal.TIMEOUT_S == 30.0


async def test_mcp_test_modal_times_out_and_dismisses(monkeypatch):
    from agent86.tui.screens.mcp_test import MCPTestModal

    monkeypatch.setattr(MCPTestModal, "TIMEOUT_S", 0.1)
    block_event = threading.Event()
    manager = _FakeManager(block_event=block_event)
    host = _PickerHost(MCPTestModal(manager, "a", _cfg()))
    async with host.run_test() as pilot:
        await pilot.pause()
        await _settle(host, pilot)
    assert host.result.ok is False
    assert host.result.override is False
    assert "Timed out" in host.result.error


async def test_mcp_test_modal_failure_offers_save_anyway():
    from agent86.tui.screens.mcp_test import MCPTestModal, MCPTestOutcome

    manager = _FakeManager(error=RuntimeError("boom"))
    host = _PickerHost(MCPTestModal(manager, "a", _cfg()))
    async with host.run_test() as pilot:
        await pilot.pause()
        for _ in range(30):
            try:
                if host.screen.query_one("#mcp-test-buttons").display:
                    break
            except Exception:
                pass
            await pilot.pause(0.1)
        await pilot.click("#mcp-save-anyway")
        await pilot.pause()
    assert "boom" in host.result.error
    assert host.result == MCPTestOutcome(ok=False, override=True, error=host.result.error)


async def test_mcp_test_modal_escape_dismisses_explicitly():
    from agent86.tui.screens.mcp_test import MCPTestModal

    block_event = threading.Event()
    manager = _FakeManager(block_event=block_event)
    host = _PickerHost(MCPTestModal(manager, "a", _cfg()))
    async with host.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert host.result.ok is False
    assert host.result.override is False


async def test_mcp_test_modal_passes_overrides_to_start_server():
    """D-18: a ${VAR} typed into the form reaches the live start without being persisted."""
    from agent86.tui.screens.mcp_test import MCPTestModal

    manager = _FakeManager(tools=[_FakeTool("mcp__a__add", "adds")])
    host = _PickerHost(
        MCPTestModal(manager, "a", _cfg(), overrides={"GITHUB_TOKEN": "typed"})
    )
    async with host.run_test() as pilot:
        await pilot.pause()
        for _ in range(30):
            if manager.calls:
                break
            await pilot.pause(0.1)
    assert manager.calls
    assert manager.calls[0]["overrides"] == {"GITHUB_TOKEN": "typed"}
