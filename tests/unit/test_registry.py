"""v0.7 — startup tool-name collisions are recorded and logged, not silently swallowed."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from agent86.config import load_config
from agent86.tools.base import Tool, ToolContext
from agent86.tools.registry import ToolRegistry, default_registry
from agent86.types import ToolResult


class _Stub(Tool["_Stub.Args"]):
    class Args(BaseModel):
        pass

    def __init__(self, name: str):
        self.name = name
        self.description = f"stub {name}"

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:  # pragma: no cover
        return ToolResult(call_id="", name=self.name, content="")


def test_registry_starts_with_no_collisions():
    assert ToolRegistry().collisions == []


def test_try_register_records_and_logs_a_collision(caplog):
    registry = ToolRegistry()
    assert registry.try_register(_Stub("search")) is True

    with caplog.at_level(logging.WARNING, logger="agent86.tools.registry"):
        assert registry.try_register(_Stub("search")) is False

    assert registry.collisions == ["search"]
    assert "search" in caplog.text and "not callable" in caplog.text
    assert registry.names().count("search") == 1


def test_collision_warning_mentions_name_truncation(caplog):
    long_name = "mcp__server__" + "t" * 60
    long_name = long_name[:64]
    registry = ToolRegistry()
    registry.try_register(_Stub(long_name))
    with caplog.at_level(logging.WARNING, logger="agent86.tools.registry"):
        registry.try_register(_Stub(long_name))
    assert "truncated to 64 characters" in caplog.text


def test_default_registry_reports_mcp_tools_it_could_not_mount(caplog):
    cfg = load_config()
    tools = [_Stub("mcp__a__search"), _Stub("mcp__a__search"), _Stub("read_file")]

    with caplog.at_level(logging.WARNING, logger="agent86.tools.registry"):
        registry = default_registry(cfg, mcp_tools=tools)

    # The duplicate across servers and the one shadowing a built-in are both reported.
    assert registry.collisions == ["mcp__a__search", "read_file"]
    assert "mcp__a__search" in caplog.text
    assert "read_file" in caplog.text
    # ...and the first registration of each name still won.
    assert registry.get("mcp__a__search") is tools[0]
    assert registry.get("read_file") is not tools[2]


def test_default_registry_has_no_collisions_for_distinct_names():
    registry = default_registry(load_config(), mcp_tools=[_Stub("mcp__a__x"), _Stub("mcp__b__x")])
    assert registry.collisions == []
    assert {"mcp__a__x", "mcp__b__x"}.issubset(set(registry.names()))
