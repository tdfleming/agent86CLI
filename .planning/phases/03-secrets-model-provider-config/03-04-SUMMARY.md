---
phase: 03-secrets-model-provider-config
plan: 04
subsystem: cognitive
tags: [catalog, httpx, model-listing, wave-1]

# Dependency graph
requires:
  - phase: 03-secrets-model-provider-config
    plan: 01
    provides: "tests/unit/test_catalog.py xfail scaffold + tests/fixtures/catalog/*.json fixtures targeting the exact interface this plan implements"
provides:
  - "agent86.cognitive.catalog: fetch_catalog/fetch_openai_compatible/fetch_anthropic/fetch_ollama/CatalogUnavailable"
  - "Per-provider live model listing normalized to (ref, label) pairs for all six seeded providers"
affects: [03-06-key-entry-connection-test, 03-08-provider-manager]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CatalogUnavailable is the single failure signal for both HTTP errors and providers with no listing endpoint (llamacpp) — callers never hit a dead end, always fall back to free-text provider:model entry"
    - "URL suffix tolerance (_v1 helper) mirrors OpenAIProvider's existing base + ('' if base.endswith('/v1') else '/v1') convention verbatim"

key-files:
  created:
    - src/agent86/cognitive/catalog.py
  modified:
    - tests/unit/test_catalog.py

key-decisions:
  - "No fixture changes needed: live OpenRouter GET /api/v1/models on 2026-08-05 confirmed data[].id + data[].name match the Wave 0 fixture exactly"
  - "Groq's schema remains unverified live (no GROQ_API_KEY in this environment, docs page is client-rendered) — recorded explicitly in code and here per 03-VALIDATION.md Manual-Only row 3, using the fixture's inferred {\"object\":\"list\",\"data\":[{\"id\":...}]} shape (matches OpenAI's own convention, which Groq explicitly mirrors)"

requirements-completed: [MODEL-01]

# Metrics
duration: ~25min
completed: 2026-08-06
---

# Phase 3 Plan 4: Catalog Fetch + Normalization Summary

**New `agent86.cognitive.catalog` module fetches each of the five distinct provider model-listing endpoint shapes (OpenAI-compatible, Anthropic, Ollama) and normalizes them into a common `(ref, label)` list, with `CatalogUnavailable` as the single fallback signal for any failure or unsupported provider (llama.cpp).**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-08-06T00:02Z (session start)
- **Completed:** 2026-08-06T00:07Z
- **Tasks:** 2/2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- `src/agent86/cognitive/catalog.py` created with `fetch_openai_compatible`, `fetch_anthropic`,
  `fetch_ollama`, `fetch_catalog`, and `CatalogUnavailable`, matching the plan's reference
  implementation exactly (D-01/D-02: the live endpoint is the only source of truth, nothing
  hardcoded).
- Anthropic fetches use `x-api-key` + `anthropic-version: 2023-06-01`, never
  `Authorization: Bearer` (the silent-401 trap RESEARCH Pitfall 4 warned about) — proven by
  `test_anthropic_uses_display_name_and_x_api_key_header`.
- Every failure path (HTTP error, non-2xx, unsupported provider) raises `CatalogUnavailable`
  carrying the original message, so the caller (a later plan's TUI picker) always has a free-text
  fallback and never hits a dead end.
- Deleted the Wave 0 `pytestmark = pytest.mark.xfail(...)` line from `tests/unit/test_catalog.py`
  as the first act (RED confirmed before implementing); all 9 tests in that module now pass for
  real, 0 xfailed.
- OpenRouter's live schema (RESEARCH MEDIUM confidence) was confirmed against a real
  `GET https://openrouter.ai/api/v1/models` call — `data[].id` + `data[].name` match the Wave 0
  fixture exactly, no fixture correction needed.
- Groq's schema (RESEARCH LOW confidence) could not be confirmed live in this environment (no
  `GROQ_API_KEY`, docs page client-rendered) — recorded explicitly under `## Unverified` below and
  in a code comment, so `03-VALIDATION.md`'s Manual-Only row 3 stays open for a future manual pass.
- Full suite green: 229 passed, 16 xfailed, 1 xpassed, 0 failed (verified after parallel agents
  03-02/03-03 also landed; an earlier mid-execution full-suite run showed 3 failures in
  `tests/unit/test_providers_key_seam.py`, which is outside this plan's `files_modified` and owned
  by the parallel 03-02 agent — not touched here).

