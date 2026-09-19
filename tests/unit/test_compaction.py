"""v0.8 — summarizing compaction of an over-budget conversation.

The pre-v0.8 behaviour was to drop the oldest span silently, which meant a long session's
first casualty was the user's original ask. These tests pin the replacement: the prefix is
summarized into a single USER message, tool blocks are never split, and every failure mode
falls back to dropping rather than costing the user their turn.
"""

from __future__ import annotations

import pytest

from agent86.config import load_config
from agent86.memory.working import SUMMARY_HEADER, apply_summary, render_transcript
from agent86.orchestration.loop import Harness
from agent86.types import AgentPhase, Message, Role, ToolCall
from tests.support import CompactingProvider


class _CapturingRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def event(self, session_id: str, kind: str, **data: object) -> None:
        self.events.append((session_id, kind, dict(data)))

    def close(self) -> None:
        pass

    def of_kind(self, kind: str) -> list[dict]:
        return [data for _sid, k, data in self.events if k == kind]


def _config(**limits):
    cfg = load_config()
    # A tiny hard cap is the cheapest way to make the budget bite without a 200k fixture.
    cfg.limits.max_context_tokens = 60
    for key, value in limits.items():
        setattr(cfg.limits, key, value)
    return cfg


def _history(n: int = 12) -> list[Message]:
    """A plain alternating history, long enough to have a compactable prefix."""
    out: list[Message] = []
    for i in range(n // 2):
        out.append(Message(role=Role.USER, content=f"question {i} " + "x" * 200))
        out.append(Message(role=Role.ASSISTANT, content=f"answer {i} " + "y" * 200))
    return out


def _harness(provider=None, cfg=None):
    harness = Harness(cfg or _config(), provider=provider or CompactingProvider(), memory=None)
    harness.recorder = _CapturingRecorder()
    return harness


# ---- the pure pieces ------------------------------------------------------- #


def test_apply_summary_merges_into_a_following_user_turn():
    rest = [Message(role=Role.USER, content="now do the next thing")]
    out = apply_summary("GOAL: ship it", rest)

    # One message, not two: consecutive USER messages are a shape some providers reject, and
    # Anthropic's adapter renders TOOL results as `user` too.
    assert len(out) == 1
    assert out[0].role is Role.USER
    assert out[0].content.startswith(SUMMARY_HEADER)
    assert "now do the next thing" in out[0].content


def test_apply_summary_prepends_when_the_next_turn_is_not_a_user_message():
    rest = [Message(role=Role.ASSISTANT, content="thinking")]
    out = apply_summary("GOAL: ship it", rest)

    assert [m.role for m in out] == [Role.USER, Role.ASSISTANT]
    assert out[0].content.startswith(SUMMARY_HEADER)


def test_render_transcript_includes_tool_calls_and_results():
    msgs = [
        Message(role=Role.USER, content="read the config"),
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(id="t1", name="read_file", arguments={"path": "src/agent86/config.py"})
            ],
        ),
        Message(role=Role.TOOL, content="file body", tool_call_id="t1", name="read_file"),
    ]
    text = render_transcript(msgs)

    assert "read the config" in text
    assert "called read_file" in text
    assert "src/agent86/config.py" in text  # the path the summary must reproduce verbatim
    assert "result of read_file" in text


# ---- compaction inside a turn ---------------------------------------------- #


def test_summary_replaces_the_oldest_prefix():
    provider = CompactingProvider(summary="GOAL: ship v0.8\nFACTS: loop.py")
    harness = _harness(provider)
    state = harness.new_session()
    state.messages = _history(12)

    list(harness.run_turn("and now finish", state))

    assert len(provider.summary_requests) == 1
    # The oldest turns are gone, replaced by one summary message at the head.
    assert len(state.messages) < 12
    assert state.messages[0].role is Role.USER
    assert state.messages[0].content.startswith(SUMMARY_HEADER)
    assert "GOAL: ship v0.8" in state.messages[0].content
    assert "question 0" not in state.messages[0].content
    assert state.phase is AgentPhase.DONE
    assert state.last_turn is not None and state.last_turn.compactions == 1


