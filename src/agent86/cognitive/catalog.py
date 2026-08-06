"""Live model catalogs, fetched from each provider's models endpoint (MODEL-01, D-01/D-02).

Nothing here is hardcoded: the endpoint is the single source of truth so the list cannot go stale
between releases. Three response shapes cover all six seeded providers:

* OpenAI-compatible (OpenAI, OpenRouter, Groq, and any custom ``base_url`` section)
      GET {base}/v1/models   Authorization: Bearer <key>
      -> {"data": [{"id": "gpt-4o", ...}, ...]}
* Anthropic                  GET https://api.anthropic.com/v1/models
      x-api-key: <key>, anthropic-version: 2023-06-01   (NOT Bearer -- a silent-401 trap)
      -> {"data": [{"id": "...", "display_name": "...", ...}], "has_more": ...}
* Ollama                     GET {base}/api/tags        (no auth)
      -> {"models": [{"name": "llama3.1:8b", ...}, ...]}

llama.cpp / LM Studio expose no equivalent listing in this codebase's convention, so they raise
:class:`CatalogUnavailable` and the caller falls back to free-text ``provider:model`` entry -- the
same fallback every fetch failure takes. Never a dead end (D-01).

Returned pairs are ``(ref, label)`` where ``ref`` is the bare model id; the caller prefixes
``provider:``.
"""

from __future__ import annotations

import httpx

from agent86.config import ProviderConfig

#: Every network call here is a UI-blocking catalog fetch behind a worker thread; keep it short.
_TIMEOUT_S = 10.0

_ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
_ANTHROPIC_VERSION = "2023-06-01"


class CatalogUnavailable(RuntimeError):
    """No model list could be obtained -- the caller must fall back to free-text entry."""


def _v1(base_url: str) -> str:
    """Tolerate a base_url given with or without the /v1 suffix (mirrors OpenAIProvider)."""
    base = base_url.rstrip("/")
    return base + ("" if base.endswith("/v1") else "/v1")


def _get_json(url: str, headers: dict[str, str]) -> dict:
    try:
        resp = httpx.get(url, headers=headers, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 - httpx errors, JSON errors, all fall back the same
        raise CatalogUnavailable(f"Could not fetch models from {url}: {exc}") from exc


# Verified against live GET https://openrouter.ai/api/v1/models on 2026-08-05: data[].id +
# data[].name match tests/fixtures/catalog/openrouter_models.json exactly, no fixture change
# needed. Groq's shape ({"object":"list","data":[{"id":...}]}) is UNVERIFIED live -- no
# GROQ_API_KEY was available in this execution environment and the docs page is client-rendered;
# see 03-04-SUMMARY.md "## Unverified" per 03-VALIDATION.md Manual-Only row 3.
def fetch_openai_compatible(base_url: str, api_key: str | None) -> list[tuple[str, str]]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    data = _get_json(_v1(base_url) + "/models", headers).get("data", [])
    return [(m["id"], m.get("name") or m["id"]) for m in data if isinstance(m, dict) and "id" in m]


def fetch_anthropic(api_key: str | None) -> list[tuple[str, str]]:
    if not api_key:
        raise CatalogUnavailable("Anthropic's model list needs an API key.")
    headers = {"x-api-key": api_key, "anthropic-version": _ANTHROPIC_VERSION}
    data = _get_json(_ANTHROPIC_MODELS_URL, headers).get("data", [])
    return [
        (m["id"], m.get("display_name") or m["id"])
        for m in data
        if isinstance(m, dict) and "id" in m
    ]


def fetch_ollama(base_url: str) -> list[tuple[str, str]]:
    models = _get_json(base_url.rstrip("/") + "/api/tags", {}).get("models", [])
    return [(m["name"], m["name"]) for m in models if isinstance(m, dict) and "name" in m]


def fetch_catalog(
    provider: str, pconf: ProviderConfig, api_key: str | None
) -> list[tuple[str, str]]:
    """Dispatch to the right fetcher for ``provider``, sorted by ref.

    Raises :class:`CatalogUnavailable` for any failure, and for providers that expose no listing.
    """
    if provider == "anthropic":
        entries = fetch_anthropic(api_key)
    elif provider == "ollama":
        entries = fetch_ollama(pconf.base_url or "http://localhost:11434")
    elif provider == "llamacpp":
        raise CatalogUnavailable(
            "llama.cpp / LM Studio expose no model list -- enter provider:model directly."
        )
    elif provider == "openai" or pconf.base_url:
        entries = fetch_openai_compatible(
            pconf.base_url or "https://api.openai.com/v1", api_key
        )
    else:
        raise CatalogUnavailable(
            f"Provider '{provider}' has no base_url configured, so its model list cannot be "
            "fetched -- enter provider:model directly."
        )
    if not entries:
        raise CatalogUnavailable(f"Provider '{provider}' returned an empty model list.")
    return sorted(entries, key=lambda pair: pair[0])


__all__ = [
    "CatalogUnavailable",
    "fetch_catalog",
    "fetch_openai_compatible",
    "fetch_anthropic",
    "fetch_ollama",
]
