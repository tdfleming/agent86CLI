"""Phase 4 — embeddings, store, working memory, and memory tools (no ML deps)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from agent86.config import load_config
from agent86.memory import embeddings as emb
from agent86.memory.embeddings import (
    HashingEmbedder,
    SentenceTransformerEmbedder,
    build_embedder,
)
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


def test_build_embedder_falls_back_without_torch(monkeypatch):
    """The fallback branch, forced — never "torch happens to be absent on this machine".

    `SentenceTransformerEmbedder.__init__` does `from sentence_transformers import
    SentenceTransformer`. Binding that name to None in `sys.modules` makes the import
    statement raise ModuleNotFoundError (CPython treats a None entry as "this module is known
    to be unimportable"), which is exactly what a missing torch looks like from
    `build_embedder`'s side. monkeypatch restores the previous entry at teardown, so a machine
    that does have the `local` extra installed keeps it for every other test.
    """
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    embedder, note = build_embedder("sentence-transformers:all-MiniLM-L6-v2")

    assert isinstance(embedder, HashingEmbedder)
    assert note and "hash embedder" in note
    # The note names the failure so the user can tell a missing dep from a download error.
    assert "sentence-transformers unavailable (ModuleNotFoundError)" in note


@pytest.mark.skipif(
    importlib.util.find_spec("sentence_transformers") is None,
    reason="requires the 'local' extra (sentence-transformers)",
)
def test_build_embedder_uses_sentence_transformers_when_installed(monkeypatch):
    """With the library importable, the spec must resolve to the real embedder, not the fallback.

    The SentenceTransformer class is stubbed so the test never downloads a model or touches the
    network; what is under test is the branch `build_embedder` takes, not the model itself.
    """
    import sentence_transformers

    class _StubModel:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        def get_sentence_embedding_dimension(self) -> int:
            return 384

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", _StubModel)

    embedder, note = build_embedder("sentence-transformers:all-MiniLM-L6-v2")

    assert isinstance(embedder, SentenceTransformerEmbedder)
    assert note is None
    assert embedder.dim == 384
    assert embedder.spec == "sentence-transformers:all-MiniLM-L6-v2"


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


def test_python_fallback_search_ranks_relevant_first(tmp_path, monkeypatch):
    # Force the dependency-free brute-force path regardless of whether sqlite-vec is installed.
    store = _store(tmp_path)
    monkeypatch.setattr(store, "has_vec", False)
    store.add_memory("The user's favorite language is Python.")
    store.add_memory("The capital of France is Paris.")
    hits = store.search_memories("Which programming language does the user like?", k=2)
    assert hits and "Python" in hits[0].text


def test_native_vec_search_matches_python_path(tmp_path):
    # When sqlite-vec is loaded, the native vec_distance_cosine path must rank identically.
    store = _store(tmp_path)
    if not store.has_vec:
        pytest.skip("sqlite-vec not available / extension loading disabled")
    store.add_memory("The user's favorite language is Python.")
    store.add_memory("The capital of France is Paris.")
    hits = store.search_memories("Which programming language does the user like?", k=2)
    assert hits and "Python" in hits[0].text
    assert all(0.0 <= h.score <= 1.0001 for h in hits)  # similarity, not distance


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


# ---- session titles & listing ------------------------------------------ #


def test_save_session_keeps_the_title_when_none_is_given(tmp_path):
    """A mid-session state dump must not wipe the session's name."""
    store = _store(tmp_path)
    store.save_session("s1", "{}", title="first name")
    store.save_session("s1", '{"later": true}')
    assert store.session_title("s1") == "first name"


def test_save_session_renames_when_a_title_is_given(tmp_path):
    """The store allows a rename; deciding not to is the harness's job."""
    store = _store(tmp_path)
    store.save_session("s1", "{}", title="first name")
    store.save_session("s1", "{}", title="second name")
    assert store.session_title("s1") == "second name"


def test_session_title_can_arrive_after_an_untitled_save(tmp_path):
    store = _store(tmp_path)
    store.save_session("s1", "{}")  # new_session(): nothing said yet
    assert store.session_title("s1") is None
    store.save_session("s1", "{}", title="named at the first turn")
    assert store.session_title("s1") == "named at the first turn"


def test_session_title_of_an_unknown_session_is_none(tmp_path):
    assert _store(tmp_path).session_title("nope") is None


def test_recent_sessions_are_typed_and_newest_first(tmp_path):
    store = _store(tmp_path)
    store.save_session("old", "{}", title="older work")
    store.save_session("new", "{}", title="newer work")
    infos = store.recent_sessions()
    assert [i.session_id for i in infos] == ["new", "old"]
    assert infos[0].title == "newer work"
    assert infos[0].updated_at > 0
    assert infos[0].label == "newer work"


def test_recent_sessions_labels_an_untitled_session(tmp_path):
    store = _store(tmp_path)
    store.save_session("s1", "{}")
    assert store.recent_sessions()[0].label == "(untitled)"


def test_recent_sessions_respects_the_limit(tmp_path):
    store = _store(tmp_path)
    for i in range(5):
        store.save_session(f"s{i}", "{}", title=f"t{i}")
    assert len(store.recent_sessions(limit=2)) == 2


def test_episodic_exposes_session_listing(tmp_path):
    store = _store(tmp_path)
    epi = EpisodicMemory(store)
    store.save_session("s1", "{}", title="named")
    assert [i.session_id for i in epi.recent_sessions()] == ["s1"]
    assert epi.session_title("s1") == "named"


def test_derived_session_title_is_the_first_user_message(tmp_path):
    from agent86.orchestration.loop import SESSION_TITLE_MAX, session_title
    from agent86.orchestration.state import AgentState

    state = AgentState()
    assert session_title(state) is None

    state.add_message(Message(role=Role.SYSTEM, content="ignored"))
    state.add_message(Message(role=Role.USER, content="  refactor   the   loop  "))
    state.add_message(Message(role=Role.USER, content="and then the tests"))
    # Whitespace collapsed, and the FIRST user message wins.
    assert session_title(state) == "refactor the loop"

    long_state = AgentState()
    long_state.add_message(Message(role=Role.USER, content="x" * 200))
    title = session_title(long_state)
    assert title is not None
    assert len(title) == SESSION_TITLE_MAX
    assert title.endswith("...")


def test_harness_names_the_session_on_its_first_turn(tmp_path):
    from agent86.config import load_config as _load
    from agent86.memory.system import MemorySystem
    from agent86.orchestration.loop import Harness
    from tests.support import make_text_provider

    store = _store(tmp_path)
    memory = MemorySystem(
        store=store,
        episodic=EpisodicMemory(store),
        semantic=SemanticMemory(store),
    )
    harness = Harness(
        _load(), provider=make_text_provider("done"), memory=memory, workspace=tmp_path
    )
    state = harness.new_session()
    # Opened but never spoken to: no placeholder name that would then stick.
    assert store.session_title(state.session_id) is None

    list(harness.run_turn("explain the circuit breaker", state))
    assert store.session_title(state.session_id) == "explain the circuit breaker"

    list(harness.run_turn("now the router", state))
    assert store.session_title(state.session_id) == "explain the circuit breaker"


def test_a_compacted_opening_message_does_not_rename_the_session(tmp_path):
    """Naming happens once: losing the opening message to compaction must not rename it."""
    from agent86.config import load_config as _load
    from agent86.memory.system import MemorySystem
    from agent86.orchestration.loop import Harness
    from tests.support import make_text_provider

    store = _store(tmp_path)
    memory = MemorySystem(
        store=store, episodic=EpisodicMemory(store), semantic=SemanticMemory(store)
    )
    harness = Harness(
        _load(), provider=make_text_provider("done"), memory=memory, workspace=tmp_path
    )
    state = harness.new_session()
    list(harness.run_turn("the original question", state))
    assert store.session_title(state.session_id) == "the original question"

    # Compaction drops the oldest messages; the name must survive it.
    state.messages = [Message(role=Role.USER, content="a much later question")]
    harness._persist(state)
    assert store.session_title(state.session_id) == "the original question"


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


# ---- the context budget ------------------------------------------------ #


def test_conversation_budget_subtracts_overhead_reserve_and_output():
    from agent86.memory.working import conversation_budget

    budget = conversation_budget(
        200_000, overhead_tokens=3_000, reserve_tokens=4_096, output_tokens=8_192
    )
    assert budget == 200_000 - 3_000 - 4_096 - 8_192


def test_conversation_budget_clamps_the_reserve_on_a_small_window():
    from agent86.memory.working import conversation_budget

    # 4096 + 8192 would swallow an entire 8k window; the reserve is capped at half of it.
    budget = conversation_budget(
        8_192, overhead_tokens=1_000, reserve_tokens=4_096, output_tokens=8_192
    )
    assert budget == 8_192 - 1_000 - 4_096


def test_conversation_budget_floors_then_applies_the_hard_cap():
    from agent86.memory.working import MIN_CONVERSATION_TOKENS, conversation_budget

    # Pathological: overhead alone exceeds the window. The floor keeps it sane ...
    assert (
        conversation_budget(2_000, overhead_tokens=9_000, reserve_tokens=500)
        == MIN_CONVERSATION_TOKENS
    )
    # ... but an explicit hard cap is still honoured below the floor (it was typed on purpose).
    assert conversation_budget(200_000, hard_cap=20) == 20
    assert conversation_budget(200_000, hard_cap=0) == 200_000  # 0 = no cap


def test_count_spec_tokens_scales_with_the_tool_catalogue():
    from agent86.memory.working import count_spec_tokens
    from agent86.types import ToolSpec

    assert count_spec_tokens([]) == 0
    specs = [
        ToolSpec(
            name=f"tool_{i}",
            description="a tool with a reasonably long description " * 4,
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        )
        for i in range(10)
    ]
    one = count_spec_tokens(specs[:1])
    assert one > 0 and count_spec_tokens(specs) > 8 * one


def test_count_tokens_includes_tool_call_arguments():
    from agent86.cognitive.base import ModelProvider

    class _P(ModelProvider):
        name = "p"
        model = "p:m"

        def stream(self, request):  # pragma: no cover - never called
            raise NotImplementedError

    provider = _P()
    bare = Message(role=Role.ASSISTANT, content="")
    with_call = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(id="1", name="write_file", arguments={"body": "x" * 4_000})],
    )
    assert provider.count_tokens([bare]) == 0
    # Regression: a step whose whole payload is tool arguments used to measure as 0 tokens.
    assert provider.count_tokens([with_call]) > 900


