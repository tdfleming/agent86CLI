# Phase 3: Secrets + Model/Provider Config - Research

**Researched:** 2026-07-21
**Domain:** OS keyring secret storage, tomlkit config write-back, provider model-catalog HTTP
endpoints, Textual modal/worker patterns
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Model catalog source**
- D-01: The model list is live-fetched from each provider's models endpoint at the moment the
  catalog is needed (OpenAI/OpenRouter/Groq `GET /v1/models`, Ollama `GET /api/tags`, Anthropic
  `GET /v1/models`). If the fetch fails, or the provider exposes no such endpoint (e.g.
  llamacpp), fall back to free-text `provider:model` entry — never a dead end.
- D-02: No hardcoded per-provider model catalog is shipped. The live endpoint is the single
  source of truth so the list cannot go stale between releases.
- D-03: Long catalogs (OpenRouter exposes 300+ models) are navigated with a type-to-filter list
  — a filter `Input` above an `OptionList` that narrows as the user types, deliberately mirroring
  the Phase 2 `/` palette interaction the user already knows.
- D-04: Fetched catalogs are cached in memory for the app session only. One fetch per launch,
  lazily on first use. No on-disk cache, no TTL, no invalidation logic.
- D-05: Providers with no resolvable key are still listed, visibly marked as having no key.
  Selecting one chains directly into the add-key flow, then fetches its catalog — so "add a
  provider" and "add a model" are one continuous path rather than two disjoint features.

**Secrets & key resolution**
- D-06: Introduce `resolve_api_key(provider_name, pconf)` with strict precedence: environment
  variable first (via `pconf.api_key_env`), then the OS keyring. Config never stores a plaintext
  secret. Both `anthropic_provider.py:40` and `openai_provider.py:44` currently call `os.getenv`
  directly — those are the two seams to replace.
- D-07: Keyring naming is service `"agent86"`, account = the config's provider name
  (`keyring.get_password("agent86", "anthropic")`). Keying on the provider name means a custom
  `[providers.myvllm]` block gets a keyring slot for free, and entries are readable in Windows
  Credential Manager / macOS Keychain.
- D-08: When neither env nor keyring yields a key: in the TUI, a masked key-entry modal appears
  at the point of need; in the plain loop and `run --json`, today's `ProviderError` is raised
  unchanged (message may additionally mention the keyring). The scripting contract stays
  non-interactive.
- D-09: keyring being absent (headless/CI) or its backend erroring falls through silently to
  env-only — no warning printed, per the milestone constraint. But keyring availability is shown
  explicitly in `/config` and in the secrets flow, so "unavailable" is distinguishable from "no
  key stored" when the user goes looking.
- D-10: The app supports storing (overwrite silently) and explicitly clearing a key, with a
  confirm on clear. No reveal/unmask action — a stored secret is never rendered in plaintext on
  screen.

**Connection test**
- D-11: The live test sends a tiny real completion (a ~1-token prompt, `max_tokens=1`) through
  the real `provider_for_ref` path — proving key, `base_url`, model name, and the actual
  completion code path together. Not a models-endpoint ping.
- D-12: The test runs on a worker thread (same pattern as the existing turn worker) with an
  inline spinner and status text in the modal, and a hard timeout of ~15 seconds producing a
  clear timeout failure. The app stays responsive throughout. No cancel button.
- D-13: A failed test blocks the default Save path and shows the provider error verbatim, but
  offers a clearly-labelled "Save anyway" override — required for endpoints that are legitimately
  unreachable at configuration time (a local llamacpp server that isn't running, a VPN-gated
  gateway).
- D-14: An entered key is held in memory during the test and only written to the keyring once the
  test passes (or when "Save anyway" is chosen). A typo'd key never becomes a persisted mystery.

