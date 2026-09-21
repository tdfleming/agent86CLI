"""Episodic memory (Pillar 2) — the flight data recorder.

Records one episode per completed turn (task -> outcome). When a new task begins, the harness
recalls the most similar past episodes and injects them as context, so the agent benefits from
(or is warned by) what happened last time — the book's episodic-reflection pattern.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from agent86.memory.store import Hit, MemoryStore, SessionInfo
from agent86.types import Message

# Only surface recalled episodes above this cosine similarity — avoids noise from
# unrelated past tasks.
_MIN_SCORE = 0.35

#: ``metadata["kind"]`` of an episode that is an archived compacted span rather than a turn.
#: Held out of recall: replaying a raw transcript into a new turn's context is the opposite
#: of what compaction is for.
COMPACTION_KIND = "compaction"


class EpisodicMemory:
    def __init__(self, store: MemoryStore):
        self.store = store

    def record_turn(
        self, session_id: str, task: str, outcome: str, metadata: dict | None = None
    ) -> int:
        return self.store.add_episode(session_id, task, outcome, metadata)

    def record_compaction(
        self, session_id: str, summary: str, dropped: Sequence[Message]
    ) -> int:
        """Archive the raw messages a compaction replaced, alongside the summary that replaced
        them.

        Compaction shrinks *working* memory; it must not destroy the record. The originals go
        to the flight recorder verbatim (JSON, resurrectable), so `agent86 trace`/`memory`
        can still answer "what did it actually say back then" after the live conversation has
        moved on. Tagged ``kind="compaction"`` so :meth:`recall` skips it.
        """
        payload = json.dumps(
            [m.model_dump(mode="json") for m in dropped], ensure_ascii=False, default=str
        )
        return self.store.add_episode(
            session_id,
            f"[compacted {len(dropped)} messages] {summary}",
            payload,
            {"kind": COMPACTION_KIND, "dropped": len(dropped), "summary": summary},
        )

    # ---- session listing ---------------------------------------------- #

    def recent_sessions(self, limit: int = 20) -> list[SessionInfo]:
        """The sessions a user can go back to, newest first.

        The flight recorder's other half: :meth:`recall` answers "what happened in a turn
        like this one", this answers "what were we working on" — the list behind
        ``/sessions``, ``/resume`` and the session picker.
        """
        return self.store.recent_sessions(limit)

    def session_title(self, session_id: str) -> str | None:
        """The stored name of one session, or None if it never got one."""
        return self.store.session_title(session_id)

    def recall(self, task: str, k: int = 3, min_score: float = _MIN_SCORE) -> list[Hit]:
        return [
            h
            for h in self.store.search_episodes(task, k)
            if h.score >= min_score and h.metadata.get("kind") != COMPACTION_KIND
        ]

    def recall_note(self, task: str, k: int = 3) -> str | None:
        """A compact system-context note summarizing relevant past turns, or None."""
        hits = self.recall(task, k)
        if not hits:
            return None
        lines = ["Relevant past experience (from memory; may help or warn):"]
        for h in hits:
            outcome = " ".join((h.metadata.get("outcome") or "").split())
            if len(outcome) > 200:
                outcome = outcome[:200] + " ..."
            lines.append(f"- task: {h.text!r} -> {outcome}")
        return "\n".join(lines)


__all__ = ["COMPACTION_KIND", "EpisodicMemory"]
