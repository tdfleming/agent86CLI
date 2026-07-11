"""Memory system assembly (Pillar 2).

Bundles the persistence store with its episodic and semantic facets and builds it from
config with graceful degradation: if the store can't be opened, :func:`build_memory` returns
``None`` and the harness runs statelessly rather than crashing.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent86.config import Config
from agent86.memory.embeddings import build_embedder
from agent86.memory.episodic import EpisodicMemory
from agent86.memory.semantic import SemanticMemory
from agent86.memory.store import MemoryStore


@dataclass
class MemorySystem:
    store: MemoryStore
    episodic: EpisodicMemory
    semantic: SemanticMemory
    note: str | None = None  # fallback message (e.g. embedder downgrade), shown once

    def close(self) -> None:
        self.store.close()


def build_memory(config: Config) -> MemorySystem | None:
    """Build the memory system, or return None if disabled or unavailable."""
    if not config.memory.enabled:
        return None
    embedder, note = build_embedder(config.memory.embeddings)
    store = MemoryStore(config.memory.resolved_path(), embedder)
    return MemorySystem(
        store=store,
        episodic=EpisodicMemory(store),
        semantic=SemanticMemory(store),
        note=note,
    )


__all__ = ["MemorySystem", "build_memory"]
