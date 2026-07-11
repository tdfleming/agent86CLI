"""Phase 5 — the flight-data recorder."""

from __future__ import annotations

from agent86.observability.recorder import Recorder, read_events


def test_recorder_writes_and_reads(tmp_path):
    path = tmp_path / "trace.jsonl"
    rec = Recorder(path)
    rec.event("s1", "turn_start", task="hello")
    rec.event("s1", "model_call", step=1, output_tokens=5)
    rec.event("s2", "turn_start", task="other")
    rec.close()

    all_events = read_events(path)
    assert len(all_events) == 3
    assert all_events[0]["kind"] == "turn_start"
    assert "ts" in all_events[0]

    s1_only = read_events(path, session_id="s1")
    assert len(s1_only) == 2
    assert all(e["session"] == "s1" for e in s1_only)


def test_disabled_recorder_is_noop(tmp_path):
    rec = Recorder(None)
    rec.event("s1", "turn_start")  # must not raise
    rec.close()
    assert read_events(tmp_path / "nonexistent.jsonl") == []
