"""Comment-preserving config write-back (MODEL-02).

``agent86.config`` reads TOML with stdlib ``tomllib``; that path is read-only by design and is
left completely untouched here. This module adds the *write* half using ``tomlkit``, whose CST
model round-trips comments, blank lines, and formatting — success criterion 3 requires that a
user's hand-written comments in ``~/.agent86/config.toml`` survive every save.

Two-step by design (D-17): ``plan_edit`` computes the new text and a unified diff **without
touching disk**, so a modal can show the user exactly what will change; ``apply_edit`` then
writes atomically and reloads via ``load_config`` (no merge logic is duplicated here).

Secrets are never written (D-06/SEC-01): ``plan_edit`` refuses secret-looking leaf keys.
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
_FORBIDDEN_LEAF_KEYS = frozenset({"api_key", "apikey", "key", "token", "secret", "password"})


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
        leaf = key_path[-1].lower()
        if leaf in _FORBIDDEN_LEAF_KEYS:
            raise ValueError(
                f"refusing to write '{'.'.join(key_path)}' to config: secrets belong in the OS "
                "keyring, config may only name the env var (api_key_env)"
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
    "ConfigEdit",
    "ConfigWriteError",
    "scope_path",
    "plan_edit",
    "apply_edit",
]
