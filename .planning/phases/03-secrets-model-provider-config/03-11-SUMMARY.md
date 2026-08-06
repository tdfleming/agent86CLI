---
phase: 03-secrets-model-provider-config
plan: 11
subsystem: security
tags: [rich, typer, traceback, redaction, providererror, cognitive-base]

# Dependency graph
requires:
  - phase: 03-secrets-model-provider-config
    provides: "resolve_api_key/secrets.py seam and provider_for_ref (plan 03-02)"
provides:
  - "agent86.secrets.redact() — strips explicit secrets and key-shaped tokens from any string"
  - "Typer app configured with pretty_exceptions_show_locals=False"
  - "provider_for_ref construction guard: any non-ProviderError exception below key resolution
    is converted to a ProviderError with a redacted message and severed __cause__ chain"
affects: [phase-04-mcp-config-ui, phase-05-packaging-hardening]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Construction guard pattern: dispatch chain extracted to a private _build_provider(),
      wrapped by the public factory in try/except Exception that redacts and re-raises `from
      None` so frames holding a secret local are never captured in a traceback"

key-files:
  created:
    - tests/unit/test_secret_traceback.py
  modified:
    - src/agent86/cli.py
    - src/agent86/secrets.py
    - src/agent86/cognitive/base.py

key-decisions:
  - "redact() is a simple two-pass replace (explicit secrets, len >= 8 guard) + regex fallback
    for key-shaped tokens (sk-/gsk_/xai-/AIza prefixes) — deliberately conservative, false
    positives only reduce message precision, false negatives leak"
  - "except ProviderError: raise placed before the catch-all Exception handler so deliberate
    ProviderError wording (missing key, missing SDK, unknown provider) stays pinned verbatim"
  - "raise ... from None (not from exc) — the chained traceback's frames hold the key in their
    locals, so severing __cause__ is required, not just cosmetic"

requirements-completed: [SEC-01]

duration: 20min
completed: 2026-08-06
---

# Phase 03 Plan 11: Traceback Secret-Leak Closure (UAT gap 2) Summary

**Typer's frame-local rendering is disabled and provider construction now fails soft through a
redacting `ProviderError` guard, closing the second independent secret-leak path found in UAT
(a crash below key resolution rendering a live `sk-ant-...` local in four traceback frames).**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-08-06T02:57:00Z
- **Tasks:** 3
- **Files modified:** 3 (+1 test file created)

## Accomplishments
- `agent86.cli.app` now built with `pretty_exceptions_show_locals=False` — Rich will never print
  a frame-local `api_key` regardless of where an unhandled exception originates.
- `agent86.secrets.redact()` added and exported — strips explicit secrets and key-shaped tokens
  (`sk-`, `gsk_`, `xai-`, `AIza` prefixes) from any human-visible string, never raises.
- `provider_for_ref` in `cognitive/base.py` refactored: the existing dispatch chain moved
  verbatim into a private `_build_provider()`; the public factory now wraps it in
  `try/except ProviderError: raise` / `except Exception: redact + raise ProviderError(...) from
  None`, severing the cause chain so no frame holding the key is ever rendered.
- 10 new regression tests in `tests/unit/test_secret_traceback.py`; two of them
  (`test_construction_typeerror_becomes_provider_error`,
  `test_formatted_traceback_has_no_key`) confirmed to FAIL against the pre-fix `base.py` via a
  `git stash` round-trip, proving they would have caught UAT gap 2.
- Full suite green: 331 passed (this plan's 10 new tests plus tests added concurrently by
  sibling gap-closure plans running in the same parallel wave).

## Task Commits

Each task was committed atomically:

1. **Task 1: Disable frame-local rendering and add secrets.redact()** - `3c03fda` (feat)
2. **Task 2: Make provider construction fail soft with a redacted, cause-severed ProviderError** - `6e14ed4` (feat)
3. **Task 3: Regression test module for the traceback leak** - `53b52e8` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/agent86/cli.py` - `typer.Typer(...)` gains `pretty_exceptions_show_locals=False` with a
  SEC-01/D-10 comment
- `src/agent86/secrets.py` - adds `redact()` (module-scope `re`, no keyring import added) and
  exports it in `__all__`
- `src/agent86/cognitive/base.py` - `provider_for_ref` split into `_build_provider` (the
  untouched dispatch chain) + a guarding wrapper that redacts and re-raises `from None`
- `tests/unit/test_secret_traceback.py` - 10 regression tests (new file)

## Decisions Made
- Followed the plan's exact code templates for `redact()` and the `provider_for_ref` guard —
  no architectural deviation.
- See `key-decisions` in frontmatter for the redaction/guard rationale.

## Deviations from Plan

None — plan executed exactly as written. One documentation-only note: the plan's acceptance
criterion `grep -c "from None" src/agent86/cognitive/base.py` returns `1`, but following the
plan's own literal code template (which includes both a `# \`from None\` is deliberate...`
comment line and the `) from None` code line) produces `2` matching lines. Both lines are
copied verbatim from the plan's `<action>` block; this is a pre-existing miscount in the plan
text, not a functional issue. All other acceptance criteria (including the ones that count
actual behavior) pass exactly as specified.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
UAT gap 2 (SEC-01/D-10 traceback secret leak) is closed at both layers: Rich never renders
frame locals, and no unguarded exception can escape provider construction with a live cause
chain. Combined with plan 03-10 (transcript echo fix), both independent UAT-found leak paths
are closed. Phase 3 gap-closure plans 03-10..03-13 running in parallel; this plan's changes
(cli.py, secrets.py, cognitive/base.py) are additive and do not touch files owned by sibling
gap plans, so no merge conflicts are expected.

---
*Phase: 03-secrets-model-provider-config*
*Completed: 2026-08-06*

## Self-Check: PASSED

All created/modified files found on disk; all three task commit hashes (3c03fda, 6e14ed4,
53b52e8) found in git log.
