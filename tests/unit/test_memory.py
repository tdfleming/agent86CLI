"""Phase 4 — embeddings, store, working memory, and memory tools (no ML deps)."""

from __future__ import annotations

from pathlib import Path

from agent86.config import load_config
from agent86.memory.embeddings import HashingEmbedder, build_embedder
from agent86.memory.episodic import EpisodicMemory
from agent86.memory.semantic import SemanticMemory
from agent86.memory.store import MemoryStore
from agent86.memory.working import WorkingMemory
from agent86.tools.base import ToolContext
from agent86.tools.builtin.memory import RecallTool, RememberTool
from agent86.tools.sandbox.policy import default_policy
from agent86.types import Message, Role, ToolCall


def _store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "mem.db", HashingEmbedder(64))


# ---- embeddings -------------------------------------------------------- #


def test_hash_embedder_is_deterministic_and_unit_norm():
    emb = HashingEmbedder(64)
    a = emb.encode_one("the quick brown fox")
    b = emb.encode_one("the quick brown fox")
    assert a == b
    assert len(a) == 64
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6


def test_build_embedder_falls_back_without_torch():
    emb, note = build_embedder("sentence-transformers:all-MiniLM-L6-v2")
    # torch isn't installed in the test env -> hash fallback with a note
    assert isinstance(emb, HashingEmbedder)
    assert note and "hash embedder" in note


def test_build_embedder_explicit_hash():
    emb, note = build_embedder("hash:128")
    assert isinstance(emb, HashingEmbedder) and emb.dim == 128 and note is None


# ---- store ------------------------------------------------------------- #


def test_semantic_add_and_search_ranks_relevant_first(tmp_path):
    store = _store(tmp_path)
    store.add_memory("The user's favorite language is Python.")
    store.add_memory("The capital of France is Paris.")
    hits = store.search_memories("Which programming language does the user like?", k=2)
    assert hits
    assert "Python" in hits[0].text


def test_search_skips_mismatched_dimension_rows(tmp_path):
    # Simulate an embedder change: write with dim 32, then search with a dim-64 store.
    path = tmp_path / "mem.db"
    MemoryStore(path, HashingEmbedder(32)).add_memory("old fact from a 32-dim embedder")
    store = MemoryStore(path, HashingEmbedder(64))
    store.add_memory("new fact from a 64-dim embedder")
    hits = store.search_memories("fact", k=5)
    # The mismatched-dimension (old) row is skipped; only the current-dim row ranks.
    assert len(hits) == 1
    assert "64-dim" in hits[0].text


def test_episode_roundtrip_and_recall(tmp_path):
    store = _store(tmp_path)
    store.add_episode("s1", task="deploy the web app", outcome="succeeded via run_command")
    hits = store.search_episodes("deploy web application", k=1)
    assert hits and hits[0].metadata["outcome"].startswith("succeeded")


def test_session_persistence(tmp_path):
    store = _store(tmp_path)
    store.save_session("s1", '{"session_id": "s1"}', title="test")
    assert store.load_session("s1") == '{"session_id": "s1"}'
    assert store.load_session("missing") is None
    assert store.counts()["sessions"] == 1
    rows = store.list_sessions()
    assert rows[0]["session_id"] == "s1"


def test_episodic_recall_note(tmp_path):
    store = _store(tmp_path)
    epi = EpisodicMemory(store)
    epi.record_turn("s1", "write a poem about the sea", "wrote a haiku about waves")
    note = epi.recall_note("compose a poem about the ocean")
    assert note is not None and "past experience" in note


# ---- working memory ---------------------------------------------------- #


def test_working_memory_trims_to_budget():
    msgs = [Message(role=Role.USER, content="word " * 50) for _ in range(10)]
    # counter ~ 1 token per 4 chars; each message ~ 62 tokens
    wm = WorkingMemory(max_tokens=130)
    counter = lambda m: sum(len(x.content) // 4 for x in m)  # noqa: E731
    kept = wm.fit(msgs, counter)
    assert 0 < len(kept) < len(msgs)
    assert kept == msgs[-len(kept):]  # kept the most recent suffix


def test_working_memory_drops_leading_tool_orphan():
    msgs = [
        Message(role=Role.TOOL, content="old tool result", tool_call_id="x", name="t"),
        Message(role=Role.USER, content="hello"),
        Message(role=Role.ASSISTANT, content="hi"),
    ]
    wm = WorkingMemory(max_tokens=1)  # force trimming to the smallest suffix
    kept = wm.fit(msgs, lambda m: sum(len(x.content) for x in m))
    assert kept[0].role != Role.TOOL


# ---- memory tools ------------------------------------------------------ #


def test_remember_and_recall_tools(tmp_path):
    store = _store(tmp_path)
    semantic = SemanticMemory(store)
    cfg = load_config()
    ctx = ToolContext(
        workspace=tmp_path, policy=default_policy(cfg, tmp_path), config=cfg, memory=semantic
    )

    RememberTool().run(
        ToolCall(id="1", name="remember", arguments={"text": "agent86 was built by Tony."}), ctx
    )
    res = RecallTool().run(
        ToolCall(id="2", name="recall", arguments={"query": "who built agent86?"}), ctx
    )
    assert res.ok and "Tony" in res.content
