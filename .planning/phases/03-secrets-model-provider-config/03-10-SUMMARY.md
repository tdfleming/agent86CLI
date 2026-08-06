---
phase: 03-secrets-model-provider-config
plan: 10
subsystem: ui
tags: [textual, tui, secrets, keyring, event-handling]

# Dependency graph
requires:
  - phase: 03-secrets-model-provider-config
    provides: KeyEntryModal, CatalogPickerModal, ConnectionTestModal, the full `/config model` chain (plans 03-05..03-09)
provides:
  - "KeyEntryModal and CatalogPickerModal consume their own Input.Submitted (event.stop())"
  - "Agent86App.on_input_submitted ignores every Input except #prompt"
  - "_on_catalog_picked passes the UNRESOLVED sentinel instead of a stale None, so a keyring-stored key resolves on every connection test, not just the first"
  - "tests/tui/test_secret_leak.py — 6 regression tests proving both gaps stay closed"
affects: [03-human-uat, 03-VALIDATION]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "event.stop() as the first statement of a modal's on_input_submitted, defense-in-depth alongside an App-level event.input.id guard"
    - "UNRESOLVED sentinel pass-through at the call site, not just at the factory default"

key-files:
  created:
    - tests/tui/test_secret_leak.py
  modified:
    - src/agent86/tui/screens/key_entry.py
    - src/agent86/tui/screens/provider_manager.py
    - src/agent86/tui/screens/connection_test.py
    - src/agent86/tui/app.py

key-decisions:
  - "Both gaps modify src/agent86/tui/app.py, so they were closed in one plan to avoid a parallel write conflict"
  - "Fixed the leak in three places (KeyEntryModal, CatalogPickerModal, and the App guard) rather than relying on any single one, per the plan's defense-in-depth requirement"

patterns-established:
  - "Every ModalScreen with its own Input must call event.stop() in on_input_submitted before dismiss(), mirroring the App's #prompt-only guard"

requirements-completed: [SEC-01, MODEL-01]

# Metrics
duration: 25min
completed: 2026-08-06
---

# Phase 3 Plan 10: Close UAT Gaps 1 and 4 (Secret Leak + Keyring Resolution) Summary

**Consumed `Input.Submitted` inside `KeyEntryModal`/`CatalogPickerModal` and guarded `Agent86App.on_input_submitted` to `#prompt` only, closing a raw-API-key transcript/turn leak; replaced the stale `None` passed to `ConnectionTestModal` with the `UNRESOLVED` sentinel so a keyring-stored key resolves on every connection test, not just the first.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-08-06T02:58:01Z
- **Tasks:** 3
- **Files modified:** 4 (+1 test file created)

## Accomplishments
- UAT gap 1 (blocker, SEC-01/D-10) closed: a typed API key can no longer be echoed into the transcript or dispatched to the model as a turn — three independent fixes (two modals + the App guard).
- UAT gap 4 (blocker, MODEL-01) closed: a keyring-stored key now resolves on the second and every subsequent connection test in a session, not just the first.
- Six new regression tests added, confirmed (by temporarily checking out the pre-fix source) to fail 4/6 against the pre-fix code and pass 6/6 post-fix.
- Full suite green: 331 passed, 0 failed (baseline had grown to 325 via parallel plans 03-11/03-12 landing concurrently; 6 new tests bring it to 331).

## Task Commits

Each task was committed atomically:

1. **Task 1: Stop Input.Submitted from escaping the modals, and guard the App handler** - `a1d59d1` (fix)
2. **Task 2: Pass UNRESOLVED (not None) so a keyring-stored key is resolved on every test** - `a1bbc0d` (fix)
3. **Task 3: Regression tests that fail on the pre-fix code** - `9605b52` (test)

## Files Created/Modified
- `src/agent86/tui/screens/key_entry.py` - `on_input_submitted` calls `event.stop()` as its first statement before reading the value
- `src/agent86/tui/screens/provider_manager.py` - `CatalogPickerModal.on_input_submitted` calls `event.stop()` as its first statement; `ProviderManagerModal`/other logic unchanged
- `src/agent86/tui/app.py` - `on_input_submitted` returns immediately unless `event.input.id == "prompt"`; `_on_catalog_picked` now imports `UNRESOLVED` and passes it to `ConnectionTestModal` whenever `self._pending_key is None`
- `src/agent86/tui/screens/connection_test.py` - `ConnectionTestModal.__init__` widens `api_key: str | None` to `api_key: Any = UNRESOLVED`, importing `UNRESOLVED` from `agent86.cognitive.base`; `_run_test` behavior unchanged, it already forwards `self._api_key` verbatim
- `tests/tui/test_secret_leak.py` (new) - 6 Pilot regression tests: transcript-no-echo, no-turn-dispatch (KeyEntryModal), no-dispatch (CatalogPickerModal), `#prompt` control test, and two `UNRESOLVED`/typed-key-passthrough tests against `_on_catalog_picked`

## Decisions Made
- Both gaps touch `src/agent86/tui/app.py`; closing them in one plan (rather than two parallel plans) avoided a write conflict on that file, as called out in the plan's objective.
- Kept all three defense-in-depth fixes from the plan (both modals' `event.stop()` plus the App-level `event.input.id != "prompt"` guard) rather than relying on any single layer — matches the plan's explicit "none substitutes for another" instruction.
- `_on_test_done`'s `finally: self._pending_key = None` was left untouched; the fix is entirely at the read site (`_on_catalog_picked`), per the plan.

## Deviations from Plan

None - plan executed exactly as written. The full test suite baseline had grown from 275 to 325 (parallel plans 03-11/03-12 landed additional tests concurrently with this plan), so the final count (331 = 325 + 6 new) differs from the plan's stated "281 minimum" arithmetic, but the plan's actual requirement — "no fewer than 281 passed" — is satisfied with margin.

## Issues Encountered
None. Confirming the pre-fix failure required temporarily checking out the four `src/` files at the commit preceding this plan's Task 1 commit (`git checkout dea0d9a -- <files>`) rather than `git stash`, since Task 1 and Task 2 had already been committed by the time Task 3 ran the required pre-fix confirmation; the pre-fix run showed 4 of 6 new tests failing (`test_key_entry_submit_does_not_echo_to_transcript`, `test_key_entry_submit_does_not_start_a_turn`, `test_catalog_filter_submit_does_not_dispatch`, `test_second_connection_test_uses_unresolved`), exceeding the plan's "at least two" requirement. The fixed files were restored immediately after (`git checkout HEAD -- <files>`) and re-verified green.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Both UAT blocker gaps (1 and 4) from `03-HUMAN-UAT.md` are closed and regression-tested.
- Remaining UAT gaps (2, 3, 5, and the blocked item) are addressed by sibling plans 03-11 through 03-13, already landing in parallel.
- No known stubs introduced by this plan.

---
*Phase: 03-secrets-model-provider-config*
*Completed: 2026-08-06*

## Self-Check: PASSED

All created/modified files found on disk; all 3 task commit hashes (a1d59d1, a1bbc0d, 9605b52) found in git history.
