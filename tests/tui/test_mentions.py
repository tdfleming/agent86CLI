"""`@file` mentions: what gets inlined, what gets refused, and what completes."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent86.tools.sandbox.policy import SandboxPolicy
from agent86.tui.mentions import (
    MAX_COMPLETIONS,
    MAX_DIR_ENTRIES,
    complete_mentions,
    expand_mentions,
    find_mentions,
)


@pytest.fixture
def workspace(tmp_path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\nprint('bye')\n", encoding="utf-8")
    (tmp_path / "notes file.md").write_text("# notes\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def policy(workspace) -> SandboxPolicy:
    return SandboxPolicy(workspace=workspace)


# ---- detection ---------------------------------------------------------- #


def test_find_mentions_orders_and_dedupes():
    assert find_mentions("see @a.py and @b.py and @a.py again") == ["a.py", "b.py"]


def test_find_mentions_ignores_email_addresses():
    assert find_mentions("mail tony@example.com about it") == []


def test_find_mentions_strips_trailing_prose_punctuation():
    assert find_mentions("look at @src/app.py, then stop.") == ["src/app.py"]
    assert find_mentions("(@src/app.py)") == ["src/app.py"]


def test_find_mentions_reads_quoted_paths():
    assert find_mentions('open @"notes file.md" please') == ["notes file.md"]


# ---- expansion ---------------------------------------------------------- #


def test_plain_text_is_untouched(policy):
    result = expand_mentions("no mentions here", policy)
    assert result.prompt == "no mentions here"
    assert result.attachments == []
    assert result.errors == []
    assert result.expanded is False


def test_file_mention_is_inlined_with_a_header_and_fence(policy, workspace):
    result = expand_mentions("explain @src/app.py", policy)
    assert result.errors == []
    assert result.attachments == [workspace / "src" / "app.py"]
    assert result.prompt.startswith("explain @src/app.py\n\n")
    assert "--- @src/app.py (2 lines) ---" in result.prompt
    assert "print('hi')" in result.prompt
    assert "```" in result.prompt


def test_quoted_path_with_spaces_is_inlined(policy, workspace):
    result = expand_mentions('read @"notes file.md"', policy)
    assert result.errors == []
    assert result.attachments == [workspace / "notes file.md"]
    assert "--- @notes file.md (1 lines) ---" in result.prompt
    assert "# notes" in result.prompt


def test_directory_mention_lists_entries(policy, workspace):
    (workspace / "src" / "pkg").mkdir()
    result = expand_mentions("what's in @src", policy)
    assert result.errors == []
    assert "--- @src (directory, 2 entries) ---" in result.prompt
    assert "pkg/" in result.prompt
    assert "app.py" in result.prompt


def test_directory_listing_is_capped(policy, workspace):
    big = workspace / "many"
    big.mkdir()
    for i in range(MAX_DIR_ENTRIES + 25):
        (big / f"f{i:04d}.txt").write_text("x", encoding="utf-8")
    result = expand_mentions("@many", policy)
    assert "and 25 more" in result.prompt
    assert result.prompt.count("\nf0") <= MAX_DIR_ENTRIES


def test_outside_the_jail_is_refused_and_never_read(workspace, tmp_path, monkeypatch):
    secret = tmp_path.parent / "outside-secret.txt"
    secret.write_text("TOP SECRET", encoding="utf-8")
    inner = workspace / "inner"
    inner.mkdir()
    policy = SandboxPolicy(workspace=inner)

    opened: list[str] = []
    real_read = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes", lambda self: (opened.append(str(self)), real_read(self))[1]
    )

    result = expand_mentions("look at @../../outside-secret.txt", policy)
    assert result.attachments == []
    assert len(result.errors) == 1
    assert "outside the workspace" in result.errors[0]
    assert "TOP SECRET" not in result.prompt
    assert opened == []
    secret.unlink()


def test_missing_path_is_a_clear_error(policy):
    result = expand_mentions("@src/nope.py", policy)
    assert result.attachments == []
    assert result.errors == ["@src/nope.py: no such file or directory"]
    # The model is told too, so it doesn't reason as if the file arrived.
    assert "no such file or directory" in result.prompt


def test_oversize_file_is_refused(policy, workspace):
    (workspace / "big.txt").write_text("x" * 5000, encoding="utf-8")
    result = expand_mentions("@big.txt", policy, max_bytes=1000)
    assert result.attachments == []
    assert "over the 1000-byte mention cap" in result.errors[0]
    assert "xxxx" not in result.prompt


def test_file_at_the_cap_is_still_inlined(policy, workspace):
    (workspace / "edge.txt").write_text("y" * 100, encoding="utf-8")
    result = expand_mentions("@edge.txt", policy, max_bytes=100)
    assert result.errors == []
    assert result.attachments == [workspace / "edge.txt"]


def test_binary_file_is_refused(policy, workspace):
    (workspace / "blob.bin").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00binary")
    result = expand_mentions("@blob.bin", policy)
    assert result.attachments == []
    assert result.errors == ["@blob.bin: looks like a binary file"]


def test_content_with_backticks_gets_a_longer_fence(policy, workspace):
    (workspace / "doc.md").write_text("```python\ncode\n```\n", encoding="utf-8")
    result = expand_mentions("@doc.md", policy)
    assert result.errors == []
    assert "````" in result.prompt


def test_several_mentions_all_expand(policy, workspace):
    result = expand_mentions("@src/app.py and @src/nope.py", policy)
    assert len(result.attachments) == 1
    assert len(result.errors) == 1
    assert result.prompt.index("--- @src/app.py") < result.prompt.index("--- @src/nope.py")


def test_allow_paths_root_is_permitted(tmp_path):
    extra = tmp_path / "shared"
    extra.mkdir()
    (extra / "notes.txt").write_text("shared note\n", encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    policy = SandboxPolicy(workspace=ws, allow_paths=[extra])
    result = expand_mentions(f'@"{extra / "notes.txt"}"', policy)
    assert result.errors == []
    assert "shared note" in result.prompt


# ---- completion --------------------------------------------------------- #


def test_completions_list_the_workspace_root(workspace):
    out = complete_mentions("", workspace)
    assert "src/" in out
    assert "notes file.md" in out


def test_completions_filter_by_prefix(workspace):
    assert complete_mentions("src/a", workspace) == ["src/app.py"]


def test_completions_skip_noise_directories(workspace):
    for junk in (".git", "node_modules", "__pycache__", ".venv"):
        (workspace / junk).mkdir()
    out = complete_mentions("", workspace)
    assert not any(n.startswith((".git", "node_modules", "__pycache__", ".venv")) for n in out)


def test_completions_include_a_noise_directory_named_exactly(workspace):
    (workspace / ".git").mkdir()
    assert complete_mentions(".git", workspace) == [".git/"]


def test_completions_are_capped(workspace):
    many = workspace / "many"
    many.mkdir()
    for i in range(MAX_COMPLETIONS + 10):
        (many / f"f{i:03d}.txt").write_text("x", encoding="utf-8")
    assert len(complete_mentions("many/f", workspace)) == MAX_COMPLETIONS


def test_completions_refuse_to_escape_the_workspace(workspace):
    assert complete_mentions("../", workspace) == []


def test_completions_tolerate_a_leading_at_and_quotes(workspace):
    assert complete_mentions('@"src/', workspace) == ["src/app.py"]


def test_completions_on_a_missing_directory_are_empty(workspace):
    assert complete_mentions("nope/x", workspace) == []
