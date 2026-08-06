"""OS-keyring-backed API key resolution (SEC-01).

Precedence is strict and non-negotiable (D-06): the environment variable named by a provider's
``api_key_env`` wins; only when it is unset do we consult the OS keyring. Config files never
hold a plaintext secret — see ``agent86.config``'s module docstring.

Keyring naming (D-07): service ``"agent86"``, account = the *config section name* for the
provider (``ref.provider``), so a custom ``[providers.myvllm]`` block gets its own slot and the
entry is legible in Windows Credential Manager / macOS Keychain.

``keyring`` is imported lazily inside every function body — importing it eagerly anywhere
reachable from ``agent86.cli`` breaks the cold-start guarantee for ``run`` and ``--plain``
(guarded by ``tests/tui/test_lazy_import.py``).
"""

from __future__ import annotations

import os
import re

SERVICE_NAME = "agent86"

_REDACTED = "***redacted***"

#: Token shapes that are almost certainly a credential. Deliberately conservative:
#: a false positive only makes an error message less precise, a false negative leaks.
_KEY_SHAPES = re.compile(
    r"\b(?:sk-[A-Za-z0-9._\-]{16,}"
    r"|gsk_[A-Za-z0-9]{20,}"
    r"|xai-[A-Za-z0-9]{20,}"
    r"|AIza[A-Za-z0-9_\-]{20,})\b"
)


def redact(text: str, *secrets: str | None) -> str:
    """Return `text` with every known secret and key-shaped token replaced.

    SEC-01 / D-10: used on any string that may be shown to a human (error messages,
    transcript lines, logs). Never raises; a `None`/empty secret is ignored.
    """
    out = text
    for secret in secrets:
        if secret and len(secret) >= 8:
            out = out.replace(secret, _REDACTED)
    return _KEY_SHAPES.sub(_REDACTED, out)


class SecretStoreError(RuntimeError):
    """The keyring refused to store or delete a secret."""


def resolve_api_key(provider_name: str, api_key_env: str | None) -> str | None:
    """Env var first, then the OS keyring. Never raises.

    Returns ``None`` when nothing is found or the keyring backend is unusable — headless/CI
    degrades silently to env-only (D-09). ``api_key_env`` being falsy short-circuits before the
    keyring is ever consulted, so keyless local endpoints (Ollama, llama.cpp) are unaffected by
    stray keyring entries (RESEARCH Pitfall 5).
    """
    if not api_key_env:
        return None
    if val := os.getenv(api_key_env):
        return val
    try:
        import keyring
        import keyring.errors  # noqa: F401
    except Exception:  # noqa: BLE001 - absent or broken install degrades to env-only
        return None
    try:
        return keyring.get_password(SERVICE_NAME, provider_name)
    except Exception:  # noqa: BLE001 - any backend error degrades to env-only (D-09)
        return None


def keyring_available() -> bool:
    """Whether a real keyring backend is usable (D-09 visibility in /config).

    Distinguishes "no backend" from "no key stored". ``keyring.get_keyring()`` forces backend
    detection; the sentinel installed when nothing works lives in ``keyring.backends.fail``.
    """
    try:
        import keyring

        backend = keyring.get_keyring()
        return type(backend).__module__ != "keyring.backends.fail"
    except Exception:  # noqa: BLE001
        return False


def has_stored_key(provider_name: str) -> bool:
    """True when the keyring holds a key for ``provider_name`` (never reads the env)."""
    try:
        import keyring

        return keyring.get_password(SERVICE_NAME, provider_name) is not None
    except Exception:  # noqa: BLE001
        return False


def store_api_key(provider_name: str, key: str) -> None:
    """Store (silently overwriting) ``key`` under service "agent86" / account ``provider_name``.

    Raises :class:`SecretStoreError` on any backend failure — e.g. Windows Credential Manager's
    payload size limit (RESEARCH Pitfall 3) — so the calling modal can show a clear message
    instead of crashing.
    """
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, provider_name, key)
    except Exception as exc:  # noqa: BLE001
        raise SecretStoreError(f"Could not store the key for '{provider_name}': {exc}") from exc


def clear_api_key(provider_name: str) -> bool:
    """Delete the stored key. Returns True if one was deleted, False if none was stored."""
    try:
        import keyring

        if keyring.get_password(SERVICE_NAME, provider_name) is None:
            return False
        keyring.delete_password(SERVICE_NAME, provider_name)
        return True
    except Exception:  # noqa: BLE001
        return False


__all__ = [
    "SERVICE_NAME",
    "SecretStoreError",
    "redact",
    "resolve_api_key",
    "keyring_available",
    "has_stored_key",
    "store_api_key",
    "clear_api_key",
]
