"""v0.9 — `edit_file` exact-match editing, diff output, and byte preservation.

The editing contract a coding agent depends on: an edit either matches exactly once (or
`replace_all` says otherwise) and reports a unified diff, or it refuses with a message the
model can act on. Nothing in between — and nothing that silently rewrites the file's line
endings or drops its BOM.
"""

from __future__ import annotations

import codecs
from pathlib import Path

from agent86.config import load_config
from agent86.tools.base import ToolContext
from agent86.tools.builtin.files import EditFileTool, WriteFileTool, unified_diff_for
from agent86.tools.sandbox.policy import default_policy
from agent86.types import ToolCall


def _ctx(tmp_path: Path) -> ToolContext:
    cfg = load_config()
    policy = default_policy(cfg, tmp_path)
    return ToolContext(workspace=policy.workspace, policy=policy, config=cfg)


def _edit(tmp_path: Path, **arguments) -> object:
    call = ToolCall(id="1", name="edit_file", arguments=arguments)
    return EditFileTool().run(call, _ctx(tmp_path))


# ---- matching ---------------------------------------------------------- #


def test_edit_replaces_single_occurrence(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    res = _edit(tmp_path, path="a.py", old_string="beta", new_string="BETA")

    assert res.ok, res.error
    assert target.read_text(encoding="utf-8") == "alpha\nBETA\ngamma\n"
    assert "1 replacement" in res.content


def test_edit_not_found_explains_itself(tmp_path):
    (tmp_path / "a.py").write_text("alpha\n", encoding="utf-8")

    res = _edit(tmp_path, path="a.py", old_string="nope", new_string="x")

    assert not res.ok
    assert "0 matches" in (res.error or "")
    assert "exactly" in (res.error or "")
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "alpha\n"  # untouched


def test_edit_ambiguous_reports_the_count_and_the_way_out(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\nx = 1\nx = 1\n", encoding="utf-8")

    res = _edit(tmp_path, path="a.py", old_string="x = 1", new_string="x = 2")

    assert not res.ok
    assert "3 matches" in (res.error or "")
    assert "replace_all" in (res.error or "")
    # The ambiguous edit must not have written anything.
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\nx = 1\nx = 1\n"


def test_edit_replace_all_rewrites_every_occurrence(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("x = 1\nx = 1\nx = 1\n", encoding="utf-8")

    res = _edit(tmp_path, path="a.py", old_string="x = 1", new_string="x = 2", replace_all=True)

    assert res.ok, res.error
    assert target.read_text(encoding="utf-8") == "x = 2\nx = 2\nx = 2\n"
    assert "3 replacements" in res.content
    assert res.metadata["replacements"] == 3


def test_edit_missing_file_is_a_soft_error(tmp_path):
    res = _edit(tmp_path, path="ghost.py", old_string="a", new_string="b")
    assert not res.ok and "No such file" in (res.error or "")


def test_edit_legacy_old_new_argument_names_still_validate(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("alpha\n", encoding="utf-8")

    res = _edit(tmp_path, path="a.py", old="alpha", new="omega")

    assert res.ok, res.error
    assert target.read_text(encoding="utf-8") == "omega\n"


# ---- encoding & line endings ------------------------------------------- #


def test_crlf_line_endings_are_preserved(tmp_path):
    target = tmp_path / "crlf.txt"
    target.write_bytes(b"one\r\ntwo\r\nthree\r\n")

    res = _edit(tmp_path, path="crlf.txt", old_string="two", new_string="TWO")

    assert res.ok, res.error
    assert target.read_bytes() == b"one\r\nTWO\r\nthree\r\n"


def test_lf_file_does_not_gain_crlf(tmp_path):
    target = tmp_path / "lf.txt"
    target.write_bytes(b"one\ntwo\n")

    assert _edit(tmp_path, path="lf.txt", old_string="two", new_string="TWO").ok
    assert target.read_bytes() == b"one\nTWO\n"


def test_bom_is_preserved(tmp_path):
    target = tmp_path / "bom.txt"
    target.write_bytes(codecs.BOM_UTF8 + b"alpha\n")

    res = _edit(tmp_path, path="bom.txt", old_string="alpha", new_string="omega")

    assert res.ok, res.error
    data = target.read_bytes()
    assert data.startswith(codecs.BOM_UTF8)
    assert data == codecs.BOM_UTF8 + b"omega\n"


def test_binary_file_is_refused_not_mangled(tmp_path):
    target = tmp_path / "blob.bin"
    target.write_bytes(b"\xff\xfe\x00binary")

    res = _edit(tmp_path, path="blob.bin", old_string="binary", new_string="text")

    assert not res.ok and "UTF-8" in (res.error or "")
    assert target.read_bytes() == b"\xff\xfe\x00binary"


# ---- the jail ----------------------------------------------------------- #


def test_edit_outside_the_jail_is_refused(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    res = _edit(tmp_path, path="../outside.txt", old_string="secret", new_string="leaked")

    assert not res.ok and "jail" in (res.error or "").lower()
    assert outside.read_text(encoding="utf-8") == "secret\n"


# ---- diffs -------------------------------------------------------------- #


def test_edit_returns_a_unified_diff(tmp_path):
    (tmp_path / "a.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    res = _edit(tmp_path, path="a.py", old_string="beta", new_string="BETA")

    assert "--- a/a.py" in res.content and "+++ b/a.py" in res.content
    assert "-beta" in res.content and "+BETA" in res.content
    assert res.metadata["diff"] == unified_diff_for("a.py", "alpha\nbeta\ngamma\n",
                                                    "alpha\nBETA\ngamma\n")


def test_write_file_reports_a_diff_against_the_existing_file(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    ctx = _ctx(tmp_path)

    res = WriteFileTool().run(
        ToolCall(id="1", name="write_file", arguments={"path": "a.txt", "content": "one\n2\n"}),
        ctx,
    )

    assert res.ok, res.error
    assert "-two" in res.content and "+2" in res.content
    assert res.metadata["created"] is False


def test_write_file_of_a_new_path_says_new_file_with_a_line_count(tmp_path):
    ctx = _ctx(tmp_path)

    res = WriteFileTool().run(
        ToolCall(id="1", name="write_file", arguments={"path": "n.txt", "content": "a\nb\nc\n"}),
        ctx,
    )

    assert res.ok, res.error
    assert "new file, 3 lines" in res.content
    assert res.metadata["created"] is True


def test_unified_diff_for_is_empty_when_nothing_changed():
    assert unified_diff_for("a.txt", "same\n", "same\n") == ""
