"""``@file`` mentions — pulling a file into the prompt without asking for a tool call.

Typing ``@src/agent86/types.py`` should put that file in front of the model directly: no
round trip, no read_file step, no guessing at a path. This module does that expansion, and
it is the same code on both surfaces — the plain loop calls it before sending, and the TUI
wiring calls it in exactly the same place.

Two hard rules, because a mention is *user* text that makes the harness read the disk:

- every mentioned path goes through :meth:`SandboxPolicy.resolve_within`, so a mention can
  never reach outside the workspace jail. A refused path is reported as an error and is
  never opened — not stat'ed for a size, not sniffed for a type, not read;
- what gets inlined is bounded: a size cap per file (``tools.mention_max_bytes``), at most
  :data:`MAX_DIR_ENTRIES` names for a directory, and binaries refused outright. A mention is
  a convenience, not a bulk loader; anything bigger is the read_file tool's job.

Nothing here imports Textual (it lives in ``tui/`` beside ``commands.py``, the other
surface-shared, Textual-free module) so the plain loop pays nothing for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from agent86.tools.sandbox.policy import PolicyError, SandboxPolicy

#: Fallback for callers without a Config; the real default is ``tools.mention_max_bytes``.
DEFAULT_MAX_BYTES = 200_000
#: Most names listed for a mentioned directory.
MAX_DIR_ENTRIES = 200
#: Most completions offered for a partial ``@`` path.
MAX_COMPLETIONS = 20
#: Directories that are never worth completing into — huge, generated, or not source.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".idea",
    }
)

#: ``@path`` or ``@"path with spaces"``. The lookbehind requires the ``@`` to start the text
#: or follow whitespace/an opening bracket, so ``user@example.com`` is an email address and
#: not a mention of a file called ``example.com``.
_MENTION_RE = re.compile(r'(?<![^\s(\[{])@(?:"([^"\n]+)"|([^\s"\'`]+))')

#: Trailing characters stripped off an unquoted path — prose punctuation, not filename. "."
#: is deliberately absent: it is far more often an extension than a full stop.
_TRAILING_PUNCT = ",;:!?)]}>"

#: Bytes sniffed when deciding whether a file is binary.
_SNIFF_BYTES = 8192


@dataclass
class MentionResult:
    """What one prompt's mentions expanded to.

    ``prompt`` is what to send the model: the user's text unchanged, followed by one block
    per mention. ``attachments`` are the paths actually inlined, and ``errors`` the
    human-readable reasons the rest were not — a surface shows those to the user, but they
    are *also* in ``prompt``, so the model knows a file it was promised is missing rather
    than silently reasoning without it.
    """

    prompt: str
    attachments: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def expanded(self) -> bool:
        """Did this prompt mention anything at all?"""
        return bool(self.attachments or self.errors)


def find_mentions(text: str) -> list[str]:
    """The raw paths mentioned in ``text``, in order, without duplicates."""
    found: list[str] = []
    for match in _MENTION_RE.finditer(text):
        quoted, bare = match.group(1), match.group(2)
        raw = quoted if quoted is not None else (bare or "").rstrip(_TRAILING_PUNCT)
        if raw and raw not in found:
            found.append(raw)
    return found


def expand_mentions(
    text: str, policy: SandboxPolicy, *, max_bytes: int = DEFAULT_MAX_BYTES
) -> MentionResult:
    """Expand every ``@path`` in ``text`` into an inline block, jailed by ``policy``."""
    raws = find_mentions(text)
    if not raws:
        return MentionResult(prompt=text)

    blocks: list[str] = []
    attachments: list[Path] = []
    errors: list[str] = []
    for raw in raws:
        block, path, error = _expand_one(raw, policy, max_bytes)
        blocks.append(block)
        if path is not None:
            attachments.append(path)
        if error is not None:
            errors.append(error)
    prompt = text.rstrip() + "\n\n" + "\n\n".join(blocks)
    return MentionResult(prompt=prompt, attachments=attachments, errors=errors)


# ---- one mention ------------------------------------------------------- #


def _expand_one(
    raw: str, policy: SandboxPolicy, max_bytes: int
) -> tuple[str, Path | None, str | None]:
    """Render one mention. Returns (block, inlined path or None, error or None)."""
    try:
        resolved = policy.resolve_within(raw)
    except PolicyError:
        # Deliberately not echoing the resolved location: the refusal says where the jail
        # is, never what happens to exist outside it.
        return _error(raw, "refused - resolves outside the workspace")
    except (OSError, ValueError) as exc:  # unparseable path (NUL byte, bad drive, ...)
        return _error(raw, f"unreadable path ({type(exc).__name__})")

    try:
        if not resolved.exists():
            return _error(raw, "no such file or directory")
        if resolved.is_dir():
            return _expand_dir(raw, resolved, policy)
        return _expand_file(raw, resolved, policy, max_bytes)
    except OSError as exc:
        return _error(raw, f"could not be read ({type(exc).__name__}: {exc.strerror or exc})")


def _expand_file(
    raw: str, resolved: Path, policy: SandboxPolicy, max_bytes: int
) -> tuple[str, Path | None, str | None]:
    size = resolved.stat().st_size
    if max_bytes and size > max_bytes:
        return _error(
            raw,
            f"{size} bytes is over the {max_bytes}-byte mention cap; "
            "read it with a tool instead of inlining it",
        )
    data = resolved.read_bytes()
    text = _decode(data)
    if text is None:
        return _error(raw, "looks like a binary file")
    label = _display(resolved, policy, raw)
    lines = text.splitlines()
    header = f"--- @{label} ({len(lines)} lines) ---"
    return f"{header}\n{_fenced(text)}", resolved, None


def _expand_dir(
    raw: str, resolved: Path, policy: SandboxPolicy
) -> tuple[str, Path | None, str | None]:
    names: list[str] = []
    for child in sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name in SKIP_DIRS:
            continue
        names.append(child.name + "/" if child.is_dir() else child.name)
    label = _display(resolved, policy, raw)
    shown = names[:MAX_DIR_ENTRIES]
    body = "\n".join(shown) if shown else "(empty)"
    if len(names) > len(shown):
        body += f"\n... and {len(names) - len(shown)} more"
    header = f"--- @{label} (directory, {len(names)} entries) ---"
    return f"{header}\n{_fenced(body)}", resolved, None


def _error(raw: str, reason: str) -> tuple[str, None, str]:
    message = f"@{raw}: {reason}"
    return f"--- @{raw} (not attached) ---\n{reason}", None, message


# ---- helpers ------------------------------------------------------------ #


def _decode(data: bytes) -> str | None:
    """``data`` as text, or None if it is binary."""
    if b"\x00" in data[:_SNIFF_BYTES]:
        return None
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _fenced(body: str) -> str:
    """``body`` in a code fence long enough to survive backticks inside it."""
    longest = max((len(run) for run in re.findall(r"`+", body)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{body.rstrip(chr(10))}\n{fence}"


def _display(resolved: Path, policy: SandboxPolicy, raw: str) -> str:
    """The path as the user should see it: workspace-relative when it can be."""
    try:
        return resolved.relative_to(policy.workspace.resolve()).as_posix()
    except ValueError:
        # Inside an `allow_paths` root rather than the workspace: show what they typed.
        return raw


# ---- completion --------------------------------------------------------- #


def complete_mentions(prefix: str, workspace: Path) -> list[str]:
    """Up to :data:`MAX_COMPLETIONS` workspace paths matching a partial ``@`` mention.

    ``prefix`` is what follows the ``@`` (a leading ``@`` and wrapping quotes are tolerated).
    Results are workspace-relative, POSIX-separated, directories first and suffixed with
    ``/`` so a second Tab can descend into them. Noise directories (:data:`SKIP_DIRS`) and
    dotfiles are hidden unless the prefix asks for them by name.
    """
    cleaned = prefix.strip().lstrip("@").strip('"').replace("\\", "/")
    head, sep, tail = cleaned.rpartition("/")
    root = workspace.resolve()
    directory = (root / head) if sep else root
    try:
        directory = directory.resolve()
        # Never complete outside the workspace, whatever "../.." the prefix contains.
        if directory != root and root not in directory.parents:
            return []
        children = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return []

    needle = tail.lower()
    out: list[str] = []
    for child in children:
        name = child.name
        if not name.lower().startswith(needle):
            continue
        if name in SKIP_DIRS and needle != name.lower():
            continue
        if name.startswith(".") and not needle.startswith("."):
            continue
        try:
            is_dir = child.is_dir()
        except OSError:  # a broken symlink, a permission wall
            is_dir = False
        out.append((f"{head}/{name}" if sep else name) + ("/" if is_dir else ""))
        if len(out) >= MAX_COMPLETIONS:
            break
    return out


__all__ = [
    "DEFAULT_MAX_BYTES",
    "MAX_COMPLETIONS",
    "MAX_DIR_ENTRIES",
    "SKIP_DIRS",
    "MentionResult",
    "complete_mentions",
    "expand_mentions",
    "find_mentions",
]
