"""Trace redaction (Tier 5).

The flight recorder is an append-only file under ``~/.agent86/traces`` that nothing ever
prunes for content. Everything the harness sees flows through it: the user's task text, the
model's tool arguments, and whatever a tool read off disk. So a key pasted into a prompt, or
a ``.env`` a tool happened to cat, used to land in plain text in a file that outlives the
session and gets attached to bug reports.

:func:`redact_event` is the one gate between an event and the file:

* **secret shapes** — every string, at any depth, is rewritten with the *same* regexes the
  guardrail tier already uses (:mod:`agent86.guardrails.scanners` for the provider key shapes
  and credential assignments, :mod:`agent86.secrets` for the key-shaped-token catch-all).
  They are imported, never re-spelled: one place to fix when a provider invents a new prefix.
* **size** — the big free-text fields (``arguments``, ``task``, ``content``, ``error``,
  ``outcome``, and anything nested inside them) are clipped to
  ``[observability] max_field_chars`` with a visible ``…[truncated N chars]`` marker, so a
  tool that returned a 40 MB file does not become 40 MB of trace.

It never raises. A value that cannot be walked or serialised falls back to ``str()``; a
redaction failure degrades to the untouched event rather than losing the record, because a
trace that drops events is worse than a trace with a long line in it.
"""

from __future__ import annotations

import re
from typing import Any

#: What a matched secret becomes. Deliberately loud and unambiguous when grepping a trace.
REDACTED = "***REDACTED***"

#: Default clip for the free-text fields; mirrors ``ObservabilityConfig.max_field_chars``.
DEFAULT_MAX_FIELD_CHARS = 2000

#: Fields whose values are free text large enough to matter. Truncation is *inherited*: once
#: inside ``arguments``, every nested string is a candidate, because the model chooses those
#: key names and we cannot enumerate them.
TRUNCATE_FIELDS = frozenset({"arguments", "task", "content", "error", "outcome"})


def _secret_patterns() -> list[re.Pattern[str]]:
    """The guardrail tier's secret regexes, reused rather than duplicated.

    Read through ``getattr`` and guarded: these are private names in modules this file does
    not own, and an observability import must never be the thing that breaks the harness.
    """
    patterns: list[re.Pattern[str]] = []
    try:
        from agent86.guardrails import scanners

        for entry in getattr(scanners, "_SECRETS", ()):
            rx = entry[0] if isinstance(entry, tuple) else entry
            if isinstance(rx, re.Pattern):
                patterns.append(rx)
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        from agent86 import secrets as secrets_mod

        rx = getattr(secrets_mod, "_KEY_SHAPES", None)
        if isinstance(rx, re.Pattern):
            patterns.append(rx)
    except Exception:  # pragma: no cover - defensive
        pass
    return patterns


_PATTERNS = _secret_patterns()


def scrub_secrets(text: str) -> str:
    """Replace every secret-shaped run in ``text`` with :data:`REDACTED`."""
    out = text
    for rx in _PATTERNS:
        try:
            out = rx.sub(REDACTED, out)
        except Exception:  # pragma: no cover - defensive
            continue
    return out


def _clip(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    dropped = len(text) - limit
    return f"{text[:limit]}…[truncated {dropped} chars]"


def _walk(value: Any, *, limit: int, truncate: bool, depth: int = 0) -> Any:
    """Recursively rewrite ``value``. Never raises; unknown types become ``str()``."""
    if depth > 24:  # pathological nesting / cycles
        return _clip(scrub_secrets(str(value)), limit)
    if isinstance(value, str):
        cleaned = scrub_secrets(value)
        return _clip(cleaned, limit) if truncate else cleaned
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            child = truncate or (isinstance(key, str) and key in TRUNCATE_FIELDS)
            out[key] = _walk(item, limit=limit, truncate=child, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_walk(item, limit=limit, truncate=truncate, depth=depth + 1) for item in value]
    # Anything else (a Pydantic model, a Path, an exception, a socket) — the recorder's own
    # json ``default=str`` would stringify it anyway, so do it here where it can be scrubbed.
    return _walk(str(value), limit=limit, truncate=truncate, depth=depth + 1)


def redact_event(
    event: dict,
    *,
    mode: str = "secrets",
    max_field_chars: int = DEFAULT_MAX_FIELD_CHARS,
) -> dict:
    """Return a redacted copy of one recorder event.

    ``mode="none"`` returns the event untouched (opt-out for a local debugging session);
    ``mode="secrets"`` scrubs secret shapes everywhere and clips the big free-text fields.
    """
    if str(mode) == "none":
        return event
    try:
        result = _walk(event, limit=max_field_chars, truncate=False)
    except Exception:  # pragma: no cover - defensive: never lose an event to redaction
        return event
    return result if isinstance(result, dict) else event


__all__ = [
    "DEFAULT_MAX_FIELD_CHARS",
    "REDACTED",
    "TRUNCATE_FIELDS",
    "redact_event",
    "scrub_secrets",
]
