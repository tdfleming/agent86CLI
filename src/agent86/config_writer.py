"""Comment-preserving config write-back (MODEL-02).

``agent86.config`` reads TOML with stdlib ``tomllib``; that path is read-only by design and is
left completely untouched here. This module adds the *write* half using ``tomlkit``, whose CST
model round-trips comments, blank lines, and formatting — success criterion 3 requires that a
user's hand-written comments in ``~/.agent86/config.toml`` survive every save.

Two-step by design (D-17): ``plan_edit`` computes the new text and a unified diff **without
touching disk**, so a modal can show the user exactly what will change; ``apply_edit`` then
writes atomically and reloads via ``load_config`` (no merge logic is duplicated here).

Secrets are never written (D-06/SEC-01): ``plan_edit`` refuses secret-looking leaf keys, unless
the value is a pure ``${VAR}`` reference (D-17) — the one accepted form under a secret-shaped
leaf key, e.g. MCP ``headers.Authorization`` or ``env.TOKEN``.
``tomlkit`` is imported lazily inside function bodies so ``run``/``--plain`` cold start does not
pay for it (guarded by ``tests/tui/test_lazy_import.py``).
"""

from __future__ import annotations

import difflib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent86.config import PROJECT_CONFIG_PATH, USER_CONFIG_PATH, Config, load_config

SCOPE_USER = "user"
SCOPE_PROJECT = "project"

#: Leaf key names that would put a plaintext secret in config. Config only ever names the *env
#: var* that holds a key (``api_key_env``); the key itself lives in the OS keyring.
#: ``authorization`` closes the SEC-01 hole opened by MCP ``headers.Authorization`` (D-17) —
#: before Phase 4 a bearer token written there passed this guard entirely.
_FORBIDDEN_LEAF_KEYS = frozenset(
    {"api_key", "apikey", "key", "token", "secret", "password", "authorization"}
)


