"""Phase 4 — memory wired into the harness: persistence, recall, resume (no network)."""

from __future__ import annotations

from agent86.config import load_config
from agent86.memory.embeddings import HashingEmbedder
from agent86.memory.episodic import EpisodicMemory
from agent86.memory.semantic import SemanticMemory
from agent86.memory.store import MemoryStore
from agent86.memory.system import MemorySystem
from agent86.orchestration.loop import Harness
from tests.support import make_text_provider


def _memory(tmp_path) -> MemorySystem:
    store = MemoryStore(tmp_path / "mem.db", HashingEmbedder(64))
    return MemorySystem(store, EpisodicMemory(store), SemanticMemory(store))


def test_turn_persists_session_and_episode(tmp_path):
    mem = _memory(tmp_path)
    harness = Harness(
        load_config(), provider=make_text_provider("all done"), memory=mem, workspace=tmp_path
    )
    state = harness.new_session()

    list(harness.run_turn("do the thing", state))

    # session persisted and an episode recorded
    assert mem.store.load_session(state.session_id) is not None
    counts = mem.store.counts()
    assert counts["episodes"] == 1
    # episodic recall finds the just-completed turn
    hits = mem.store.search_episodes("do the thing", k=1)
    assert hits and hits[0].metadata["outcome"] == "all done"


def test_resume_restores_prior_conversation(tmp_path):
    mem = _memory(tmp_path)
    harness = Harness(
        load_config(), provider=make_text_provider("first answer"), memory=mem, workspace=tmp_path
    )
    state = harness.new_session()
    list(harness.run_turn("first question", state))
    sid = state.session_id

    # A fresh harness over the same store can resume the session.
    harness2 = Harness(
        load_config(), provider=make_text_provider("x"), memory=mem, workspace=tmp_path
    )
    resumed = harness2.resume(sid)
    assert resumed is not None
    assert resumed.session_id == sid
    assert any("first question" == m.content for m in resumed.messages)
