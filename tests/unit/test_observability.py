"""Phase 5 — the flight-data recorder. v1.0 adds rotation and streaming reads."""

from __future__ import annotations

from agent86.observability.recorder import (
    Recorder,
    read_events,
    rotated_path,
    trace_generations,
)


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


# --------------------------------------------------------------------------- #
# Rotation
# --------------------------------------------------------------------------- #


def _write(rec: Recorder, session: str, n: int, start: int = 0) -> None:
    for i in range(start, start + n):
        rec.event(session, "model_call", step=i)


def test_rotation_shifts_generations_and_drops_the_oldest(tmp_path):
    path = tmp_path / "trace.jsonl"
    # A cap of ~1 line forces a rotation after every event.
    rec = Recorder(path, max_bytes=80, keep=3)
    _write(rec, "s1", 12)
    rec.close()

    assert path.exists()
    for index in (1, 2, 3):
        assert rotated_path(path, index).exists(), f"missing generation {index}"
    # keep=3 means exactly three rotated generations survive.
    assert not rotated_path(path, 4).exists()


def test_rotation_never_loses_an_event(tmp_path):
    path = tmp_path / "trace.jsonl"
    rec = Recorder(path, max_bytes=120, keep=50)
    _write(rec, "s1", 40)
    rec.close()

    events = read_events(path, session_id="s1", limit=500, keep=50)
    assert [e["step"] for e in events] == list(range(40))


def test_read_events_walks_rotated_files_newest_first(tmp_path):
    path = tmp_path / "trace.jsonl"
    rec = Recorder(path, max_bytes=120, keep=10)
    _write(rec, "s1", 20)
    rec.close()

    tail = read_events(path, limit=5, keep=10)
    assert [e["step"] for e in tail] == [15, 16, 17, 18, 19]
    assert len(read_events(path, limit=3, keep=10)) == 3


def test_read_events_filters_across_generations(tmp_path):
    path = tmp_path / "trace.jsonl"
    rec = Recorder(path, max_bytes=120, keep=10)
    for i in range(20):
        rec.event("s1" if i % 2 == 0 else "s2", "model_call", step=i)
    rec.close()

    s2 = read_events(path, session_id="s2", limit=100, keep=10)
    assert [e["step"] for e in s2] == [i for i in range(20) if i % 2]


def test_rotation_on_open_when_the_file_is_already_over_the_cap(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text('{"kind":"old"}\n' * 50, encoding="utf-8")

    rec = Recorder(path, max_bytes=100, keep=2)
    try:
        assert rotated_path(path, 1).exists()
        assert path.stat().st_size == 0
    finally:
        rec.close()


def test_rotation_disabled_when_max_bytes_is_zero(tmp_path):
    path = tmp_path / "trace.jsonl"
    rec = Recorder(path, max_bytes=0)
    _write(rec, "s1", 50)
    rec.close()
    assert trace_generations(path) == [path]


def test_keep_zero_discards_history(tmp_path):
    path = tmp_path / "trace.jsonl"
    rec = Recorder(path, max_bytes=80, keep=0)
    _write(rec, "s1", 10)
    rec.close()
    assert not rotated_path(path, 1).exists()


def test_build_recorder_passes_rotation_settings(tmp_path):
    from agent86.config import Config
    from agent86.observability.recorder import build_recorder

    cfg = Config()
    cfg.observability.path = str(tmp_path)
    cfg.observability.max_trace_bytes = 4096
    cfg.observability.keep_traces = 2
    rec = build_recorder(cfg)
    try:
        assert (rec.max_bytes, rec.keep) == (4096, 2)
    finally:
        rec.close()
