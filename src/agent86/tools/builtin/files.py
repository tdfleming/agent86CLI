"""Built-in file tools: read, write, edit, list — all jailed to the workspace.

Every mutation answers with a **unified diff** rather than a bare "wrote N bytes": the diff
is what the approval gate shows the user before the write happens (``Tool.preview``) and what
the model reads back afterwards, so both sides judge the same artifact.

``edit_file`` is byte-preserving by design. It decodes the file itself (BOM detected, CRLF
normalised for matching) and re-encodes with the file's *original* line endings and BOM, so a
one-line edit to a CRLF file does not rewrite every line of it — which would turn a two-line
diff into a whole-file diff in the user's VCS.
"""

from __future__ import annotations

import codecs
import difflib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, Field

from agent86.tools.base import Tool, ToolContext
from agent86.types import ToolResult

#: How many lines of a brand-new file the approval preview shows before eliding the rest.
PREVIEW_HEAD_LINES = 40
#: Lines of unchanged context either side of a hunk.
DIFF_CONTEXT_LINES = 3

_BOM = codecs.BOM_UTF8


def _fail(name: str, msg: str) -> ToolResult:
    return ToolResult(call_id="", name=name, ok=False, error=msg)


# --------------------------------------------------------------------------- #
# Diffing
# --------------------------------------------------------------------------- #


def unified_diff_for(
    path: str, old_text: str, new_text: str, *, context: int = DIFF_CONTEXT_LINES
) -> str:
    """A unified diff from ``old_text`` to ``new_text``, labelled with ``path``.

    Shared by the tools (which return it as the observation) and by the approval preview
    (which renders it *before* the write). Returns ``""`` when the texts are identical.
    """
    diff = difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
        n=context,
    )
    return "\n".join(diff)


def head_of(text: str, limit: int = PREVIEW_HEAD_LINES) -> str:
    """The first ``limit`` lines of ``text``, with a marker when anything was dropped."""
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    return "\n".join(lines[:limit]) + f"\n... [{len(lines) - limit} more lines]"


def new_file_summary(path: str, content: str) -> str:
    """What a write to a not-yet-existing ``path`` would create."""
    count = len(content.splitlines())
    return f"new file: {path} ({count} line{'' if count == 1 else 's'})\n" + head_of(content)


# --------------------------------------------------------------------------- #
# Encoding-preserving read/write
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FileText:
    """A decoded text file plus the two facts needed to write it back unchanged."""

    text: str  # newline-normalised to "\n", BOM stripped
    newline: str  # the file's dominant line terminator
    bom: bool  # did the file start with a UTF-8 BOM?

    def encode(self, text: str) -> bytes:
        """Re-encode ``text`` with this file's original line endings and BOM."""
        if self.newline != "\n":
            text = text.replace("\n", self.newline)
        data = text.encode("utf-8")
        return _BOM + data if self.bom else data


def read_file_text(target: Path) -> FileText:
    """Decode ``target`` as UTF-8, remembering its BOM and line endings.

    Raises ``UnicodeDecodeError`` for a non-UTF-8 (likely binary) file — better a structured
    refusal than a lossy ``errors="replace"`` round-trip that corrupts the file on write.
    """
    data = target.read_bytes()
    bom = data.startswith(_BOM)
    if bom:
        data = data[len(_BOM) :]
    text = data.decode("utf-8")
    crlf = text.count("\r\n")
    # Only a *consistently* CRLF file is normalised; a mixed file is matched and written
    # verbatim, because converting its lone LFs would rewrite lines nobody asked to touch.
    if crlf and crlf == text.count("\n"):
        return FileText(text.replace("\r\n", "\n"), "\r\n", bom)
    return FileText(text, "\n", bom)


