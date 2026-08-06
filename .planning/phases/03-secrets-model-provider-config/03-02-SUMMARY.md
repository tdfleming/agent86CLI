---
phase: 03-secrets-model-provider-config
plan: 02
subsystem: auth
tags: [keyring, secrets, cognitive-tier, api-keys]

# Dependency graph
requires:
  - phase: 03-secrets-model-provider-config
    provides: "Wave 0 xfail-scaffolded tests/unit/test_secrets.py and tests/unit/test_providers_key_seam.py written against the exact interfaces this plan implements (03-01)"
provides:
  - "agent86.secrets module: resolve_api_key/keyring_available/has_stored_key/store_api_key/clear_api_key, env-first-then-keyring, never raises, keyring imported lazily inside function bodies"
  - "provider_for_ref(ref, config, api_key=UNRESOLVED) resolves the key once, keyed on ref.provider (the config section name), and injects it into every provider constructor"
  - "AnthropicProvider/OpenAIProvider/LlamaCppProvider constructors accept an injected api_key (UNRESOLVED sentinel falls back to self-resolution for existing direct-construction call sites)"
affects: [03-06-key-entry-connection-test, 03-07-save-diff, 03-08-provider-manager, 03-09-full-app-chain]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "UNRESOLVED sentinel (object() typed Any) distinguishes 'caller passed no key, resolve it yourself' from 'caller passed None deliberately' — lets provider_for_ref resolve once while direct construction in tests/ad-hoc code keeps self-resolving"
    - "keyring imported lazily inside every agent86.secrets function body, never at module top-level, to preserve the run/--plain cold-start guarantee"

key-files:
  created:
    - src/agent86/secrets.py
  modified:
    - src/agent86/cognitive/base.py
    - src/agent86/cognitive/anthropic_provider.py
    - src/agent86/cognitive/openai_provider.py
    - src/agent86/cognitive/llamacpp_provider.py
    - tests/unit/test_secrets.py
    - tests/unit/test_providers_key_seam.py

key-decisions:
  - "Key resolution happens once in provider_for_ref, keyed on ref.provider (the config section name), not inside each provider's __init__ by default — this is the only place that knows a custom [providers.myvllm] block's section name (RESEARCH Open Question 2, resolved)"
  - "ProviderError wording preserved verbatim with only an appended clause ('...or store a key in the OS keyring via /config model.') to avoid breaking existing message-prefix assertions"

requirements-completed: [SEC-01]

# Metrics
duration: ~25min
completed: 2026-08-06
---

# Phase 3 Plan 2: Secrets Seam + Provider Key Injection Summary

**`agent86.secrets.resolve_api_key` (env-first, then OS keyring, never raises) now backs every keyed provider via a single resolution point in `provider_for_ref`, keyed on the config section name.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-08-06T00:00Z (approx, based on session context)
- **Completed:** 2026-08-06T00:07:47Z
- **Tasks:** 2/2
- **Files modified:** 6 (1 created, 5 modified)

## Accomplishments
- `src/agent86/secrets.py` created: `resolve_api_key`/`keyring_available`/`has_stored_key`/`store_api_key`/`clear_api_key`, all degrading silently (never raising) when keyring is absent or broken, keyring imported lazily inside each function body
- `provider_for_ref` in `cognitive/base.py` gained an `api_key: Any = UNRESOLVED` parameter; resolves the key once via `resolve_api_key(ref.provider, pconf.api_key_env)` and threads it into every provider construction path (Anthropic, OpenAI, LlamaCpp, and the OpenAI-compatible fallback)
- `AnthropicProvider`, `OpenAIProvider`, `LlamaCppProvider` constructors now accept an injected `api_key`, falling back to self-resolution via `resolve_api_key` when the `UNRESOLVED` sentinel is passed (preserving every existing direct-construction call site, including positional `require_key` args)
- Both `os.getenv(api_key_env)` seams removed from `src/agent86/cognitive/` entirely
- Wave 0 xfail markers deleted from `tests/unit/test_secrets.py` (7 tests) and `tests/unit/test_providers_key_seam.py` (6 tests) — all now pass for real
- Full suite green: 229 passed, 16 xfailed, 1 xpassed (unrelated, owned by plans 03-08/03-09), 0 failed

## Task Commits

1. **Task 1: Create agent86/secrets.py** - `8cd0fdb` (feat)
2. **Task 2: Move key resolution into provider_for_ref and inject it into provider constructors** - `7aa9f7d` (feat)

**Plan metadata:** (this commit) `docs(03-02): complete secrets seam plan`

## Files Created/Modified
- `src/agent86/secrets.py` - env-then-keyring resolution seam; SERVICE_NAME="agent86"; SecretStoreError for store/clear failures
- `src/agent86/cognitive/base.py` - `UNRESOLVED` sentinel added; `provider_for_ref` resolves the key once and injects it into every provider construction branch
- `src/agent86/cognitive/anthropic_provider.py` - `__init__` accepts `api_key: Any = UNRESOLVED`; falls back to `resolve_api_key("anthropic", key_env)`; original error wording preserved, clause appended
- `src/agent86/cognitive/openai_provider.py` - `__init__` accepts `api_key: Any = UNRESOLVED` as a new 4th keyword param (require_key keeps its 3rd-positional slot); falls back to `resolve_api_key(self.name, config.api_key_env)`; original error wording preserved, clause appended
- `src/agent86/cognitive/llamacpp_provider.py` - forwards `api_key` through to `OpenAIProvider.__init__`
- `tests/unit/test_secrets.py` - Wave 0 xfail marker removed; all 7 tests now genuinely pass
- `tests/unit/test_providers_key_seam.py` - Wave 0 xfail marker removed; all 6 tests now genuinely pass

## Decisions Made
- Resolved RESEARCH Open Question 2 exactly as specified in the plan: resolve once in `provider_for_ref`, keyed on `ref.provider`, not inside each provider constructor by default — only `provider_for_ref` knows the config section name for custom `[providers.NAME]` blocks
- Kept `require_key`'s existing 3rd-positional slot in `OpenAIProvider.__init__` and appended `api_key` as a 4th keyword-only-by-convention param, preserving `OpenAIProvider("test-model", ProviderConfig(...), require_key=False)` call sites unchanged

## Deviations from Plan

None - plan executed exactly as written. Implementation matched the plan's provided code blocks verbatim (with only whitespace/formatting adjustments from the code block being illustrative).

## Issues Encountered
None. Both tasks' acceptance-criteria greps (xfail markers removed, no `os.getenv` for keys remaining, wording preserved, `UNRESOLVED`/`resolve_api_key` wiring present) passed on first verification run.

## User Setup Required
None - no external service configuration required. Manual keyring-integration verification (Windows Credential Manager round-trip) remains a manual-only item per `03-VALIDATION.md`, to be exercised once the TUI key-entry modal (plan 03-06) lands.

## Next Phase Readiness
`resolve_api_key` and the `provider_for_ref(..., api_key=...)` seam are ready for plan 03-06's key-entry/connection-test modal (D-14: test a key before it's stored, using the explicit `api_key` override which never touches the keyring). No blockers for downstream plans in this wave.

---
*Phase: 03-secrets-model-provider-config*
*Completed: 2026-08-06*

## Self-Check: PASSED

`src/agent86/secrets.py` confirmed present; commits `8cd0fdb` and `7aa9f7d` confirmed in git history.
