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
from agent86.observability.redact import DEFAULT_MAX_FIELD_CHARS, redact_event


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
    ):
        self.path = path
        self.enabled = path is not None
        self.redact = str(redact)
        self.max_field_chars = max_field_chars
        self._fh = None
        if self.enabled and path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = path.open("a", encoding="utf-8")

    def event(self, session_id: str, kind: str, **data: object) -> None:
        if not self._fh:
            return
        try:
            record = {"ts": time.time(), "session": session_id, "kind": kind, **data}
            record = redact_event(
                record, mode=self.redact, max_field_chars=self.max_field_chars
            )
            self._fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()
        except Exception:  # pragma: no cover - the loop must never die for a trace line
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
    )


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
