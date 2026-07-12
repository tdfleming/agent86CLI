"""v0.2 regression — a memory-backed turn must run from a worker thread (rich REPL).

The rich REPL runs each turn in a worker thread so the spinner can animate. SQLite objects
are thread-bound by default, so this reproduces the ProgrammingError that surfaced and locks
in the check_same_thread=False fix.
"""

from __future__ import annotations

import threading

from agent86.config import load_config
from agent86.memory.embeddings import HashingEmbedder
from agent86.memory.episodic import EpisodicMemory
from agent86.memory.semantic import SemanticMemory
from agent86.memory.store import MemoryStore
from agent86.memory.system import MemorySystem
from agent86.orchestration.loop import Harness
from tests.support import make_text_provider


def test_turn_runs_in_worker_thread_with_memory(tmp_path):
    store = MemoryStore(tmp_path / "mem.db", HashingEmbedder(64))
    mem = MemorySystem(store, EpisodicMemory(store), SemanticMemory(store))
    harness = Harness(
        load_config(), provider=make_text_provider("hello"), memory=mem, workspace=tmp_path
    )
    state = harness.new_session()  # main thread

    result: dict = {}

    def worker():
        try:
            list(harness.run_turn("do the thing", state))  # touches SQLite from this thread
            result["ok"] = True
        except Exception as exc:  # e.g. sqlite3.ProgrammingError before the fix
            result["error"] = exc

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=10)

    assert result.get("ok"), f"turn failed in worker thread: {result.get('error')!r}"
    # and memory was actually written from the worker thread
    assert store.load_session(state.session_id) is not None
    assert store.counts()["episodes"] == 1