## Task Commits

1. **Task 1: Implement the per-provider fetchers and normalizers** - `8f32489` (feat)
2. **Task 2: Confirm the MEDIUM/LOW-confidence OpenRouter and Groq schemas against live endpoints** - `72a2d24` (docs)

**Plan metadata:** (this commit) `docs(03-04): complete catalog fetch plan`

## Files Created/Modified

- `src/agent86/cognitive/catalog.py` - new module: `fetch_openai_compatible`/`fetch_anthropic`/
  `fetch_ollama`/`fetch_catalog`/`CatalogUnavailable`, normalizing all five endpoint response
  shapes into `(ref, label)` pairs; `_v1()` reuses `OpenAIProvider`'s URL-suffix-tolerance
  convention verbatim; `_get_json()` centralizes the httpx-error-to-`CatalogUnavailable` mapping.
- `tests/unit/test_catalog.py` - Wave 0 xfail marker removed; all 9 tests now assert real
  behavior against `tests/fixtures/catalog/*.json` with `httpx.get` monkeypatched (no real
  network calls in the test suite).

## Decisions Made

- No fixture changes needed for OpenRouter after live verification.
- Groq's response shape assumption (`{"object":"list","data":[{"id":...}]}`, matching OpenAI's
  own `/v1/models` shape which Groq explicitly advertises OpenAI-compatibility with) was kept
  as-is since no live confirmation was possible in this environment; flagged as still-open in
  `## Unverified` below.

## Deviations from Plan

None — plan executed exactly as written. The reference implementation in the plan's `<action>`
block was used verbatim (with the docstring's dashes normalized to ASCII `--` for Windows
console safety, matching the project's existing UTF-8-reconfigure convention).

## Unverified

- **Groq's `GET https://api.groq.com/openai/v1/models` response shape** could not be confirmed
  against the live endpoint in this execution environment: no `GROQ_API_KEY` was present to
  authenticate the call (an unauthenticated request returned `{"error":{"code":"invalid_api_key"}}`
  as expected), and `https://console.groq.com/docs/api-reference` is client-side rendered so a
  plain `curl` fetch returned no matching schema text. The fixture and normalizer keep the
  RESEARCH-inferred `{"object":"list","data":[{"id":...}]}` shape (identical to OpenAI's, which
  Groq documents itself as OpenAI-compatible with). `03-VALIDATION.md`'s Manual-Only row 3
  ("Live catalog fetch against OpenRouter and Groq") stays open for Groq specifically — a future
  manual pass with a real `GROQ_API_KEY` should confirm this before relying on it in production.

## Issues Encountered

None blocking. A full-suite run mid-execution showed 3 failures in
`tests/unit/test_providers_key_seam.py::test_keyring_supplies_key_when_env_absent`,
`test_custom_section_name_is_the_keyring_account`, and `test_explicit_api_key_argument_wins` —
these are outside this plan's scope (`src/agent86/cognitive/catalog.py` and
`tests/unit/test_catalog.py` only) and were caused by the parallel 03-02 agent's in-progress edits
to `src/agent86/cognitive/base.py`/`openai_provider.py`/`anthropic_provider.py`. A subsequent full
run after both parallel plans landed showed 0 failed, confirming this was transient inter-agent
interleaving, not a defect introduced here.

## User Setup Required

None. `httpx` was already a dependency (used by `OpenAIProvider`/`AnthropicProvider`); no new
packages, no lazy-import guard changes needed for this plan.

## Next Phase Readiness

`fetch_catalog` and `CatalogUnavailable` are ready for plans 03-06 (key entry / connection test)
and 03-08 (provider manager / `CatalogPickerModal`) to import and wire into the TUI's live model
picker, with the free-text fallback path already proven by `test_llamacpp_has_no_catalog` and
`test_fetch_failure_falls_back`.

---
*Phase: 03-secrets-model-provider-config*
*Completed: 2026-08-06*

## Self-Check: PASSED

Both key files confirmed present on disk (`src/agent86/cognitive/catalog.py`,
`tests/unit/test_catalog.py`); both task commits (8f32489, 72a2d24) confirmed in git history.
