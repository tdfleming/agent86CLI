"""Phase 4 — embeddings, store, working memory, and memory tools (no ML deps)."""

from __future__ import annotations

from pathlib import Path

from agent86.config import load_config
from agent86.memory import embeddings as emb
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
    embedder, note = build_embedder("sentence-transformers:all-MiniLM-L6-v2")
    # torch isn't installed in the test env -> hash fallback with a note
    assert isinstance(embedder, HashingEmbedder)
    assert note and "hash embedder" in note


def test_build_embedder_explicit_hash():
    embedder, note = build_embedder("hash:128")
    assert isinstance(embedder, HashingEmbedder) and embedder.dim == 128 and note is None


def test_hf_overrides_go_offline_when_model_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    (tmp_path / "models--sentence-transformers--all-MiniLM-L6-v2").mkdir()
    env = emb._hf_env_overrides("all-MiniLM-L6-v2", offline=True)
    assert env["HF_HUB_OFFLINE"] == "1"  # cached -> skip the hub check (no warning)
    assert env["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"


def test_hf_overrides_stay_online_when_model_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))  # empty cache
    env = emb._hf_env_overrides("all-MiniLM-L6-v2", offline=True)
    assert "HF_HUB_OFFLINE" not in env  # not cached -> allow first-run download
    assert env["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"  # still quiet the progress bars


def test_hf_overrides_respect_offline_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    (tmp_path / "models--sentence-transformers--all-MiniLM-L6-v2").mkdir()
    env = emb._hf_env_overrides("all-MiniLM-L6-v2", offline=False)
    assert "HF_HUB_OFFLINE" not in env  # opt-out honored even when cached


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


def test_delete_memory(tmp_path):
    store = _store(tmp_path)
    mid = store.add_memory("a fact to remove")
    assert store.delete_memory(mid) is True
    assert store.delete_memory(mid) is False  # already gone
    assert store.counts()["memories"] == 0


def test_prune_keep_last_trims_log(tmp_path):
    store = _store(tmp_path)
    for i in range(5):
        store.add_episode("s1", task=f"task {i}", outcome="ok")
        store.save_session(f"sess{i}", "{}")
    removed = store.prune(keep_last=2)
    assert removed["episodes"] == 3 and removed["sessions"] == 3
    assert store.counts()["episodes"] == 2
    assert store.counts()["sessions"] == 2


def test_prune_leaves_memories_by_default(tmp_path):
    store = _store(tmp_path)
    store.add_memory("keep me")
    store.add_episode("s1", task="t", outcome="ok")
    removed = store.prune(keep_last=0)  # nuke the log entirely
    assert removed["episodes"] == 1
    assert "memories" not in removed
    assert store.counts()["memories"] == 1  # curated facts untouched
    # opt-in prunes memories too
    removed2 = store.prune(keep_last=0, memories=True, episodes=False, sessions=False)
    assert removed2["memories"] == 1
    assert store.counts()["memories"] == 0


def test_enforce_retention_per_table_caps(tmp_path):
    store = _store(tmp_path)
    for i in range(10):
        store.add_episode("s1", task=f"t{i}", outcome="ok")
    for i in range(6):
        store.save_session(f"sess{i}", "{}")
    store.add_memory("a curated fact")
    removed = store.enforce_retention(max_episodes=4, max_sessions=2)
    assert removed == {"episodes": 6, "sessions": 4}
    assert store.counts()["episodes"] == 4
    assert store.counts()["sessions"] == 2
    assert store.counts()["memories"] == 1  # facts never auto-pruned


def test_enforce_retention_zero_disables_cap(tmp_path):
    store = _store(tmp_path)
    for i in range(3):
        store.add_episode("s1", task=f"t{i}", outcome="ok")
    removed = store.enforce_retention(max_episodes=0, max_sessions=0, max_age_days=0.0)
    assert removed == {}  # nothing capped
    assert store.counts()["episodes"] == 3


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