class _Delete:
    """Sentinel type for :data:`DELETE`; a distinct class so ``repr`` is legible in errors."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "DELETE"


#: Marker value in ``plan_edit``'s ``changes`` list meaning "remove this key path" (D-10).
#: One code path, one diff: a single edit can delete one server and set a key on another.
DELETE = _Delete()


class ConfigWriteError(RuntimeError):
    """The target config file could not be parsed or written."""


@dataclass(frozen=True)
class ConfigEdit:
    """A prepared, not-yet-committed change to one config file."""

    scope: str
    path: Path
    before_text: str
    after_text: str
    diff: str

    @property
    def is_noop(self) -> bool:
        return self.before_text == self.after_text


def scope_path(scope: str) -> Path:
    if scope == SCOPE_USER:
        return USER_CONFIG_PATH
    if scope == SCOPE_PROJECT:
        return PROJECT_CONFIG_PATH
    raise ValueError(f"unknown config scope '{scope}' (expected 'user' or 'project')")


def _is_var_ref(value: Any) -> bool:
    """True when ``value`` is a pure ``${VAR}``-reference string, never a literal secret (D-17).

    "Pure" means: it contains at least one ``${VAR}`` and, once every reference is blanked out,
    what remains holds no key-shaped token. That rejects
    ``"sk-liveXXXXXXXXXXXXXXXX${notreal}"`` — appending a decoy reference must not smuggle a real
    secret past the guard (RESEARCH Pitfall 2).
    """
    from agent86.secrets import _KEY_SHAPES, _VAR_REF_RE, find_var_refs

    if not isinstance(value, str) or not find_var_refs(value):
        return False
    return not _KEY_SHAPES.search(_VAR_REF_RE.sub("", value))


def _pop_trailing_trivia(table: Any) -> list[Any]:
    """Pop trailing ``Whitespace``/``Comment`` body items (a hand-written comment that visually
    precedes the *next* table, but that tomlkit parses as trailing content of *this* one) so a
    delete doesn't silently discard a comment that belongs to a sibling that survives.
    """
    from tomlkit.items import Comment, Whitespace

    container = table.value if hasattr(table, "value") else table
    body = getattr(container, "_body", None)
    if body is None:
        return []
    trailing: list[Any] = []
    while body and body[-1][0] is None and isinstance(body[-1][1], (Whitespace, Comment)):
        trailing.append(body.pop()[1])
    trailing.reverse()
    return trailing


def _apply_delete(doc: Any, key_path: list[str]) -> None:
    """Remove ``key_path`` from the tomlkit document. Missing paths are a silent no-op.

    Idempotent by design (RESEARCH Open Question 1): deleting a server a user already removed by
    hand must render as "No changes." in SaveDiffModal, not crash the modal.

    A trailing hand-written comment inside the deleted table is re-homed onto the parent
    container rather than discarded (RESEARCH Pitfall — tomlkit attaches a comment between two
    table headers to the *preceding* table's own body, not the container between them).
    """
    node: Any = doc
    for part in key_path[:-1]:
        if not hasattr(node, "get"):
            return
        nxt = node.get(part)
        if nxt is None:
            return
        node = nxt
    leaf = key_path[-1]
    if not (hasattr(node, "__contains__") and leaf in node):
        return
    trailing = _pop_trailing_trivia(node[leaf])
    del node[leaf]
    container = node.value if hasattr(node, "value") else node
    for item in trailing:
        container._raw_append(None, item)


def plan_edit(scope: str, changes: list[tuple[list[str], Any]]) -> ConfigEdit:
    """Compute the post-change text and a unified diff. Touches nothing on disk.

    ``changes`` is a list of ``(key_path, value)`` pairs, e.g.
    ``(["providers", "groq", "api_key_env"], "GROQ_API_KEY")`` or
    ``(["model", "default"], "groq:llama-3.3-70b-versatile")``.
    """
    import tomlkit

    path = scope_path(scope)
    before_text = _read_text(path)
    try:
        doc = tomlkit.parse(before_text) if before_text else tomlkit.document()
    except Exception as exc:  # tomlkit.exceptions.ParseError and friends
        raise ConfigWriteError(f"Malformed config at {path}: {exc}") from exc

    for key_path, value in changes:
        if not key_path:
            raise ValueError("empty key path in changes")
        if value is DELETE:
            _apply_delete(doc, key_path)
            continue
        leaf = key_path[-1].lower()
        if leaf in _FORBIDDEN_LEAF_KEYS and not _is_var_ref(value):
            raise ValueError(
                f"refusing to write '{'.'.join(key_path)}' to config: secrets belong in the OS "
                "keyring or a ${VAR} reference, never a literal value"
            )
        node: Any = doc
        for part in key_path[:-1]:
            existing = node.get(part)
            if existing is None:
                existing = tomlkit.table()
                node[part] = existing
            node = existing
        node[key_path[-1]] = value

    after_text = doc.as_string()
    diff = "\n".join(
        difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile=str(path),
            tofile=str(path),
            lineterm="",
        )
    )
    return ConfigEdit(
        scope=scope, path=path, before_text=before_text, after_text=after_text, diff=diff
    )


def apply_edit(edit: ConfigEdit) -> Config:
    """Write ``edit.after_text`` atomically, then return a freshly resolved :class:`Config`."""
    _write_atomic(edit.path, edit.after_text)
    return load_config()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise ConfigWriteError(f"Could not read {path}: {exc}") from exc


def _write_atomic(path: Path, text: str) -> None:
    """Write-then-rename so a crash mid-write never truncates an existing config.

    ``tempfile.mkstemp(dir=path.parent, ...)`` guarantees the temp file is on the same volume,
    which is what makes ``os.replace`` atomic on Windows (NTFS) as well as POSIX.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".toml.tmp")
    except OSError as exc:
        raise ConfigWriteError(f"Could not write {path}: {exc}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


__all__ = [
    "SCOPE_USER",
    "SCOPE_PROJECT",
    "DELETE",
    "ConfigEdit",
    "ConfigWriteError",
    "scope_path",
    "plan_edit",
    "apply_edit",
]