def test_a_successful_compaction_tells_the_user_it_happened():
    """Silent compaction reads, from the user's seat, as a model that forgot the task."""
    from agent86.ui.repl import notice_text

    harness = _harness()
    state = harness.new_session()
    state.messages = _history(12)

    deltas = list(harness.run_turn("and now finish", state))

    notices = [n for n in (notice_text(d.text) for d in deltas if d.text) if n is not None]
    dropped = harness.recorder.of_kind("compaction")[-1]["dropped"]
    assert notices == [f"[compacted {dropped} messages into a summary]"]
    # It is a plain text delta, newline-fenced, so it can never glue onto model prose.
    assert any(d.text == f"\n[compacted {dropped} messages into a summary]\n" for d in deltas)


def test_the_drop_fallback_says_so_rather_than_going_quiet():
    from agent86.ui.repl import notice_text

    harness = _harness(CompactingProvider(fail_summary=True))
    state = harness.new_session()
    state.messages = _history(12)

    deltas = list(harness.run_turn("and now finish", state))

    notices = [n for n in (notice_text(d.text) for d in deltas if d.text) if n is not None]
    dropped = harness.recorder.of_kind("compaction")[-1]["dropped"]
    assert notices == [f"[compaction failed; dropped {dropped} messages]"]


def test_an_empty_summary_reports_the_same_drop_notice():
    from agent86.ui.repl import notice_text

    harness = _harness(CompactingProvider(summary="   "))
    state = harness.new_session()
    state.messages = _history(12)

    deltas = list(harness.run_turn("and now finish", state))

    notices = [n for n in (notice_text(d.text) for d in deltas if d.text) if n is not None]
    assert notices and notices[0].startswith("[compaction failed; dropped ")


def test_a_turn_that_compacts_nothing_is_silent():
    harness = _harness(CompactingProvider(), cfg=load_config())
    state = harness.new_session()

    deltas = list(harness.run_turn("hello", state))

    assert not any("[compact" in (d.text or "") for d in deltas)


def test_the_current_user_turn_is_never_compacted():
    harness = _harness()
    state = harness.new_session()
    state.messages = _history(12)

    list(harness.run_turn("and now finish", state))

    assert any("and now finish" in m.content for m in state.messages)


def test_a_tool_call_is_never_split_from_its_results():
    harness = _harness()
    state = harness.new_session()
    history = _history(8)
    history += [
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[ToolCall(id="t1", name="read_file", arguments={"path": "a.py"})],
        ),
        Message(role=Role.TOOL, content="z" * 400, tool_call_id="t1", name="read_file"),
        Message(role=Role.ASSISTANT, content="got it"),
    ]
    state.messages = list(history)

    list(harness.run_turn("continue", state))

    # Every surviving TOOL result still has an assistant tool_use ahead of it.
    open_ids: set[str] = set()
    for m in state.messages:
        for call in m.tool_calls:
            open_ids.add(call.id)
        if m.role is Role.TOOL:
            assert m.tool_call_id in open_ids, "a tool_result outlived its tool_use"


def test_summarizer_failure_falls_back_to_dropping():
    provider = CompactingProvider(fail_summary=True)
    harness = _harness(provider)
    state = harness.new_session()
    state.messages = _history(12)

    deltas = list(harness.run_turn("and now finish", state))

    # The turn completed normally — a failed summary is never the user's problem.
    assert state.phase is AgentPhase.DONE
    assert "all done" in "".join(d.text for d in deltas if d.text)
    # Nothing was rewritten; `fit` drops instead, and the trace says why.
    assert not any(m.content.startswith(SUMMARY_HEADER) for m in state.messages)
    event = harness.recorder.of_kind("compaction")[-1]
    assert event["status"] == "failed"
    assert event["fallback"] == "drop"
    assert "summarizer exploded" in event["error"]
    assert state.last_turn is not None and state.last_turn.compactions == 0


