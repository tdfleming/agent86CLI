"""Prompt history: bash rules, the cap, multi-line round-trips, and a hostile file."""

from __future__ import annotations

import os

import pytest

from agent86.config import load_config
from agent86.ui.history import (
    DEFAULT_HISTORY_SIZE,
    PromptHistory,
    build_history,
    history_path,
    storable,
)


def _hist(tmp_path, **kwargs) -> PromptHistory:
    return PromptHistory(tmp_path / "history", **kwargs)


def test_append_and_reload_round_trips(tmp_path):
    h = _hist(tmp_path)
    assert h.append("first prompt") is True
    assert h.append("second prompt") is True
    assert list(h) == ["first prompt", "second prompt"]

    reloaded = _hist(tmp_path)
    assert reloaded.entries == ["first prompt", "second prompt"]
    assert len(reloaded) == 2
    assert reloaded[0] == "first prompt"
    assert bool(reloaded)


def test_consecutive_duplicates_are_recorded_once(tmp_path):
    h = _hist(tmp_path)
    h.append("same")
    assert h.append("same") is False
    h.append("other")
    h.append("same")  # not consecutive -> kept
    assert h.entries == ["same", "other", "same"]
    assert _hist(tmp_path).entries == ["same", "other", "same"]


def test_leading_space_lines_are_never_stored(tmp_path):
    h = _hist(tmp_path)
    assert h.append(" secret prompt") is False
    assert h.append("\thidden too") is False
    assert h.entries == []
    assert not (tmp_path / "history").exists()


@pytest.mark.parametrize("line", ["", "   ", "\n", " x"])
def test_storable_rejects_blanks_and_leading_space(line):
    assert storable(line) is False


def test_blank_lines_are_not_stored(tmp_path):
    h = _hist(tmp_path)
    assert h.append("") is False
    assert h.append("   ") is False
    assert h.entries == []


def test_cap_drops_the_oldest_in_memory_and_on_disk(tmp_path):
    h = _hist(tmp_path, max_entries=3)
    for i in range(6):
        h.append(f"prompt {i}")
    assert h.entries == ["prompt 3", "prompt 4", "prompt 5"]
    assert _hist(tmp_path, max_entries=3).entries == ["prompt 3", "prompt 4", "prompt 5"]


def test_zero_cap_means_unbounded(tmp_path):
    h = _hist(tmp_path, max_entries=0)
    for i in range(50):
        h.append(f"p{i}")
    assert len(h) == 50


def test_multi_line_prompts_round_trip(tmp_path):
    prompt = "line one\nline two\n  indented \\ backslash"
    h = _hist(tmp_path)
    h.append(prompt)
    assert _hist(tmp_path).entries == [prompt]
    # ...and the file is still one physical line per entry.
    assert len((tmp_path / "history").read_text(encoding="utf-8").splitlines()) == 1


def test_missing_file_loads_empty(tmp_path):
    h = PromptHistory(tmp_path / "nope" / "history")
    assert h.entries == []
    assert h.load() == []


def test_corrupt_file_degrades_instead_of_raising(tmp_path):
    path = tmp_path / "history"
    path.write_bytes(b"good line\n\xff\xfe\x00binary\ngood two\n")
    h = PromptHistory(path)
    # The NUL-bearing junk line is dropped; the readable ones survive.
    assert h.entries == ["good line", "good two"]


def test_unwritable_path_still_records_in_memory(tmp_path):
    # A path whose parent is a *file* can never be created -> every write fails.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    h = PromptHistory(blocker / "sub" / "history")
    assert h.append("still remembered") is True
    assert h.entries == ["still remembered"]


def test_path_none_is_memory_only(tmp_path):
    h = PromptHistory(None)
    assert h.append("in memory") is True
    assert h.entries == ["in memory"]
    assert h.path is None


def test_history_path_expands_user(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    expanded = history_path("~/.agent86/history")
    assert "~" not in str(expanded)
    assert expanded.is_absolute()


def test_build_history_reads_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cfg = load_config()
    cfg.ui.history_file = str(tmp_path / "h")
    cfg.ui.history_size = 7
    h = build_history(cfg)
    assert h.max_entries == 7
    assert h.path == (tmp_path / "h")


def test_default_size_matches_config_default():
    assert load_config().ui.history_size == DEFAULT_HISTORY_SIZE


def test_two_sessions_share_one_file(tmp_path):
    a = _hist(tmp_path)
    b = _hist(tmp_path)
    a.append("from a")
    b.append("from b")
    # Appends interleave rather than clobber: a third reader sees both.
    assert _hist(tmp_path).entries == ["from a", "from b"]


def test_rewrite_leaves_no_temp_files(tmp_path):
    h = _hist(tmp_path, max_entries=2)
    for i in range(5):
        h.append(f"p{i}")
    leftovers = [n for n in os.listdir(tmp_path) if n.startswith(".history-")]
    assert leftovers == []
