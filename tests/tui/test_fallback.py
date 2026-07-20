"""Routing + graceful-fallback behavior of ``run_repl`` (Plan 01-05, TUI-01).

Covers: ``--plain`` skips the TUI entirely, a TUI import/start failure falls back to the
plain loop with a dim note (no exception propagates), and importing ``agent86.ui.repl``
never pulls in ``textual``.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import agent86.ui.repl as repl_mod
from agent86.config import load_config


class _PlainLoopSpy:
    """Stand-in for ``_Repl`` that records whether ``plain_loop`` ran."""

    def __init__(self, cfg, resume, harness=None):  # noqa: ANN001
        self.ran_plain_loop = False

    def print_notes(self) -> None:
        pass

    def plain_loop(self) -> None:
        self.ran_plain_loop = True


@pytest.fixture
def cfg():
    return load_config()


def test_plain_flag_skips_tui(monkeypatch, cfg):
    spy_holder: dict = {}

    def _make_spy(c, resume, harness=None):  # noqa: ANN001
        spy = _PlainLoopSpy(c, resume, harness)
        spy_holder["spy"] = spy
        return spy

    tui_called = {"called": False}

    def _fake_run_tui(cfg, resume=None):  # noqa: ANN001
        tui_called["called"] = True

    monkeypatch.setattr(repl_mod, "_Repl", _make_spy)
    monkeypatch.setitem(
        sys.modules,
        "agent86.tui.app",
        type(sys)("agent86.tui.app"),
    )
    sys.modules["agent86.tui.app"].run_tui = _fake_run_tui

    repl_mod.run_repl(cfg, plain=True)

    assert spy_holder["spy"].ran_plain_loop is True
    assert tui_called["called"] is False


def test_tui_start_failure_falls_back(monkeypatch, cfg):
    spy_holder: dict = {}

    def _make_spy(c, resume, harness=None):  # noqa: ANN001
        spy = _PlainLoopSpy(c, resume, harness)
        spy_holder["spy"] = spy
        return spy

    def _raising_run_tui(cfg, resume=None):  # noqa: ANN001
        raise RuntimeError("no tty")

    monkeypatch.setattr(repl_mod, "_Repl", _make_spy)
    monkeypatch.setattr(repl_mod, "_use_rich", lambda cfg, plain: True)
    fake_module = type(sys)("agent86.tui.app")
    fake_module.run_tui = _raising_run_tui
    monkeypatch.setitem(sys.modules, "agent86.tui.app", fake_module)

    repl_mod.run_repl(cfg)  # must not raise

    assert spy_holder["spy"].ran_plain_loop is True


def test_tui_import_failure_falls_back(monkeypatch, cfg):
    spy_holder: dict = {}

    def _make_spy(c, resume, harness=None):  # noqa: ANN001
        spy = _PlainLoopSpy(c, resume, harness)
        spy_holder["spy"] = spy
        return spy

    monkeypatch.setattr(repl_mod, "_Repl", _make_spy)
    monkeypatch.setattr(repl_mod, "_use_rich", lambda cfg, plain: True)
    # Force the lazy `from agent86.tui.app import run_tui` to raise ImportError.
    monkeypatch.delitem(sys.modules, "agent86.tui.app", raising=False)

    real_import = __import__

    def _failing_import(name, *args, **kwargs):
        if name == "agent86.tui.app":
            raise ImportError("simulated missing textual")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _failing_import)

    repl_mod.run_repl(cfg)  # must not raise

    assert spy_holder["spy"].ran_plain_loop is True


def test_repl_module_import_is_textual_free():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, agent86.ui.repl; assert 'textual' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