**Modal flow & write-back**
- D-15: `/model` stays the fast switch-only picker Phase 2 shipped — now enriched with the live
  catalog (this fulfils Phase 2's deferred D-12). A new `/config model` opens the full manager:
  list providers/models, add, test, save, set role slots, clear key. The frequent action stays
  one keystroke; management is a separate, discoverable surface.
- D-16: Scope is chosen at save time, presented pre-selected to user (`~/.agent86/config.toml`)
  with project (`./.agent86/config.toml`) one arrow-key away. Explicit on every write — the user
  always knows which file changed.
- D-17: Before tomlkit commits, show the TOML diff — the exact lines being added/changed plus the
  target file path — with confirm/cancel. This is the user-visible proof that comments and
  surrounding config survive the write (success criterion 3).
- D-18: Switching a model applies immediately in-session via `Harness.set_model` exactly as
  `/model` does today (success criterion 4). Persisting it as `model.default` is a separate,
  explicit action in the manager — a quick experiment must never silently rewrite the default.

### Claude's Discretion
- D-19: How each provider's models-endpoint response is normalized into a common `(ref, label)`
  shape, and how the differing schemas (OpenAI `data[].id`, Ollama `models[].name`, Anthropic
  `data[].id`) are adapted. A small per-provider catalog function next to the existing provider
  modules is a reasonable shape.
- D-20: What metadata (if any) each catalog row displays beyond the ref — context window,
  pricing, and ownership are inconsistently available across endpoints. Show what's cheaply and
  uniformly available; don't build a metadata layer.
- D-21: Exact modal composition, widget ids, CSS, and how the type-to-filter list is wired,
  consistent with the Phase 1 layout and the `ModalScreen[T]` conventions in
  `tui/screens/approval.py` and `tui/screens/model_picker.py`.
- D-22: How `keyring` and `tomlkit` are added to `pyproject.toml` and lazy-imported so the `run`
  (one-shot) and `--plain` cold-start paths never import them (project constraint).
- D-23: Whether editing an existing provider's `base_url` / `num_ctx` is exposed in the manager
  this phase. Include it only if it falls out naturally from the add-provider flow; it is not a
  success criterion.

### Deferred Ideas (OUT OF SCOPE)
- MCP server list/add/remove/test UI — Phase 4 (MCP-01). The tomlkit write-back and
  connection-test patterns built here should be reusable there; design them with that in mind but
  do not build MCP surface in this phase.
- Plain-loop / `run --json` degradation guarantees and lazy-import hardening as a verified
  contract — Phase 5 (TUI-06). This phase must not break them, but proving them is Phase 5.
- On-disk catalog caching with a TTL — rejected for this phase (D-04); revisit only if per-launch
  fetch latency proves annoying.
- Recency/usage ranking of model choices — considered for long-list navigation, deferred because
  it requires persisting usage state.
- Revealing a stored key in plaintext — explicitly rejected (D-10), not merely deferred.
- Per-project scoped secrets (keyring entries keyed by project) — not in scope; keyring entries
  are global per provider (D-07).
- Theming / color schemes for the new modals — v2 (POL-01).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEC-01 | API keys can be stored in and read from the OS keyring; env vars still take precedence, config never contains a plaintext secret | `resolve_api_key` design (Code Examples), keyring API surface + error handling (Standard Stack, Common Pitfalls), the two provider seams documented verbatim below |
| MODEL-01 | List, switch, add, and test model providers/models from within the app; a live connection test confirms the model responds before saving | Provider models-endpoint schemas (Code Examples), connection-test-on-worker-thread pattern (Architecture Patterns), `/config model` manager modal composition (Architecture Patterns) |
| MODEL-02 | Config changes are written back to `~/.agent86/config.toml` non-destructively (comments preserved), defaulting to user scope with a project-scope option | tomlkit round-trip write-back design (Standard Stack, Code Examples), scope-selection + diff-preview pattern (Architecture Patterns) |
</phase_requirements>

## Summary

Phase 3 adds two new core-but-lazy dependencies — `keyring` (secret storage) and `tomlkit`
(comment-preserving TOML write-back) — and threads them through three existing seams: the two
`os.getenv` calls in `anthropic_provider.py` and `openai_provider.py`, the read-only `config.py`
loader, and the Phase 2 command registry / modal-screen conventions in `tui/`. Both new
dependencies have small, stable, well-documented APIs verified against Context7 (jaraco/keyring,
python-poetry/tomlkit) — there is no ambiguity in "how does the library work"; the real design
work is in the *seams*: keeping `ProviderError` messages byte-identical for the plain-loop
contract, making `resolve_api_key` a drop-in replacement for `os.getenv(key_env)` that never
raises on its own, and building a new write-back module (`config.py` currently only reads TOML
via stdlib `tomllib`) that reuses `load_config`'s merge/reload semantics rather than duplicating
them.

The five provider model-catalog endpoints split into two shapes: three OpenAI-compatible
`{"data": [{"id": ...}]}` lists (OpenAI, OpenRouter, Groq — Groq and OpenRouter both mirror the
OpenAI Chat Completions API surface, including `/v1/models`), one Anthropic-flavored
`{"data": [{"id": ..., "display_name": ...}]}` list with cursor pagination, and one
Ollama-flavored `{"models": [{"name": ..., "model": ...}]}` list. All five normalize cleanly to a
`(ref, label)` pair with a small per-provider function; `httpx` (already a core dependency) is
sufficient for every fetch — no new HTTP dependency is needed. llamacpp has no models endpoint by
convention in this codebase (`LlamaCppProvider` is a thin `OpenAIProvider` specialization with no
override), so its catalog step must skip straight to the D-01 free-text fallback.

The Textual layer has three fully worked, directly-reusable precedents already in the codebase:
`ApprovalModal` (`ModalScreen[bool]`, every dismissal path explicit), `ModelPickerModal` +
`model_choices()` (`ModalScreen[str | None]`, `OptionList` selection, "return `[]`/`None` rather
than hang" discipline), and `run_turn_worker` + `Agent86App._run_turn` (`@work(thread=True,
exclusive=True)` + `post_message` for off-UI-thread blocking work). The connection test (D-12)
should be built as a near-mechanical copy of the `@work(thread=True)` + `post_message` pattern
already proven for turns; nothing new needs to be invented there.

**Primary recommendation:** Introduce `resolve_api_key(provider_name, pconf) -> str | None` in a
new `agent86/secrets.py` module (lazy-imports `keyring` inside the function body, catches
`keyring.errors.KeyringError`/any exception broadly and returns `None` on failure — never raises),
call it from both `AnthropicProvider.__init__` and `OpenAIProvider.__init__` in place of the
existing `os.getenv` calls, add a `agent86/config_writer.py` module built on `tomlkit.parse` /
`.as_string()` diffing for the write-back (reusing `load_config`'s `_deep_merge`/reload pattern
for in-session refresh), and build the new TUI surface as three chained `ModalScreen[T]` screens
(`ProviderManagerModal` list -> `KeyEntryModal` masked input -> `ConnectionTestModal` worker +
spinner -> `SaveDiffModal` confirm) registered as a single `/config model` `CommandEntry`, wired
through `Agent86App._run_or_chain` exactly like `/model`/`/mode` today.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| keyring | >=25.0 | OS-native secret storage (Windows Credential Manager, macOS Keychain, SecretService/kwallet on Linux) | The de facto Python stdlib-adjacent secret-storage library (jaraco/keyring); zero-config backend auto-detection, no custom crypto (matches REQUIREMENTS.md "Out of Scope: hand-rolled encrypted secret storage") |
| tomlkit | >=0.13 | Comment/whitespace-preserving TOML parse + edit + serialize | Only mature Python TOML library that round-trips formatting; `tomllib` (stdlib, already used for reads) is read-only by design and cannot write |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | >=0.27 (already a core dep) | Fetch each provider's models-list endpoint and drive the connection-test completion | Already imported in `openai_provider.py`/`ollama_provider.py`; no new HTTP client needed for catalogs or the test |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| keyring | `keyrings.alt` (plaintext/encrypted-file fallback backends) | Explicitly out of scope per REQUIREMENTS.md ("Plaintext / hand-rolled encrypted secret storage" is listed as Out of Scope) — do not add as a dependency; if `keyring` has no usable backend, fall through to env-only per D-09, do not install a fallback backend |
| tomlkit | Hand-rolled regex-based TOML patching | Rejected — brittle, cannot handle inline tables/arrays/multi-line strings correctly; tomlkit exists precisely to solve this |
| tomlkit | `tomllib` + full rewrite (accept comment loss) | Rejected — success criterion 3 explicitly requires comment preservation |

**Installation:**
```bash
pip install "keyring>=25.0" "tomlkit>=0.13"
```
Add both to `pyproject.toml` `dependencies` (not an optional extra) but import them lazily inside
function/method bodies — same pattern already used for `textual` (core-but-lazy) per CLAUDE.md
constraints. `tests/tui/test_lazy_import.py` is the existing regression-guard shape to extend:
assert `'keyring' not in sys.modules` and `'tomlkit' not in sys.modules` after `import agent86.cli`.

**Version verification:** Verify current published versions before finalizing the plan:
```bash
npm view keyring version    # N/A — use: pip index versions keyring  (or check PyPI directly)
```
(This is a Python project — use `pip index versions keyring` / `pip index versions tomlkit`, or
check https://pypi.org/project/keyring/ and https://pypi.org/project/tomlkit/ directly, since `npm
view` does not apply here.) At research time, Context7 resolved both libraries against their
current `main` branches with no deprecation notices; treat exact patch versions as MEDIUM
confidence pending a live PyPI check at plan/implementation time.

## Architecture Patterns

### Recommended Project Structure
```
src/agent86/
├── secrets.py                    # NEW — resolve_api_key(), keyring set/clear/is_available
├── config_writer.py               # NEW — tomlkit round-trip write-back, scope selection, diff
├── cognitive/
│   ├── anthropic_provider.py      # MODIFIED — os.getenv -> resolve_api_key seam
│   ├── openai_provider.py         # MODIFIED — os.getenv -> resolve_api_key seam
│   └── catalog.py                 # NEW (D-19) — per-provider models-endpoint fetch + normalize
├── config.py                      # UNCHANGED read path; config_writer.py is additive, not a rewrite
└── tui/
    ├── commands.py                 # MODIFIED — new `/config model` CommandEntry
    └── screens/
        ├── model_picker.py         # MODIFIED — enrich choices with live catalog (D-15)
        ├── provider_manager.py      # NEW — list/add/test/save modal chain (D-21)
        ├── key_entry.py             # NEW — masked Input modal (D-08/D-10)
        ├── connection_test.py       # NEW — worker-thread test w/ spinner (D-11/D-12/D-13)
        └── save_diff.py             # NEW — TOML diff + scope confirm (D-16/D-17)
```

### Pattern 1: `resolve_api_key` — env-first, keyring-fallback, never-raising
**What:** A single function every keyed provider constructor calls in place of `os.getenv`.
**When to use:** Any provider whose `ProviderConfig.api_key_env` is set.
**Example:**
```python
# agent86/secrets.py — new module, mirrors the lazy-import discipline already used for
# textual (see agent86/tui/app.py docstring, "Textual is only ever imported by this module").
from __future__ import annotations

import os

SERVICE_NAME = "agent86"


def resolve_api_key(provider_name: str, api_key_env: str | None) -> str | None:
    """Env var first, then OS keyring. Never raises — returns None if nothing is found
    or the keyring backend is unusable (headless/CI degrades silently per D-09)."""
    if api_key_env:
        if val := os.getenv(api_key_env):
            return val
    try:
        import keyring
        import keyring.errors
    except ImportError:
        return None
    try:
        return keyring.get_password(SERVICE_NAME, provider_name)
    except keyring.errors.KeyringError:
        return None


def keyring_available() -> bool:
    """For the D-09 '/config' visibility requirement — distinguishes 'unavailable' from
    'no key stored'. Calling get_keyring() forces backend initialization/detection."""
    try:
        import keyring
        import keyring.errors
        backend = keyring.get_keyring()
        # keyring.backends.fail.Keyring is the sentinel installed when no real backend
        # is usable (headless Linux with no SecretService/kwallet, etc.)
        return backend.__class__.__module__ != "keyring.backends.fail"
    except Exception:
        return False
```
Source: pattern synthesized from Context7 `/jaraco/keyring` (`get_password`,
`keyring.errors.NoKeyringError`/`KeyringError`, `get_keyring()`) plus D-06/D-09 requirements.
`anthropic_provider.py:40-45` and `openai_provider.py:44-47` become:
```python
# anthropic_provider.py — replaces `key_env = ...; api_key = os.getenv(key_env)`
from agent86.secrets import resolve_api_key
key_env = config.api_key_env or "ANTHROPIC_API_KEY"
api_key = resolve_api_key("anthropic", key_env)
if not api_key:
    raise ProviderError(
        f"No Anthropic API key found. Set the {key_env} environment variable "
        "or store one in the keyring via /config model."
    )
```
```python
# openai_provider.py — replaces `self._api_key = os.getenv(config.api_key_env) if ... else None`
self._api_key = resolve_api_key(self.name, config.api_key_env) if config.api_key_env else None
if require_key and not self._api_key:
    env = config.api_key_env or "OPENAI_API_KEY"
    raise ProviderError(f"No API key found. Set the {env} environment variable "
                         "or store one in the keyring via /config model.")
```
Note `self.name` for `OpenAIProvider` is `"openai"` for the built-in provider but the custom
`[providers.myvllm]` block reaches `OpenAIProvider` too (base.py fallback) — the account name
passed to `resolve_api_key` must be the *config section name* (`ref.provider`), not the class
`name` attribute, so a custom provider's keyring slot is independent. `provider_for_ref` already
has `ref.provider` in scope; threading it through as an explicit constructor argument (rather than
relying on `self.name`) is the safer shape — flag this as an Open Question below for the planner.

**require_key interaction (critical, D-06 canonical ref):** `provider_for_ref`'s existing rule —
`require_key=bool(pconf.api_key_env)` — must NOT change. A keyless local endpoint (Ollama,
llama.cpp with no `api_key_env` configured) has `api_key_env=None`, so `resolve_api_key` returns
`None` immediately from the `if api_key_env:` guard without ever touching the keyring, and
`require_key=False` means the `None` is accepted. This preserves today's behavior exactly.

### Pattern 2: tomlkit write-back — parse once, mutate in place, diff before write
**What:** Load the target scope file (or start a fresh document if absent), get-or-create nested
tables with `setdefault`, set leaf values, and generate a text diff for the D-17 confirm screen.
**When to use:** Every save action in the model manager (add provider, set model role, persist
default).
**Example:**
```python
# agent86/config_writer.py
from __future__ import annotations

from pathlib import Path


def load_document(path: Path):
    import tomlkit
    if not path.exists():
        return tomlkit.document()
    return tomlkit.parse(path.read_text(encoding="utf-8"))


def set_provider_field(doc, provider: str, field: str, value: str) -> None:
    import tomlkit
    providers = doc.setdefault("providers", tomlkit.table())
    section = providers.setdefault(provider, tomlkit.table())
    section[field] = value


def render_diff(before_text: str, after_text: str, path: Path) -> str:
    import difflib
    return "\n".join(
        difflib.unified_diff(
            before_text.splitlines(), after_text.splitlines(),
            fromfile=str(path), tofile=str(path), lineterm="",
        )
    )


def write_atomic(path: Path, text: str) -> None:
    """Write-then-rename so a crash mid-write never corrupts the existing file (works on
    Windows because os.replace is atomic-on-same-volume there too, unlike os.rename)."""
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".toml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp_name, path)  # atomic on POSIX; atomic-if-same-volume on Windows (NTFS)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
```
Sources: `tomlkit.parse`/`.as_string()`/`table()`/`setdefault()` verified via Context7
`/python-poetry/tomlkit` (Modify TOML Document, AbstractTable.setdefault, Preserve Formatting).
`os.replace` atomic-rename-on-Windows is a well-established Python stdlib pattern (same-volume
requirement — using `tempfile.mkstemp(dir=path.parent, ...)` guarantees same volume).

**Reload-after-write:** After a successful save, call `load_config()` again (or manually
`_deep_merge` the new section into the in-memory `Config`) so `/config`/`/models` reflect the
write without an app restart — `config.py`'s existing `load_config`/`_deep_merge` functions are
reusable as-is; do not duplicate merge logic in `config_writer.py`.

### Pattern 3: Provider models-catalog fetch + normalize (D-19)
**What:** One small function per provider family, returning `list[tuple[str, str]]` = `(ref,
label)` pairs, where `ref` is the bare model id/name (the caller prefixes `provider:`).
**When to use:** Called lazily on first catalog need per D-04 (in-memory session cache — a plain
module-level or app-level `dict[str, list[tuple[str,str]]]` keyed by provider name is sufficient;
no on-disk cache).
**Example:**
```python
# agent86/cognitive/catalog.py (new; D-19 discretion)
from __future__ import annotations
import httpx

def fetch_openai_compatible(base_url: str, api_key: str | None) -> list[tuple[str, str]]:
    """OpenAI, OpenRouter, Groq all expose GET {base}/models -> {"data": [{"id": ...}, ...]}."""
    url = base_url.rstrip("/") + ("" if base_url.rstrip("/").endswith("/v1") else "/v1") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = httpx.get(url, headers=headers, timeout=10.0)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return [(m["id"], m["id"]) for m in data if "id" in m]

def fetch_anthropic(api_key: str) -> list[tuple[str, str]]:
    """GET https://api.anthropic.com/v1/models -> {"data": [{"id","display_name",...}]}.
    Requires x-api-key and anthropic-version headers (not Bearer auth)."""
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    resp = httpx.get("https://api.anthropic.com/v1/models", headers=headers, timeout=10.0)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return [(m["id"], m.get("display_name", m["id"])) for m in data]

def fetch_ollama(base_url: str) -> list[tuple[str, str]]:
    """GET {base}/api/tags -> {"models": [{"name","model",...}]}."""
    resp = httpx.get(base_url.rstrip("/") + "/api/tags", timeout=10.0)
    resp.raise_for_status()
    models = resp.json().get("models", [])
    return [(m["name"], m["name"]) for m in models]

# llamacpp: no catalog endpoint by convention in this codebase (LlamaCppProvider has no
# override) — the manager must skip catalog fetch and go straight to free-text entry (D-01).
```
Response-shape sources (WebSearch, cross-checked against Anthropic's and Ollama's own docs
pages returned in results — MEDIUM confidence, not fetched via Context7 since neither ships an
OpenAPI spec there):
- Anthropic `GET /v1/models`: `{"data":[{"id","display_name","created_at","type"}], "has_more",
  "first_id","last_id"}` — auth via `x-api-key` + `anthropic-version` header, NOT `Authorization:
  Bearer` (differs from every other provider here — a real pitfall, see below).
- Ollama `GET /api/tags`: `{"models":[{"name","model","modified_at","size","digest","details":
  {...}}]}` — no auth.
- OpenAI `GET /v1/models`: `{"object":"list","data":[{"id","object":"model","created",
  "owned_by"}]}` — `Authorization: Bearer <key>`. (HIGH confidence — stable, unchanged API
  surface, this codebase's own `AnthropicProvider`/`OpenAIProvider` already encode Bearer-auth
  convention for OpenAI-compatible endpoints.)
- Groq mirrors the OpenAI Chat Completions API including `/v1/models`, same `data[].id` shape,
  `Authorization: Bearer`. (MEDIUM confidence — Groq documents itself as OpenAI-compatible;
  verify at implementation time with a live call if possible.)
- OpenRouter `GET /api/v1/models`: `{"data":[{"id","name","pricing":{"prompt","completion",...},
  "context_length",...}]}` — endpoint is publicly listable without auth, but sending
  `Authorization: Bearer <key>` is harmless and consistent with the other three. (MEDIUM
  confidence.)

### Pattern 4: Chained modal flow through `_run_or_chain` (mirrors D-15 continuous UX)
**What:** `/config model` is a new `CommandEntry` with a new `needs_choice` value (e.g.
`"config_model"`), and `_run_or_chain` pushes the first modal in the chain; each modal's
`dismiss` callback decides whether to push the next modal or stop.
**When to use:** The entire add-provider-key-test-save flow described in CONTEXT.md's Specific
Ideas ("see a provider with no key -> enter key masked -> tests -> catalog appears -> pick model
-> TOML diff -> save").
**Example (chaining shape, following `_on_mode_picked`/`_on_model_picked` in `app.py`):**
```python
# tui/app.py additions — same shape as existing _run_or_chain branches
elif entry.needs_choice == "config_model":
    self.push_screen(ProviderManagerModal(self.repl.cfg), self._on_provider_picked)

def _on_provider_picked(self, choice) -> None:
    if choice is None:
        return
    if choice.needs_key:
        self.push_screen(KeyEntryModal(choice.provider), self._on_key_entered)
    else:
        self._fetch_catalog_and_continue(choice.provider)

def _on_key_entered(self, key) -> None:
    if key is None:
        return
    self.push_screen(ConnectionTestModal(self._pending_provider, key), self._on_test_done)
# ... etc, each step an explicit dismiss -> next-push, never a hang (ModalScreen[T] discipline)
```
Every screen in the chain MUST follow the `ApprovalModal`/`ModelPickerModal` convention: Escape
always dismisses with an explicit falsy/None sentinel, never leaves the chain hanging.

### Pattern 5: Connection test on a worker thread (D-11/D-12)
**What:** Reuse the exact `@work(thread=True, exclusive=True)` + `post_message` shape from
`Agent86App._run_turn`/`run_turn_worker`, but for a single non-streaming `provider.complete()`
call with `max_tokens=1`, guarded by a manual timeout.
**Example:**
```python
# connection_test.py — new Message + worker, mirrors tui/messages.py's TurnDone/TurnError shape
from textual import work
import threading

class ConnectionTestModal(ModalScreen[bool]):
    ...
    def on_mount(self) -> None:
        self._run_test()

    @work(thread=True, exclusive=True)
    def _run_test(self) -> None:
        from agent86.cognitive.base import provider_for_ref, ProviderError
        from agent86.types import ModelRef, CompletionRequest, Message, Role
        try:
            provider = provider_for_ref(ModelRef(provider=self._provider, model=self._model), self._cfg)
            req = CompletionRequest(
                model=self._model,
                messages=[Message(role=Role.USER, content="hi")],
                max_tokens=1,
            )
            result_holder: dict = {}
            done = threading.Event()

            def _call():
                try:
                    result_holder["completion"] = provider.complete(req)
                except Exception as exc:  # noqa: BLE001 — surface verbatim per D-13
                    result_holder["error"] = str(exc)
                finally:
                    done.set()

            t = threading.Thread(target=_call, daemon=True)
            t.start()
            if not done.wait(timeout=15.0):
                self.app.call_from_thread(self._post_result, False, "Timed out after 15s")
                return
            if "error" in result_holder:
                self.app.call_from_thread(self._post_result, False, result_holder["error"])
            else:
                self.app.call_from_thread(self._post_result, True, None)
        except (ProviderError, ValueError) as exc:
            self.app.call_from_thread(self._post_result, False, str(exc))
```
This nested-thread-with-manual-timeout shape is necessary because `provider.complete()` (via
`httpx.stream`) has no built-in per-call timeout override exposed at this call site for some
providers (Anthropic SDK does support `timeout=`; the OpenAI-compatible path uses
`httpx.stream(..., timeout=None)` explicitly in `openai_provider.py:125` — passing a timeout
through would be cleaner than the nested-thread wrapper if the provider API is extended to accept
one). **Open Question:** should `ProviderError`/timeout plumbing instead go through an optional
`timeout` kwarg on `stream()`/`complete()` rather than a wrapper thread? Flagged below for the
planner — the wrapper-thread approach works without touching provider signatures and keeps this
phase's scope to config/secrets rather than the cognitive tier, but it's a secondary layer of
threading worth a second look.

### Anti-Patterns to Avoid
- **Calling `keyring.get_password` unconditionally at import time or module load** — must be
  inside `resolve_api_key`'s function body only; importing `keyring` eagerly anywhere reachable
  from `agent86.cli` breaks the lazy-import cold-start guarantee (see `test_lazy_import.py`).
- **Writing the whole `Config.model_dump()` back to TOML** — this would erase user comments and
  any manually-added out-of-schema keys. Only mutate the specific keys the user changed
  (`set_provider_field`-style targeted writes), never round-trip through the pydantic model.
- **Storing the freshly-entered key in `Config`/`ProviderConfig` before the test passes** — D-14
  requires the key to live only in local modal state (a plain Python variable) until the test
  passes or "Save anyway" is chosen.
- **Using `Authorization: Bearer` for the Anthropic models-catalog fetch** — Anthropic's API uses
  `x-api-key` + `anthropic-version`, not Bearer; reusing the OpenAI-compatible fetch helper for
  Anthropic will silently 401.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Secure secret storage | A custom encrypted file / obfuscation scheme | `keyring` | REQUIREMENTS.md explicitly rules out hand-rolled encrypted storage; OS keychains handle key-wrapping, ACLs, and user-session binding correctly, which a custom scheme would get wrong |
| TOML comment-preserving edits | Regex-based line patching of the config file | `tomlkit` | TOML has non-trivial syntax (inline tables, multi-line strings, dotted keys); tomlkit's CST-based model handles all of it and is the standard tool for exactly this problem |
| Diffing before a config write | A hand-rolled line comparator | `difflib.unified_diff` (stdlib) | Already solves this correctly; no reason to reinvent |
| Atomic file replace | Direct `path.write_text()` | `tempfile.mkstemp` + `os.replace` | Direct writes can leave a truncated file if the process dies mid-write; `os.replace` is atomic on both POSIX and same-volume Windows (NTFS) |

**Key insight:** Every "hand-roll" temptation in this phase (secrets, TOML diffing, atomic
writes) already has a correct, standard, small-surface-area library or stdlib tool. The actual
engineering work is entirely in the *seams* — where `resolve_api_key` plugs into providers, where
`config_writer` plugs into `load_config`'s reload path, and how the TUI modal chain hands state
from one screen to the next.

## Common Pitfalls

### Pitfall 1: Breaking the plain-loop `ProviderError` message contract
**What goes wrong:** Changing `os.getenv(key_env)` to `resolve_api_key(...)` and forgetting that
the *exact wording* of the raised `ProviderError` may be asserted by existing tests or scripts
consuming `run --json` error output.
**Why it happens:** It's tempting to rewrite the error message while touching the line.
**How to avoid:** Keep the existing message text and only *append* a clause about the keyring
(per D-08: "message may additionally mention the keyring"), never replace it. Grep
`tests/` for the literal current message strings before changing them.
**Warning signs:** Any test asserting `str(exc) == "No Anthropic API key found..."` or similar
exact-match assertions.

### Pitfall 2: keyring backend hangs or prompts interactively in a test/CI environment
**What goes wrong:** On some Linux CI runners, `keyring`'s SecretService backend can attempt to
launch a D-Bus prompt or block waiting for a session keyring that doesn't exist, rather than
failing fast.
**Why it happens:** `keyring.get_keyring()` auto-detects backends at runtime; a partially-present
D-Bus environment can look "available" but hang on first real call.
**How to avoid:** All tests must monkeypatch `keyring.get_password`/`set_password`/
`delete_password` (or monkeypatch `agent86.secrets`'s internal calls) rather than exercising a
real backend — never let a test suite touch the actual OS keychain. `resolve_api_key`'s broad
`except` around the keyring call (Pattern 1) also protects production headless runs, but tests
should not rely on that as their only safety net (a hang is not caught by exception handling).
**Warning signs:** A test suite that takes unusually long or hangs specifically in CI but not
locally.

### Pitfall 3: Windows Credential Manager has a payload size limit
**What goes wrong:** `WinVaultKeyring` (the default Windows backend) enforces a maximum total
credential blob size (historically documented around 2560 bytes for the combined
target/username/credential in some Windows Credential Manager versions); a very long API key or
combined service/account string could fail to store.
**Why it happens:** Windows Credential Manager itself imposes this limit, not `keyring`.
**How to avoid:** Not a practical concern for typical API keys (tens to low hundreds of chars),
but the `set_password`/`store` path in the manager should catch and surface any `PasswordSetError`
from `keyring.errors` cleanly rather than letting it propagate as an unhandled exception in the
modal. Since this project's primary dev/test platform is Windows 11, exercise a manual
store/retrieve/clear cycle for at least one real key during phase validation.
**Warning signs:** `keyring.errors.PasswordSetError` raised only on Windows, not other platforms.

### Pitfall 4: Anthropic's models endpoint uses different auth than every other provider here
**What goes wrong:** Reusing the OpenAI-compatible `fetch_openai_compatible` helper (Bearer auth)
for Anthropic's catalog fetch silently returns a 401.
**Why it happens:** Anthropic's REST API uses `x-api-key` + `anthropic-version` headers, not
`Authorization: Bearer`, unlike every OpenAI-compatible provider in this codebase.
**How to avoid:** Keep `fetch_anthropic` as its own function (Pattern 3) with the correct headers;
do not generalize it into the OpenAI-compatible helper.
**Warning signs:** A 401 from `api.anthropic.com/v1/models` when the same key works fine for
completions via the `anthropic` SDK (which sets these headers internally).

### Pitfall 5: `require_key` regression for keyless local endpoints
**What goes wrong:** If `resolve_api_key` is wired in incorrectly (e.g. called unconditionally
even when `api_key_env` is `None`), it could attempt a keyring lookup keyed on the provider name
for Ollama/llamacpp, and if a stale/irrelevant keyring entry happens to exist under that name, a
local keyless endpoint could start sending an unwanted `Authorization` header.
**Why it happens:** Easy to lose the `if api_key_env:` short-circuit while refactoring.
**How to avoid:** `resolve_api_key` (Pattern 1) explicitly returns `None` immediately when
`api_key_env` is falsy, never reaching the keyring branch — preserve this order strictly. Add a
regression test: Ollama/llamacpp provider construction with a keyring entry present under
`"ollama"`/`"llamacpp"` must NOT pick it up when `api_key_env` is unset.
**Warning signs:** A previously-keyless local test starts sending an `Authorization` header.

### Pitfall 6: tomlkit `setdefault` on a table that already exists as a plain dict from a prior
non-tomlkit write
**What goes wrong:** If any other code path ever wrote raw text to `config.toml` without going
through tomlkit (unlikely but worth guarding), `tomlkit.parse` might encounter a malformed
document. `tomlkit.parse` raises `tomlkit.exceptions.ParseError` on invalid TOML — the write path
must handle this the same way `_read_toml` already handles `tomllib.TOMLDecodeError` (raises with
a clear "Malformed config at {path}" message) rather than crashing the modal.
**Why it happens:** Any hand-edit of the file (by the user, in an editor) between app launches.
**How to avoid:** Wrap `load_document` in a try/except that surfaces a clear, catchable error the
modal can show instead of a raw traceback.
**Warning signs:** App crash (not a graceful error modal) when config.toml has a syntax error.

## Runtime State Inventory

Not applicable — this is new-feature work (add keyring + tomlkit write-back), not a
rename/refactor/migration phase. No existing stored data, live service config, OS-registered
state, or build artifacts reference strings this phase changes. The one item worth flagging
explicitly:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Secrets/env vars | None yet — this phase CREATES the first `keyring` entries the app will ever write (service `"agent86"`, account = provider name). No prior entries exist to migrate. | None — greenfield for this phase; D-07 naming convention (service="agent86", account=provider name) must be followed consistently by all future phases (e.g. Phase 4 MCP auth, if it ever needs secrets) to avoid orphaned entries later. |
| Build artifacts | `pyproject.toml` dependency list — `keyring`/`tomlkit` not yet present | Add to `dependencies` (not extras) per D-22, matching the `textual` core-but-lazy precedent |

## Code Examples

Verified patterns from official sources and existing codebase precedent:

### keyring: store, retrieve, delete, detect no-backend
```python
# Source: Context7 /jaraco/keyring (01-core-api.md, 06-errors.md)
import keyring
from keyring.errors import NoKeyringError, PasswordDeleteError

keyring.set_password("agent86", "anthropic", "sk-ant-...")   # store (silently overwrites)
pw = keyring.get_password("agent86", "anthropic")             # None if absent, never raises
try:
    keyring.delete_password("agent86", "anthropic")
except PasswordDeleteError:
    pass  # nothing was stored — treat as already-cleared

try:
    pw = keyring.get_password("agent86", "anthropic")
except NoKeyringError:
    pw = None  # headless/CI: no backend installed at all
```

### tomlkit: parse existing file, add nested table, diff, write
```python
# Source: Context7 /python-poetry/tomlkit (quickstart.md, table-classes.md, INDEX.md)
import tomlkit
from pathlib import Path

path = Path.home() / ".agent86" / "config.toml"
before_text = path.read_text(encoding="utf-8") if path.exists() else ""
doc = tomlkit.parse(before_text) if before_text else tomlkit.document()

providers = doc.setdefault("providers", tomlkit.table())
groq = providers.setdefault("groq", tomlkit.table())
groq["api_key_env"] = "GROQ_API_KEY"  # secrets never written here — env var name only

after_text = doc.as_string()
# diff before_text vs after_text with difflib.unified_diff for the D-17 confirm screen
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(after_text, encoding="utf-8")  # or atomic write per Pattern 2
```

### Textual worker + post_message (existing codebase precedent, directly reusable shape)
```python
# Source: src/agent86/tui/app.py lines 216-219, src/agent86/tui/turn_bridge.py
@work(thread=True, exclusive=True)
def _run_turn(self, line: str) -> None:
    run_turn_worker(self.repl.harness, line, self.repl.state, self.post_message)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `config.py` reads TOML via stdlib `tomllib` (read-only) | Add `tomlkit`-based write path alongside the unchanged `tomllib` read path | This phase | `_read_toml`/`load_config`/`_deep_merge` stay exactly as-is; `config_writer.py` is purely additive, reducing regression risk |
| API keys read only from env vars (`os.getenv`) | `resolve_api_key`: env-first, then OS keyring | This phase | Existing env-var-only setups keep working unchanged (env always wins); keyring is additive |

**Deprecated/outdated:** Nothing in this domain is deprecated — both libraries are current and
actively maintained (verified via Context7 resolution against their `main`/current docs branches
with no deprecation notices surfaced).

## Open Questions

1. **Should the connection-test timeout be implemented via provider-level `timeout=` plumbing
   instead of a wrapper thread?**
   - What we know: `AnthropicProvider` uses the `anthropic` SDK's own client (which supports a
     `timeout=` kwarg at the client or per-call level); `OpenAIProvider`/`OllamaProvider` call
     `httpx.stream(..., timeout=None)` explicitly today.
   - What's unclear: Whether adding an optional `timeout` parameter to `ModelProvider.stream()`/
     `complete()` (touching the cognitive tier, nominally out of this phase's stated boundary —
     "This phase does not touch the harness or cognitive loop beyond the api-key seam and
     `Harness.set_model`") is preferable to the nested-thread-with-`Event.wait(timeout=)` wrapper
     shown in Pattern 5, which keeps the change entirely inside the new TUI/test module.
   - Recommendation: Default to the wrapper-thread approach (Pattern 5) to respect the stated
     phase boundary; note it as a known minor inefficiency (an extra thread inside a worker
     thread) rather than a correctness risk. Revisit provider-level timeout plumbing only if a
     future phase needs it broadly.

2. **Exact account-name convention when a custom `[providers.NAME]` block reuses the built-in
   `OpenAIProvider` class (e.g. `[providers.myvllm]` via the base.py fallback).**
   - What we know: D-07 says "account = the config's provider name" — i.e. the TOML section key
     (`ref.provider`), not the provider class's `.name` attribute (`OpenAIProvider.name ==
     "openai"` regardless of which config section constructed it).
   - What's unclear: `OpenAIProvider.__init__` doesn't currently receive `ref.provider` — only
     `model` and `config` (a `ProviderConfig`, which has no name field). Passing the provider
     name through requires either adding a constructor parameter or moving the `resolve_api_key`
     call up into `provider_for_ref` (in `base.py`) rather than inside each provider's
     `__init__`.
   - Recommendation: Resolve the key in `provider_for_ref` (which already has `ref.provider` in
     scope) and pass the resolved `api_key: str | None` into each provider's constructor,
     replacing the current `os.getenv`-inside-`__init__` pattern entirely. This is a slightly
     larger refactor than a one-line swap but is the only way to honor D-07's "account = config
     provider name" for custom OpenAI-compatible providers; flag this design choice explicitly
     for the planner since it changes provider constructor signatures across four files
     (`base.py`, `anthropic_provider.py`, `openai_provider.py`, `llamacpp_provider.py`).

3. **Where does the in-memory session catalog cache (D-04) live?**
   - What we know: "cached in memory for the app session only... lazily on first use." No
     on-disk cache.
   - What's unclear: Whether this cache belongs on `Agent86App` (a plain instance dict) or on
     `_Repl`/`Harness` (making it theoretically reachable from the plain loop too, though the
     plain loop has no UI to display it).
   - Recommendation: Keep it on `Agent86App` (or a small dedicated `CatalogCache` object it
     owns) — the plain loop never needs a model catalog, so there's no reason to add TUI-only
     state to `_Repl`/`Harness`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.2+ with pytest-asyncio (auto mode) — `[tool.pytest.ini_options]` in `pyproject.toml` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `testpaths = ["tests"]`) |
| Quick run command | `pytest tests/unit/test_config.py tests/tui -q` |
| Full suite command | `pytest -q` (currently 196 tests green per STATE.md) |

Textual modals are tested headlessly via `App.run_test()` / `Pilot` (see `tests/tui/test_pickers.py`
for the exact `_PickerHost` pattern — a minimal host `App` that pushes one screen and records its
dismissed value; `tests/tui/test_app.py` for a full-app Pilot test with a fake `ModelProvider`).
The keyring backend must be monkeypatched, never exercised for real (Pitfall 2); the "live"
provider models-endpoint fetch and the connection-test completion call must be exercised against
a fake/monkeypatched `httpx`/provider, never a real network call, mirroring `tests/support.py`'s
existing `make_text_provider`/`ToolThenTextProvider` fakes used in `test_app.py`.

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEC-01 | `resolve_api_key` returns env value when set, ignoring keyring | unit | `pytest tests/unit/test_secrets.py::test_env_wins_over_keyring -x` | ❌ Wave 0 |
| SEC-01 | `resolve_api_key` falls back to keyring when env unset (keyring monkeypatched) | unit | `pytest tests/unit/test_secrets.py::test_keyring_fallback -x` | ❌ Wave 0 |
| SEC-01 | `resolve_api_key` returns `None` silently when keyring raises/absent, no exception propagates | unit | `pytest tests/unit/test_secrets.py::test_keyring_unavailable_silent -x` | ❌ Wave 0 |
| SEC-01 | Config never serializes a plaintext secret (`model_dump_json` / written TOML contains no key value, only `api_key_env` names) | unit | `pytest tests/unit/test_config_writer.py::test_no_plaintext_secret_in_output -x` | ❌ Wave 0 |
| SEC-01 | `AnthropicProvider`/`OpenAIProvider` still raise the (extended) `ProviderError` when no key resolves anywhere, message preserves original wording | unit | `pytest tests/unit/test_providers_key_seam.py::test_provider_error_message_preserved -x` | ❌ Wave 0 |
| SEC-01 | Keyless local providers (Ollama/llamacpp with `api_key_env=None`) remain unaffected even if a stray keyring entry exists under that provider name | unit | `pytest tests/unit/test_providers_key_seam.py::test_keyless_provider_ignores_keyring -x` | ❌ Wave 0 |
| MODEL-01 | Each provider's catalog fetch function normalizes a fixture response into `(ref, label)` pairs (OpenAI/OpenRouter/Groq/Anthropic/Ollama fixtures) | unit | `pytest tests/unit/test_catalog.py -x` | ❌ Wave 0 |
| MODEL-01 | Catalog fetch failure (network error / non-200) falls back to free-text entry path, never a dead end | unit | `pytest tests/unit/test_catalog.py::test_fetch_failure_falls_back -x` | ❌ Wave 0 |
| MODEL-01 | `/config model` manager modal: list -> select provider with no key -> key-entry modal chains automatically | integration (Pilot) | `pytest tests/tui/test_provider_manager.py::test_no_key_provider_chains_to_key_entry -x` | ❌ Wave 0 |
| MODEL-01 | Connection test success/failure/timeout all resolve without hanging (mirrors `ApprovalModal` discipline) | integration (Pilot) | `pytest tests/tui/test_connection_test.py -x` | ❌ Wave 0 |
| MODEL-01 | Failed test blocks default Save but "Save anyway" override works | integration (Pilot) | `pytest tests/tui/test_provider_manager.py::test_save_anyway_override -x` | ❌ Wave 0 |
| MODEL-01 | Type-to-filter narrows a long catalog (OptionList + Input wiring) | integration (Pilot) | `pytest tests/tui/test_provider_manager.py::test_catalog_filter_narrows -x` | ❌ Wave 0 |
| MODEL-02 | tomlkit write preserves existing comments/formatting on a real fixture file with hand-written comments | unit | `pytest tests/unit/test_config_writer.py::test_comments_preserved_roundtrip -x` | ❌ Wave 0 |
| MODEL-02 | Write targets user scope by default, project scope when explicitly chosen | unit | `pytest tests/unit/test_config_writer.py::test_scope_selection -x` | ❌ Wave 0 |
| MODEL-02 | Diff preview shown before write matches the actual before/after text | integration (Pilot) | `pytest tests/tui/test_save_diff.py::test_diff_matches_actual_write -x` | ❌ Wave 0 |
| MODEL-02 (SC4) | Switching model via manager applies immediately via `Harness.set_model`; persisting `model.default` is a separate explicit action | integration (Pilot) | `pytest tests/tui/test_provider_manager.py::test_switch_is_immediate_persist_is_separate -x` | ❌ Wave 0 |
| Packaging (D-22) | `agent86.cli` import still does not import `keyring`/`tomlkit` (extends existing lazy-import guard) | unit | `pytest tests/tui/test_lazy_import.py -x` | ✅ extend existing file |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_secrets.py tests/unit/test_config_writer.py tests/unit/test_catalog.py tests/unit/test_providers_key_seam.py -q` for backend-only tasks;
  `pytest tests/tui -q` for TUI-touching tasks (fast — headless Pilot, no real I/O).
- **Per wave merge:** `pytest -q` (full suite, currently 196 tests, expected to grow by
  ~15-20 new tests this phase).
- **Phase gate:** Full suite green, plus a manual Windows verification pass (per this project's
  primary-platform constraint) of one real store/retrieve/clear cycle against Windows Credential
  Manager — Pitfall 3's size-limit concern and any Windows-specific `WinVaultKeyring` behavior
  cannot be fully proven by monkeypatched unit tests alone.

### Wave 0 Gaps
- [ ] `tests/unit/test_secrets.py` — new file; covers SEC-01 resolve_api_key precedence + silent
      degradation. Needs a `monkeypatch`-based fake for `keyring.get_password`/`set_password`/
      `delete_password`/`get_keyring` (do not import the real `keyring` package's backends in
      tests — patch at the `agent86.secrets` module boundary).
- [ ] `tests/unit/test_config_writer.py` — new file; covers MODEL-02 tomlkit round-trip,
      comment preservation, scope selection, no-plaintext-secret assertion. Needs a fixture TOML
      file with hand-written comments (e.g. `tests/fixtures/config_with_comments.toml`) to prove
      round-trip fidelity concretely rather than asserting on tomlkit's internals.
- [ ] `tests/unit/test_catalog.py` — new file; covers MODEL-01 per-provider response
      normalization. Needs fixture JSON payloads for all five endpoint shapes (OpenAI, Groq,
      OpenRouter, Anthropic, Ollama) captured from the schemas documented in Code Examples above
      — mock `httpx.get`/`httpx.Client` rather than hitting real endpoints.
- [ ] `tests/unit/test_providers_key_seam.py` — new file (or extend existing provider tests if
      `tests/unit/test_cognitive*.py`/similar already exist — verify at Wave 0 time) — covers the
      `require_key`/keyless-endpoint regression (Pitfall 5) and the preserved-`ProviderError`-
      message assertion (Pitfall 1).
- [ ] `tests/tui/test_provider_manager.py`, `tests/tui/test_connection_test.py`,
      `tests/tui/test_save_diff.py` — new files; follow the `_PickerHost`/`run_test()`/`Pilot`
      shape already established in `tests/tui/test_pickers.py` and `tests/tui/test_app.py`.
- [ ] Extend `tests/tui/test_lazy_import.py` with `keyring`/`tomlkit` assertions alongside the
      existing `textual` assertion.
- [ ] Framework install: none — pytest/pytest-asyncio are already dev dependencies; no new test
      framework needed.

## Sources

### Primary (HIGH confidence)
- Context7 `/jaraco/keyring` — `get_password`/`set_password`/`delete_password` core API,
  `keyring.errors` (`NoKeyringError`, `PasswordDeleteError`, `KeyringError`), `get_keyring()`,
  `WinVaultKeyring` persistence configuration.
- Context7 `/python-poetry/tomlkit` — `parse`/`dumps`/`document`/`table`/`setdefault`,
  formatting-preservation round-trip examples, super-tables, dotted keys, `TOMLFile`/`dump`.
- This codebase, read directly: `src/agent86/config.py`, `src/agent86/types.py`,
  `src/agent86/cognitive/{base,anthropic_provider,openai_provider,ollama_provider,
  llamacpp_provider}.py`, `src/agent86/tui/{app,commands,turn_bridge}.py`,
  `src/agent86/tui/screens/{approval,model_picker,mode_picker}.py`,
  `src/agent86/orchestration/loop.py`, `pyproject.toml`, `tests/tui/*.py`,
  `tests/unit/test_config.py`.

### Secondary (MEDIUM confidence)
- WebSearch, Anthropic `GET /v1/models` response shape (`anthropic.mintlify.app/en/api/
  models-list`) — cross-checked against the shape's internal consistency (cursor pagination
  fields match Anthropic's other list endpoints) but not fetched via Context7.
- WebSearch, Ollama `GET /api/tags` response shape (`docs.ollama.com/api/tags`,
  `github.com/ollama/ollama/blob/main/docs/api.md`) — official docs, consistent across two
  independent result sources.
- WebSearch, OpenRouter `GET /api/v1/models` response shape — official docs referenced but exact
  field list (context_length presence) not fully confirmed in the fetched excerpt; verify at
  implementation time with a live unauthenticated call (`curl https://openrouter.ai/api/v1/models`)
  before writing the normalizer.

### Tertiary (LOW confidence)
- Groq `/v1/models` schema — inferred from Groq's documented OpenAI-API-compatibility claim, not
  independently fetched this session. Verify with a live call (or Groq's own docs) at
  implementation time; treat the OpenAI-shape assumption as needing a quick confirmation, not a
  blocker.
- Windows Credential Manager payload size limit (Pitfall 3) — general knowledge of
  `WinVaultKeyring` constraints, not pinned to a specific byte count from an official source this
  session. Treat as "handle the error gracefully" guidance rather than a hard number to code
  against.

## Metadata

**Confidence breakdown:**
- Standard stack (keyring, tomlkit APIs): HIGH — verified via Context7 against current library
  docs, plus this codebase's existing lazy-import precedent for `textual`.
- Architecture (modal chaining, worker-thread test, config-writer module boundary): HIGH — every
  pattern is a direct extension of an already-proven, already-tested precedent in this exact
  codebase (`ApprovalModal`, `ModelPickerModal`, `run_turn_worker`, `load_config`/`_deep_merge`).
- Provider models-endpoint schemas: MEDIUM — OpenAI/Anthropic/Ollama shapes cross-verified across
  multiple sources; OpenRouter/Groq shapes MEDIUM/LOW pending a live-call confirmation at
  implementation time (flagged explicitly, not blocking).
- Pitfalls: HIGH for the codebase-specific ones (require_key regression, ProviderError message
  preservation — read directly from source); MEDIUM for the OS-keyring-specific ones (Windows
  Credential Manager size limit, SecretService hang risk — general library knowledge, not
  independently reproduced this session).

**Research date:** 2026-07-21
**Valid until:** ~30 days for the architecture/codebase findings (stable, first-party); ~14 days
for the provider models-endpoint schemas (third-party APIs can add fields without notice; OpenAI/
Anthropic/Ollama are stable, OpenRouter/Groq should be reconfirmed if implementation is delayed).
</content>
</function_results>