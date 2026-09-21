"""Flight-data recorder (Tier 5).

Append-only JSONL trace of everything the harness does — turn boundaries, model calls,
tool calls, guardrail hits, and errors — each tagged with the session id. Local, greppable,
and always available (no collector needed). ``agent86 trace show`` reads it back.

Two properties make it safe to leave on forever:

* **Redacted** — every event goes through :mod:`agent86.observability.redact` first, so
  secret-shaped values never reach the file and huge observations are clipped.
* **Rotated** — the live file is capped at ``[observability] max_trace_bytes``; crossing it
  shifts ``trace.jsonl`` to ``trace.1.jsonl`` … ``trace.N.jsonl`` and drops the oldest.
  Rotation happens *between* events (flush, then rename), so no event is ever half-written.

:func:`read_events` streams rather than slurping — it keeps at most ``limit`` records in
memory and walks the rotated generations newest-first when the tail of the live file does
not hold enough matching events.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

from agent86.config import Config
from agent86.observability.redact import DEFAULT_MAX_FIELD_CHARS, redact_event

#: Cap on the live trace file; mirrors ``ObservabilityConfig.max_trace_bytes``.
DEFAULT_MAX_TRACE_BYTES = 50_000_000
#: How many rotated generations to keep; mirrors ``ObservabilityConfig.keep_traces``.
DEFAULT_KEEP_TRACES = 5


def rotated_path(path: Path, index: int) -> Path:
    """``trace.jsonl`` + 2 → ``trace.2.jsonl`` (generation 1 is the most recent)."""
    return path.with_name(f"{path.stem}.{index}{path.suffix}")


def _replace(src: Path, dst: Path, attempts: int = 5) -> bool:
    """``os.replace`` with retries.

    On Windows a rename fails with ``PermissionError`` while another process (a tail, an
    editor, an antivirus scanner) still holds the file open. Retrying briefly clears the
    common case; giving up is fine — the caller keeps appending to the current file and
    tries again on the next crossing.
    """
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            if attempt == attempts - 1:
                return False
            time.sleep(0.05 * (attempt + 1))
    return False


class Recorder:
    """Append-only JSONL writer for harness events.

    Every event passes through :func:`~agent86.observability.redact.redact_event` before it
    reaches the file, so a key pasted into a prompt or read out of a file by a tool never
    lands on disk (``[observability] redact``). Writing is best-effort by design: an event
    that cannot be serialised or a file that cannot be written is dropped silently rather
    than raising into the ReAct loop, because observability must never be the reason a turn
    fails.
    """

    def __init__(
        self,
        path: Path | None,
        *,
        redact: str = "secrets",
        max_field_chars: int = DEFAULT_MAX_FIELD_CHARS,
        max_bytes: int = DEFAULT_MAX_TRACE_BYTES,
        keep: int = DEFAULT_KEEP_TRACES,
    ):
        self.path = path
        self.enabled = path is not None
        self.redact = str(redact)
        self.max_field_chars = max_field_chars
        self.max_bytes = max_bytes
        self.keep = keep
        self._fh: TextIO | None = None
        self._size = 0
        if self.enabled and path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Rotate on open: a process that died over the cap must not append to an
            # already-oversized file for the whole of the next session.
            if self.max_bytes > 0 and self._file_size(path) >= self.max_bytes:
                self._rotate_files()
            self._open()

    # ---- file handling -------------------------------------------------- #

    @staticmethod
    def _file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def _open(self) -> None:
        assert self.path is not None
        self._fh = self.path.open("a", encoding="utf-8")
        self._size = self._file_size(self.path)

    def _rotate_files(self) -> None:
        """Shift the generations down and drop the oldest. The live file must be closed."""
        path = self.path
        if path is None:
            return
        keep = max(0, self.keep)
        if keep == 0:
            # No history wanted: the live file is simply discarded on crossing.
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return
        oldest = rotated_path(path, keep)
        try:
            oldest.unlink(missing_ok=True)
        except OSError:
            pass
        for index in range(keep - 1, 0, -1):
            src = rotated_path(path, index)
            if src.exists():
                _replace(src, rotated_path(path, index + 1))
        if path.exists():
            _replace(path, rotated_path(path, 1))

    def _rotate(self) -> None:
        """Close, rotate, reopen. Called only *between* events, never mid-write."""
        if self._fh is not None:
            try:
                self._fh.flush()
                self._fh.close()
            except OSError:
                pass
            self._fh = None
        self._rotate_files()
        try:
            self._open()
        except OSError:  # pragma: no cover - defensive: keep the harness alive
            self._fh = None

    # ---- the write path ------------------------------------------------- #

    def event(self, session_id: str, kind: str, **data: object) -> None:
        if not self._fh:
            return
        try:
            record = {"ts": time.time(), "session": session_id, "kind": kind, **data}
            record = redact_event(
                record, mode=self.redact, max_field_chars=self.max_field_chars
            )
            line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
            self._fh.write(line)
            self._fh.flush()
            self._size += len(line.encode("utf-8"))
        except Exception:  # pragma: no cover - the loop must never die for a trace line
            return
        # Crossing the cap rotates for the NEXT event: this one is already safely on disk.
        if self.max_bytes > 0 and self._size >= self.max_bytes:
            try:
                self._rotate()
            except Exception:  # pragma: no cover - defensive
                return

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


def build_recorder(config: Config) -> Recorder:
    obs = config.observability
    if not obs.trace:
        return Recorder(None)
    return Recorder(
        obs.resolved_path() / "trace.jsonl",
        redact=str(obs.redact),
        max_field_chars=obs.max_field_chars,
        max_bytes=obs.max_trace_bytes,
        keep=obs.keep_traces,
    )


# --------------------------------------------------------------------------- #
# Reading back
# --------------------------------------------------------------------------- #


def trace_generations(path: Path, keep: int = DEFAULT_KEEP_TRACES) -> list[Path]:
    """Existing trace files, newest first: the live file, then ``trace.1`` … ``trace.N``."""
    files = [path] if path.exists() else []
    for index in range(1, max(0, keep) + 1):
        candidate = rotated_path(path, index)
        if candidate.exists():
            files.append(candidate)
    return files


def iter_events(path: Path) -> Iterator[dict]:
    """Stream one trace file's records, skipping blank and malformed lines."""
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def read_events(
    path: Path,
    session_id: str | None = None,
    limit: int = 50,
    keep: int = DEFAULT_KEEP_TRACES,
) -> list[dict]:
    """Read the tail of the trace, optionally filtered to one session.

    Streams: at most ``limit`` records are held at a time, so a multi-gigabyte trace costs
    the same memory as a small one. When the live file does not hold ``limit`` matching
    events — which is the normal case once a session's events have rotated out — the older
    generations are walked newest-first until the budget is filled. Results stay in
    chronological order.
    """
    if limit <= 0:
        return []
    events: list[dict] = []
    for generation in trace_generations(path, keep):
        remaining = limit - len(events)
        if remaining <= 0:
            break
        chunk: deque[dict] = deque(maxlen=remaining)
        for record in iter_events(generation):
            if session_id and record.get("session") != session_id:
                continue
            chunk.append(record)
        events = list(chunk) + events
    return events


__all__ = [
    "DEFAULT_KEEP_TRACES",
    "DEFAULT_MAX_TRACE_BYTES",
    "Recorder",
    "build_recorder",
    "iter_events",
    "read_events",
    "rotated_path",
    "trace_generations",
]
