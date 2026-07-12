"""A minimal threaded terminal spinner (v0.2).

Animates a single line to show the agent is working during dead air (model latency, tool
execution). It only runs while explicitly started and always clears its line on stop, so the
caller can print streamed output on a clean line. Not shown when output isn't a TTY.
"""

from __future__ import annotations

import sys
import threading

_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Spinner:
    def __init__(self, interval: float = 0.1):
        self._interval = interval
        self._label = "thinking"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._enabled = sys.stdout.isatty()

    def start(self, label: str = "thinking") -> None:
        if not self._enabled or self._thread is not None:
            return
        self._label = label
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        i = 0
        drawn = 0
        while not self._stop.is_set():
            frame = f"{_FRAMES[i % len(_FRAMES)]} {self._label}… "
            sys.stdout.write("\r" + frame)
            sys.stdout.flush()
            drawn = len(frame)
            i += 1
            self._stop.wait(self._interval)
        # Clear exactly what was drawn (label length can change between runs), then
        # return to column 0 so the caller prints on a clean line.
        sys.stdout.write("\r" + " " * drawn + "\r")
        sys.stdout.flush()

    def stop(self) -> None:
        if self._thread is not None:
            self._stop.set()
            self._thread.join()
            self._thread = None


__all__ = ["Spinner"]
