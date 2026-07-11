"""Semantic memory (Pillar 2) — the knowledge base.

Stores durable facts and retrieves them by meaning (RAG). Exposed to the agent through the
``remember`` and ``recall`` tools so it can persist and look up knowledge across sessions.
"""

from __future__ import annotations

from agent86.memory.store import Hit, MemoryStore

_MIN_SCORE = 0.30


class SemanticMemory:
    def __init__(self, store: MemoryStore):
        self.store = store

    def add(self, text: str, metadata: dict | None = None) -> int:
        return self.store.add_memory(text, kind="fact", metadata=metadata)

    def search(self, query: str, k: int = 5, min_score: float = _MIN_SCORE) -> list[Hit]:
        return [h for h in self.store.search_memories(query, k) if h.score >= min_score]


__all__ = ["SemanticMemory"]
