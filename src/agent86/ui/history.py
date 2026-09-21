"""Prompt history — the one file both interactive surfaces append to.

Deliberately dependency-free (stdlib only, no Textual, no Rich): the plain loop imports it
at module level, and the Textual prompt widget layers navigation on top of the same object,
so a prompt typed under ``--plain`` is there the next time the TUI starts and vice versa.

The rules are bash's, because they're the ones people already have in their fingers:

- a line starting with a space is never recorded (the "don't remember this" escape hatch);
- a line identical to the one before it is not recorded twice;
- the file is capped at ``history_size`` entries, oldest dropped first.

Storage is one entry per line. A prompt may itself be multi-line (the TUI's prompt is a
``TextArea``), so newlines are escaped on write and unescaped on read — that keeps the file
line-oriented and greppable while round-tripping a pasted block exactly.

Every filesystem interaction is best-effort. A history file that is missing, unreadable,
half-written or full of binary junk must never be the thing that stops a REPL from starting:
loading degrades to "no history", appending degrades to "this session only".
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

#: Defaults mirrored from ``UIConfig`` so a ``PromptHistory`` is usable without a Config.
DEFAULT_HISTORY_FILE = "~/.agent86/history"
DEFAULT_HISTORY_SIZE = 1000


def history_path(path: str | os.PathLike[str]) -> Path:
    """``path`` with ``~`` and ``$VARS`` expanded — where history actually lives."""
    return Path(os.path.expandvars(os.path.expanduser(str(path))))


def _encode(entry: str) -> str:
    """One entry as one physical line (backslash and newline escaped)."""
    return entry.replace("\\", "\\\\").replace("\r\n", "\n").replace("\n", "\\n")


def _decode(line: str) -> str:
    """Inverse of :func:`_encode`, tolerant of a trailing lone backslash."""
    out: list[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            nxt = line[i + 1]
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def storable(line: str) -> bool:
    """Is this line worth remembering? (bash rules: no blanks, nothing leading-space.)"""
    if not line or line.startswith((" ", "\t")):
        return False
    return bool(line.strip())


class PromptHistory:
    """The recorded prompts, oldest first, backed by ``path`` (None = memory only)."""

    def __init__(
        self,
        path: str | os.PathLike[str] | None = DEFAULT_HISTORY_FILE,
        *,
        max_entries: int = DEFAULT_HISTORY_SIZE,
        load: bool = True,
    ) -> None:
        self.path: Path | None = history_path(path) if path else None
        #: 0 disables the cap entirely.
        self.max_entries = max(0, int(max_entries))
        self._entries: list[str] = []
        if load:
            self.load()

    # ---- reading -------------------------------------------------------- #

    def load(self) -> list[str]:
        """(Re)read the file into memory. A missing or corrupt file yields no history."""
        self._entries = []
        if self.path is None:
            return []
        try:
            # errors="replace", not strict: a file with one mangled byte should cost the
            # user that one line's fidelity, not their whole history.
            raw = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        entries: list[str] = []
        for line in raw.splitlines():
            entry = _decode(line)
            if not storable(entry) or "\x00" in entry:
                continue
            if entries and entries[-1] == entry:
                continue
            entries.append(entry)
        self._entries = self._capped(entries)
        return list(self._entries)

    @property
    def entries(self) -> list[str]:
        """A copy of the recorded prompts, oldest first."""
        return list(self._entries)

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._entries))

    def __len__(self) -> int:
        return len(self._entries)

    def __getitem__(self, index: int) -> str:
        return self._entries[index]

    def __bool__(self) -> bool:
        return bool(self._entries)

    # ---- writing -------------------------------------------------------- #

    def append(self, line: str) -> bool:
        """Record a submitted prompt. Returns True if it was kept.

        Refused (and returns False) for a blank line, a leading-space line, or an exact
        repeat of the previous entry. A file that can't be written is not an error — the
        entry still lives in memory for the rest of the session.
        """
        if not storable(line):
            return False
        if self._entries and self._entries[-1] == line:
            return False
        self._entries.append(line)
        if self.max_entries and len(self._entries) > self.max_entries:
            # Over the cap: rewrite the whole file rather than append to it, so the file on
            # disk is exactly what's in memory.
            self._entries = self._capped(self._entries)
            self._rewrite()
        else:
            self._append_line(line)
        return True

    def _capped(self, entries: list[str]) -> list[str]:
        if self.max_entries and len(entries) > self.max_entries:
            return entries[-self.max_entries :]
        return entries

    def _append_line(self, line: str) -> None:
        """Append one entry with a single write — the cheap, concurrent-safe path.

        Opened in append mode, so two agent86 sessions sharing a history file interleave
        whole lines instead of overwriting each other's.
        """
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(_encode(line) + "\n")
        except OSError:
            return

    def _rewrite(self) -> None:
        """Replace the file with the in-memory entries, atomically (temp file + rename)."""
        if self.path is None:
            return
        payload = "".join(_encode(e) + "\n" for e in self._entries)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".history-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(payload)
                os.replace(tmp, self.path)
            except OSError:
                # Leave no stray temp file behind when the rename is what failed.
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError:
            return


def build_history(config) -> PromptHistory:  # noqa: ANN001 - Config, kept import-free
    """A :class:`PromptHistory` wired from ``[ui] history_file`` / ``history_size``."""
    return PromptHistory(config.ui.history_file, max_entries=config.ui.history_size)


__all__ = [
    "DEFAULT_HISTORY_FILE",
    "DEFAULT_HISTORY_SIZE",
    "PromptHistory",
    "build_history",
    "history_path",
    "storable",
]