def test_an_empty_summary_falls_back_to_dropping():
    harness = _harness(CompactingProvider(summary="   "))
    state = harness.new_session()
    state.messages = _history(12)

    list(harness.run_turn("and now finish", state))

    assert not any(m.content.startswith(SUMMARY_HEADER) for m in state.messages)
    assert harness.recorder.of_kind("compaction")[-1]["status"] == "empty"


def test_drop_mode_keeps_the_pre_v08_behaviour():
    provider = CompactingProvider()
    harness = _harness(provider, cfg=_config(compaction="drop"))
    state = harness.new_session()
    state.messages = _history(12)

    list(harness.run_turn("and now finish", state))

    assert provider.summary_requests == []          # the summarizer is never consulted
    assert harness.recorder.of_kind("compaction") == []
    assert not any(m.content.startswith(SUMMARY_HEADER) for m in state.messages)


def test_compaction_records_dropped_and_summary_token_counts():
    harness = _harness()
    state = harness.new_session()
    state.messages = _history(12)

    list(harness.run_turn("and now finish", state))

    event = harness.recorder.of_kind("compaction")[-1]
    assert event["status"] == "ok"
    assert event["dropped"] >= 1
    assert event["dropped_tokens"] > event["summary_tokens"] > 0
    # `kept` is the history at compaction time; the turn's answer was appended afterwards.
    assert event["kept"] == len(state.messages) - 1


def test_compaction_happens_at_most_once_per_step():
    """The summarizer's own call must not trigger a nested compaction."""
    provider = CompactingProvider()
    harness = _harness(provider)
    state = harness.new_session()
    state.messages = _history(12)

    list(harness.run_turn("and now finish", state))

    assert len(provider.summary_requests) == 1
    assert len(harness.recorder.of_kind("compaction")) == 1


def test_nothing_to_compact_is_a_no_op():
    """A short conversation that fits the budget is left completely alone."""
    provider = CompactingProvider()
    cfg = load_config()  # no hard cap: the real window is far bigger than this history
    harness = _harness(provider, cfg=cfg)
    state = harness.new_session()

    list(harness.run_turn("hello", state))

    assert provider.summary_requests == []
    assert harness.recorder.of_kind("compaction") == []


# ---- persistence ----------------------------------------------------------- #


@pytest.fixture
def memory_harness(tmp_path):
    """A harness with a real (temporary) memory system, so resume and archival are live."""
    from agent86.memory.embeddings import HashingEmbedder
    from agent86.memory.episodic import EpisodicMemory
    from agent86.memory.semantic import SemanticMemory
    from agent86.memory.store import MemoryStore
    from agent86.memory.system import MemorySystem

    store = MemoryStore(tmp_path / "mem.db", HashingEmbedder(64))
    memory = MemorySystem(
        store=store, episodic=EpisodicMemory(store), semantic=SemanticMemory(store)
    )
    harness = Harness(_config(), provider=CompactingProvider(), memory=memory)
    harness.recorder = _CapturingRecorder()
    yield harness
    memory.close()


def test_resume_sees_the_compacted_history(memory_harness):
    state = memory_harness.new_session()
    state.messages = _history(12)

    list(memory_harness.run_turn("and now finish", state))

    revived = memory_harness.resume(state.session_id)
    assert revived is not None
    assert revived.messages[0].content.startswith(SUMMARY_HEADER)
    assert [m.content for m in revived.messages] == [m.content for m in state.messages]


def test_the_originals_are_archived_in_episodic_memory(memory_harness):
    from agent86.memory.episodic import COMPACTION_KIND

    state = memory_harness.new_session()
    state.messages = _history(12)

    list(memory_harness.run_turn("and now finish", state))

    rows = memory_harness.memory.store.conn.execute(
        "SELECT task, outcome, metadata_json FROM episodes"
    ).fetchall()
    archived = [r for r in rows if COMPACTION_KIND in (r[2] or "")]
    assert len(archived) == 1
    task, outcome, _meta = archived[0]
    assert "compacted" in task
    # The raw messages survive verbatim, as resurrectable JSON.
    assert "question 0" in outcome
    # ... but they are held out of recall, so a new turn is never handed a raw transcript.
    assert memory_harness.memory.episodic.recall("question 0", k=5) == []
