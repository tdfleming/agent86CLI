"""Routing + graceful-fallback behavior of ``run_repl`` (Plan 01-05, TUI-01).

Covers: ``--plain`` skips the TUI entirely, the TUI receives the already-built ``_Repl``
(one harness per process), a TUI import/start failure falls back to the plain loop with a
dim note (no exception propagates), and importing ``agent86.ui.repl`` never pulls in
``textual``.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import agent86.ui.repl as repl_mod
from agent86.config import load_config


class _PlainLoopSpy:
    """Stand-in for ``_Repl`` that records whether ``plain_loop`` / ``print_notes`` ran."""

    def __init__(self, cfg, resume, harness=None):  # noqa: ANN001
        self.ran_plain_loop = False
        self.printed_notes = False
        self.startup_notes: list[str] = ["session abc123"]

    def print_notes(self) -> None:
        self.printed_notes = True

    def plain_loop(self) -> None:
        self.ran_plain_loop = True


@pytest.fixture
def cfg():
    return load_config()


def _patch_repl(monkeypatch) -> dict:
    """Swap ``_Repl`` for a spy; returns the holder the spy lands in."""
    holder: dict = {}

    def _make_spy(c, resume, harness=None):  # noqa: ANN001
        spy = _PlainLoopSpy(c, resume, harness)
        holder["spy"] = spy
        return spy

    monkeypatch.setattr(repl_mod, "_Repl", _make_spy)
    return holder


def _install_fake_tui(monkeypatch, run_tui) -> None:
    fake_module = type(sys)("agent86.tui.app")
    fake_module.run_tui = run_tui
    monkeypatch.setitem(sys.modules, "agent86.tui.app", fake_module)


def test_plain_flag_skips_tui(monkeypatch, cfg):
    holder = _patch_repl(monkeypatch)
    tui_called = {"called": False}

    def _fake_run_tui(repl):  # noqa: ANN001
        tui_called["called"] = True

    _install_fake_tui(monkeypatch, _fake_run_tui)

    repl_mod.run_repl(cfg, plain=True)

    assert holder["spy"].ran_plain_loop is True
    assert tui_called["called"] is False


def test_tui_receives_the_already_built_repl(monkeypatch, cfg):
    """``run_tui(repl)`` — the harness is constructed once, in ``run_repl``."""
    holder = _patch_repl(monkeypatch)
    seen: dict = {}

    def _fake_run_tui(repl):  # noqa: ANN001
        seen["repl"] = repl

    monkeypatch.setattr(repl_mod, "_use_tui", lambda cfg, plain: True)
    _install_fake_tui(monkeypatch, _fake_run_tui)

    repl_mod.run_repl(cfg)

    assert seen["repl"] is holder["spy"]
    assert holder["spy"].ran_plain_loop is False  # the TUI ran; no fallback


def test_tui_path_prints_no_banner_or_notes(monkeypatch, cfg, capsys):
    """They'd land behind the alternate screen; the TUI renders `startup_notes` instead."""
    holder = _patch_repl(monkeypatch)
    monkeypatch.setattr(repl_mod, "_use_tui", lambda cfg, plain: True)
    _install_fake_tui(monkeypatch, lambda repl: None)  # noqa: ARG005

    repl_mod.run_repl(cfg)

    assert capsys.readouterr().out.strip() == ""
    assert holder["spy"].printed_notes is False


def test_plain_path_prints_banner_and_notes(monkeypatch, cfg, capsys):
    holder = _patch_repl(monkeypatch)
    # capsys's captured stdout is never a real terminal (isatty() is False); force it so this
    # test exercises the normal interactive case, distinct from the non-TTY suppression below.
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    repl_mod.run_repl(cfg, plain=True)

    assert "agent86" in capsys.readouterr().out  # the banner panel
    assert holder["spy"].printed_notes is True


def test_tui_failure_fallback_still_prints_banner_and_notes(monkeypatch, cfg, capsys):
    holder = _patch_repl(monkeypatch)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    def _raising_run_tui(repl):  # noqa: ANN001
        raise RuntimeError("no tty")

    monkeypatch.setattr(repl_mod, "_use_tui", lambda cfg, plain: True)
    _install_fake_tui(monkeypatch, _raising_run_tui)

    repl_mod.run_repl(cfg)

    assert "agent86" in capsys.readouterr().out
    assert holder["spy"].printed_notes is True


def test_plain_path_suppresses_the_banner_when_stdout_is_not_a_tty(monkeypatch, cfg, capsys):
    """`echo hi | agent86` — a non-TTY stdout must not get the decorative panel ahead of the
    answer, even though the notes (memory/mcp/sandbox/session) still print."""
    holder = _patch_repl(monkeypatch)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    repl_mod.run_repl(cfg, plain=True)

    out = capsys.readouterr().out
    assert "Type /help for commands" not in out
    assert "╭" not in out
    assert holder["spy"].printed_notes is True


def test_tui_start_failure_falls_back(monkeypatch, cfg):
    holder = _patch_repl(monkeypatch)

    def _raising_run_tui(repl):  # noqa: ANN001
        raise RuntimeError("no tty")

    monkeypatch.setattr(repl_mod, "_use_tui", lambda cfg, plain: True)
    _install_fake_tui(monkeypatch, _raising_run_tui)

    repl_mod.run_repl(cfg)  # must not raise

    assert holder["spy"].ran_plain_loop is True


def test_tui_import_failure_falls_back(monkeypatch, cfg):
    holder = _patch_repl(monkeypatch)
    monkeypatch.setattr(repl_mod, "_use_tui", lambda cfg, plain: True)
    # Force the lazy `from agent86.tui.app import run_tui` to raise ImportError.
    monkeypatch.delitem(sys.modules, "agent86.tui.app", raising=False)

    real_import = __import__

    def _failing_import(name, *args, **kwargs):
        if name == "agent86.tui.app":
            raise ImportError("simulated missing textual")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _failing_import)

    repl_mod.run_repl(cfg)  # must not raise

    assert holder["spy"].ran_plain_loop is True


def test_use_tui_honours_config_and_plain_flag(cfg):
    cfg.ui.tui = False
    assert repl_mod._use_tui(cfg, plain=False) is False
    cfg.ui.tui = True
    assert repl_mod._use_tui(cfg, plain=True) is False


def test_use_tui_respects_agent86_plain_env(monkeypatch, cfg):
    monkeypatch.setenv("AGENT86_PLAIN", "1")
    assert repl_mod._use_tui(cfg, plain=False) is False


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


def test_command_registry_import_is_textual_free():
    """The plain loop dispatches through `agent86.tui.commands`; it must stay Textual-free."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, agent86.tui.commands; "
            "assert 'textual' not in sys.modules, 'textual imported eagerly'",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