def _existing_text(target: Path) -> str | None:
    """The current contents of ``target`` as LF text, or None if it is unreadable/absent."""
    try:
        if not target.is_file():
            return None
        return read_file_text(target).text
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _preview_target(path_str: str, ctx: ToolContext | None) -> Path | None:
    """Resolve ``path_str`` for a *preview* — never raising, jail-respecting when we have one.

    The approval gate may not carry a ``ToolContext`` (it is constructed before one exists),
    so the fallback resolves against the process CWD, which is the default workspace. A
    preview that cannot resolve simply shows less; it never blocks the prompt.
    """
    try:
        if ctx is not None:
            return ctx.policy.resolve_within(path_str)
        candidate = Path(path_str)
        return candidate if candidate.is_absolute() else Path.cwd() / candidate
    except Exception:  # pragma: no cover - defensive; a preview must never raise
        return None


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


class ReadFileTool(Tool["ReadFileTool.Args"]):
    name = "read_file"
    description = "Read a UTF-8 text file within the workspace and return its contents."
    side_effecting = False

    class Args(BaseModel):
        path: str = Field(..., description="Path to the file, relative to the workspace.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        target = ctx.policy.resolve_within(args.path)
        if not target.exists():
            return _fail(self.name, f"No such file: {args.path}")
        if not target.is_file():
            return _fail(self.name, f"Not a file: {args.path}")
        text = target.read_text(encoding="utf-8", errors="replace")
        return ToolResult(call_id="", name=self.name, content=ctx.policy.truncate(text))


class WriteFileTool(Tool["WriteFileTool.Args"]):
    name = "write_file"
    description = (
        "Create or overwrite a text file within the workspace (creates parent dirs). "
        "Returns a unified diff of what changed."
    )
    side_effecting = True
    preview_lexer = "diff"

    class Args(BaseModel):
        path: str = Field(..., description="Path to write, relative to the workspace.")
        content: str = Field(..., description="Full file contents to write.")

    def preview(self, arguments: Mapping[str, Any], ctx: ToolContext | None = None) -> str | None:
        path = arguments.get("path")
        content = arguments.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            return None
        target = _preview_target(path, ctx)
        current = _existing_text(target) if target is not None else None
        if current is None:
            return new_file_summary(path, content)
        diff = unified_diff_for(path, current, content)
        return diff or f"{path} is already exactly this content (no change)."

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        target = ctx.policy.resolve_within(args.path)
        existed = _existing_text(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(args.content, encoding="utf-8")
        if existed is None:
            count = len(args.content.splitlines())
            detail = f"new file, {count} line{'' if count == 1 else 's'}"
            diff = ""
        else:
            diff = unified_diff_for(args.path, existed, args.content)
            detail = diff or "no change"
        kind = "new file" if existed is None else "overwrite"
        header = f"Wrote {len(args.content)} bytes to {args.path} ({kind})."
        body = f"{header}\n{detail}" if detail else header
        return ToolResult(
            call_id="",
            name=self.name,
            content=ctx.policy.truncate(body),
            metadata={"path": args.path, "diff": diff, "created": existed is None},
        )


class EditFileTool(Tool["EditFileTool.Args"]):
    name = "edit_file"
    description = (
        "Replace an exact substring in a workspace file and return a unified diff of the "
        "change. `old_string` must match the file exactly (whitespace included) and must be "
        "unique unless `replace_all` is true."
    )
    side_effecting = True
    preview_lexer = "diff"

    class Args(BaseModel):
        path: str = Field(..., description="Path to the file, relative to the workspace.")
        # `old`/`new` are the pre-v0.9 names; accepted so a model (or an older transcript)
        # using them still lands on the same field rather than a validation error.
        old_string: str = Field(
            ...,
            validation_alias=AliasChoices("old_string", "old"),
            description="Exact text to replace, including indentation and line breaks.",
        )
        new_string: str = Field(
            ...,
            validation_alias=AliasChoices("new_string", "new"),
            description="Replacement text.",
        )
        replace_all: bool = Field(
            default=False,
            description="Replace every occurrence instead of failing when there is more than one.",
        )

    def preview(self, arguments: Mapping[str, Any], ctx: ToolContext | None = None) -> str | None:
        path = arguments.get("path")
        old = arguments.get("old_string", arguments.get("old"))
        new = arguments.get("new_string", arguments.get("new"))
        if not isinstance(path, str) or not isinstance(old, str) or not isinstance(new, str):
            return None
        target = _preview_target(path, ctx)
        current = _existing_text(target) if target is not None else None
        if current is None:
            return f"{path}: cannot be read (missing, or not a UTF-8 text file)."
        count = current.count(old)
        if count == 0:
            return f"{path}: old_string was NOT found — this edit would fail."
        replace_all = bool(arguments.get("replace_all", False))
        if count > 1 and not replace_all:
            return f"{path}: old_string is ambiguous — {count} matches, and replace_all is off."
        updated = current.replace(old, new) if replace_all else current.replace(old, new, 1)
        diff = unified_diff_for(path, current, updated)
        if count > 1:
            return f"{count} occurrences replaced\n{diff}"
        return diff or f"{path}: old_string and new_string are identical (no change)."

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        target = ctx.policy.resolve_within(args.path)
        if not target.is_file():
            return _fail(self.name, f"No such file: {args.path}")
        if not args.old_string:
            return _fail(
                self.name, "old_string must not be empty; use write_file to create a file."
            )
        try:
            doc = read_file_text(target)
        except UnicodeDecodeError:
            return _fail(self.name, f"Not a UTF-8 text file: {args.path}")
        except OSError as exc:
            return _fail(self.name, f"Could not read {args.path}: {exc}")

        count = doc.text.count(args.old_string)
        if count == 0:
            return _fail(
                self.name,
                f"old_string not found in {args.path} (0 matches). It must match the file "
                "exactly, including indentation and line breaks — read the file and copy the "
                "text verbatim.",
            )
        if count > 1 and not args.replace_all:
            return _fail(
                self.name,
                f"old_string is ambiguous in {args.path}: {count} matches. Include more "
                f"surrounding context so it matches exactly once, or pass replace_all=true "
                f"to replace all {count}.",
            )
        if args.old_string == args.new_string:
            return _fail(self.name, "old_string and new_string are identical; nothing to do.")

        if args.replace_all:
            updated, replaced = doc.text.replace(args.old_string, args.new_string), count
        else:
            updated, replaced = doc.text.replace(args.old_string, args.new_string, 1), 1
        diff = unified_diff_for(args.path, doc.text, updated)
        target.write_bytes(doc.encode(updated))
        header = f"Edited {args.path} ({replaced} replacement{'' if replaced == 1 else 's'})."
        return ToolResult(
            call_id="",
            name=self.name,
            content=ctx.policy.truncate(f"{header}\n{diff}" if diff else header),
            metadata={"path": args.path, "diff": diff, "replacements": replaced},
        )


class ListDirTool(Tool["ListDirTool.Args"]):
    name = "list_dir"
    description = "List the entries of a directory within the workspace."
    side_effecting = False

    class Args(BaseModel):
        path: str = Field(default=".", description="Directory path, relative to the workspace.")

    def execute(self, args: Args, ctx: ToolContext) -> ToolResult:
        target = ctx.policy.resolve_within(args.path)
        if not target.is_dir():
            return _fail(self.name, f"Not a directory: {args.path}")
        lines = []
        for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            marker = "/" if entry.is_dir() else ""
            lines.append(f"{entry.name}{marker}")
        body = "\n".join(lines) if lines else "(empty)"
        return ToolResult(call_id="", name=self.name, content=ctx.policy.truncate(body))


__all__ = [
    "ReadFileTool",
    "WriteFileTool",
    "EditFileTool",
    "ListDirTool",
    "FileText",
    "read_file_text",
    "unified_diff_for",
    "head_of",
    "new_file_summary",
    "PREVIEW_HEAD_LINES",
]
