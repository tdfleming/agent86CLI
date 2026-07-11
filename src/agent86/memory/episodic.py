"""Episodic memory (Pillar 2) — the flight data recorder.

Records one episode per completed turn (task -> outcome). When a new task begins, the harness
recalls the most similar past episodes and injects them as context, so the agent benefits from
(or is warned by) what happened last time — the book's episodic-reflection pattern.
"""

from __future__ import annotations

from agent86.memory.store import Hit, MemoryStore

# Only surface recalled episodes above this cosine similarity — avoids noise from
# unrelated past tasks.
_MIN_SCORE = 0.35


class EpisodicMemory:
    def __init__(self, store: MemoryStore):
        self.store = store

    def record_turn(
        self, session_id: str, task: str, outcome: str, metadata: dict | None = None
    ) -> int:
        return self.store.add_episode(session_id, task, outcome, metadata)

    def recall(self, task: str, k: int = 3, min_score: float = _MIN_SCORE) -> list[Hit]:
        return [h for h in self.store.search_episodes(task, k) if h.score >= min_score]

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


__all__ = ["EpisodicMemory"]
