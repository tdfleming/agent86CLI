"""v0.2 UI — the threaded spinner clears exactly what it drew (no leftover artifacts)."""

from __future__ import annotations

import io
import sys
import time

from agent86.ui.spinner import Spinner


def test_spinner_disabled_off_tty_is_noop(monkeypatch):
    buf = io.StringIO()  # not a TTY
    monkeypatch.setattr(sys, "stdout", buf)
    sp = Spinner(interval=0.01)  # __init__ reads isatty() -> False
    sp.start("thinking")
    sp.stop()
    assert buf.getvalue() == ""  # nothing drawn when output isn't a terminal


def test_spinner_clears_exactly_what_it_drew(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    sp = Spinner(interval=0.01)
    sp._enabled = True  # force on (a StringIO reports isatty() == False)
    sp.start("running remember")
    time.sleep(0.05)  # let a few frames draw
    sp.stop()

    out = buf.getvalue()
    assert "running remember…" in out  # label was drawn
    # The final act is a clear: carriage return, spaces, carriage return.
    assert out.endswith("\r")
    trailing_spaces = len(out[:-1]) - len(out[:-1].rstrip(" "))
    # drawn width = braille(1) + space(1) + label + "…"(1) + space(1)
    assert trailing_spaces == len("running remember") + 4
