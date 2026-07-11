"""Flight-data recorder (Tier 5).

Append-only JSONL trace of everything the harness does — turn boundaries, model calls,
tool calls, guardrail hits, and errors — each tagged with the session id. Local, greppable,
and always available (no collector needed). ``agent86 trace show`` reads it back.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from agent86.config import Config


class Recorder:
    def __init__(self, path: Path | None):
        self.path = path
        self.enabled = path is not None
        self._fh = None
        if self.enabled and path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = path.open("a", encoding="utf-8")

    def event(self, session_id: str, kind: str, **data: object) -> None:
        if not self._fh:
            return
        record = {"ts": time.time(), "session": session_id, "kind": kind, **data}
        self._fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


def build_recorder(config: Config) -> Recorder:
    if not config.observability.trace:
        return Recorder(None)
    return Recorder(config.observability.resolved_path() / "trace.jsonl")


def read_events(
    path: Path, session_id: str | None = None, limit: int = 50
) -> list[dict]:
    """Read the tail of the trace, optionally filtered to one session."""
    if not path.exists():
        return []
    events: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if session_id and rec.get("session") != session_id:
                continue
            events.append(rec)
    return events[-limit:]


__all__ = ["Recorder", "build_recorder", "read_events"]