def test_compaction_cut_protects_recent_turns_and_tool_pairs():
    from agent86.memory.working import WorkingMemory

    msgs = [
        Message(role=Role.USER, content="a" * 400),
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[ToolCall(id="t1", name="read_file", arguments={})],
        ),
        Message(role=Role.TOOL, content="b" * 400, tool_call_id="t1", name="read_file"),
        Message(role=Role.ASSISTANT, content="c" * 400),
        Message(role=Role.USER, content="d" * 400),
        Message(role=Role.ASSISTANT, content="e" * 400),
        Message(role=Role.USER, content="f" * 400),
    ]
    counter = lambda m: sum(len(x.content) // 4 for x in m)  # noqa: E731
    wm = WorkingMemory(max_tokens=10)

    # keep_recent=5 would cut at index 2, which is a TOOL result — walk back to 1, then to the
    # assistant that owns it, leaving the prefix a whole number of blocks.
    cut = wm.compaction_cut(msgs, counter, keep_recent=5)
    assert cut == 1
    assert msgs[cut].role is Role.ASSISTANT

    # Nothing to do when the conversation already fits.
    assert WorkingMemory(max_tokens=10_000).compaction_cut(msgs, counter) == 0

    # The current user turn is never compacted.
    assert wm.compaction_cut(msgs, counter, keep_recent=0, protect_from=0) == 0
