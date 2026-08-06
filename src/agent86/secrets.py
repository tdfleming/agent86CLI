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

MCP server configs (MCP-01) reference secrets as ``${VAR}`` rather than a literal value; a
server's command/args/env/headers are resolved at connect time via ``expand_var_refs``, which
applies the exact same env-first-then-keyring precedence as ``resolve_api_key`` above, keyed by
variable name.
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


#: A ${VAR} reference in an MCP server config (D-17). Deliberately strict: the name must be a
#: valid identifier, so a literal that merely contains "${" cannot masquerade as a reference.
_VAR_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MissingSecretRef(RuntimeError):
    """A ${VAR} reference has no env var and no OS keyring entry (D-18 chains to KeyEntryModal)."""

    def __init__(self, var_name: str) -> None:
        self.var_name = var_name
        super().__init__(f"'${{{var_name}}}' is not set (checked the environment, then the OS keyring)")


def find_var_refs(*texts: str | None) -> set[str]:
    """Every distinct ${VAR} name referenced across ``texts``. Never raises."""
    names: set[str] = set()
    for text in texts:
        if text:
            names.update(_VAR_REF_RE.findall(text))
    return names


def expand_var_refs(text: str, overrides: dict[str, str] | None = None) -> str:
    """Substitute every ${VAR} in ``text``, env var first then the OS keyring.

    ``overrides`` carries values typed this session but not yet persisted (D-18): they win over
    both sources, mirroring the Phase 3 test-before-store flow. Raises :class:`MissingSecretRef`
    for the first name that resolves nowhere — the caller turns that into a masked key prompt.
    """
    if not text:
        return text
    overrides = overrides or {}

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in overrides:
            return overrides[name]
        # resolve_api_key(name, name) == "env var named `name`, else keyring account `name`" —
        # the exact precedence SEC-01 already mandates; do not reimplement it here.
        value = resolve_api_key(name, name)
        if value is None:
            raise MissingSecretRef(name)
        return value

    return _VAR_REF_RE.sub(_sub, text)


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
    "MissingSecretRef",
    "redact",
    "resolve_api_key",
    "keyring_available",
    "has_stored_key",
    "store_api_key",
    "clear_api_key",
    "find_var_refs",
    "expand_var_refs",
]
