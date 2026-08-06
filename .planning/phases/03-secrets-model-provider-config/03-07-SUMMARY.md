---
phase: 03-secrets-model-provider-config
plan: 07
subsystem: ui
tags: [textual, modal, tomlkit, diff-preview, config-write-back]

# Dependency graph
requires:
  - phase: 03-secrets-model-provider-config
    plan: 01
    provides: "xfail-scaffolded tests/tui/test_save_diff.py Pilot tests targeting SaveDiffModal, plus tests/fixtures/config_with_comments.toml"
  - phase: 03-secrets-model-provider-config
    plan: 03
    provides: "agent86.config_writer: plan_edit/apply_edit two-step tomlkit round-trip write-back with ConfigEdit/ConfigWriteError, SCOPE_USER/SCOPE_PROJECT, scope_path"
provides:
  - "agent86.tui.screens.save_diff.SaveDiffModal — ModalScreen[ConfigEdit | None] previewing the exact unified diff and target path for a set of pending config changes before any disk write, with a user/project scope RadioSet (user pre-selected)"
affects: [03-08-provider-manager, 03-09-full-app-chain]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SaveDiffModal never calls apply_edit itself — it only calls plan_edit (pure, no disk I/O) and dismisses with the resulting ConfigEdit; the caller (provider_manager / app chain) is responsible for calling config_writer.apply_edit on confirm"
    - "Static(..., markup=False) used for #save-diff-body so unified-diff text containing literal '[' (from model refs like anthropic/claude) round-trips byte-for-byte through Rich's renderable, satisfying the diff-matches-actual-write test"

key-files:
  created:
    - src/agent86/tui/screens/save_diff.py
  modified:
    - tests/tui/test_save_diff.py
    - .planning/phases/03-secrets-model-provider-config/deferred-items.md

key-decisions:
  - "ConfigWriteError/ValueError from plan_edit (malformed existing TOML, or a change touching a forbidden secret leaf key) is caught in _refresh and rendered as plain text in #save-diff-body with #save-confirm disabled, rather than letting the modal crash — matches the plan's acceptance criterion for a malformed config file"

requirements-completed: [MODEL-02]

# Metrics
duration: ~15min
completed: 2026-08-06
---

# Phase 3 Plan 7: Save-Diff Modal (SaveDiffModal) Summary

**`SaveDiffModal` — a `ModalScreen[ConfigEdit | None]` that previews the exact unified diff and target file path for pending config changes, with a user/project scope `RadioSet` (user pre-selected), before anything is written to disk.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2/2 complete
- **Files modified:** 2 (1 created, 1 modified) plus a deferred-items note

## Accomplishments

- `src/agent86/tui/screens/save_diff.py` created exactly per the plan's module-body spec:
  `SaveDiffModal(changes, scope=SCOPE_USER)` composes a `RadioSet#save-scope` (`#scope-user`
  pre-selected, `#scope-project` one arrow key away), a `#save-target` path label, a
  `#save-diff-body` `Static` diff preview, and `#save-confirm`/`#save-cancel` buttons.
- On mount and on every scope change, `_refresh` calls `agent86.config_writer.plan_edit(scope,
  changes)` — pure, no disk I/O — and re-renders the diff/target. A no-op edit renders "No
  changes." instead of an empty diff.
- `ConfigWriteError` (malformed existing TOML) or `ValueError` (e.g. a forbidden secret leaf key)
  is caught, rendered as the exception text in `#save-diff-body`, and disables `#save-confirm` —
  no crash.
- `#save-confirm` dismisses with the live `ConfigEdit`; `#save-cancel` and `Escape`
  (`action_cancel`) both dismiss with `None`. The modal itself contains no `apply_edit`/
  `write_text`/`os.replace` call anywhere — write-back stays the caller's responsibility.
- `#save-diff-body` uses `Static(..., markup=False)` so diff text containing literal `[`
  characters (model refs like `anthropic/claude`) renders byte-identical to `edit.diff`.
- Deleted the Wave 0 `pytestmark = pytest.mark.xfail(...)` line from `tests/tui/test_save_diff.py`;
  all 4 originally-scaffolded tests pass for real (diff-matches-write, default-scope-is-user,
  project-scope-recomputes-path, cancel-returns-none).
- Added 2 integration-strength tests: `test_preview_then_apply_preserves_all_comments` proves the
  previewed text equals `edit.diff`, the written file equals `edit.after_text`, all four
  hand-written comments from `tests/fixtures/config_with_comments.toml` survive, and the new
  `api_key_env = "GROQ_API_KEY"` line is present; `test_malformed_existing_config_disables_save`
  proves a broken `"[model\nbroken"` file disables `#save-confirm`, renders "Malformed config
  at ...", and leaves the file untouched after Escape.

## Task Commits

1. **Task 1: SaveDiffModal — scope radio + live diff preview + confirm/cancel** — `a20c9fb` (feat)
2. **Task 2: Prove the preview equals the write on a real commented config** — `4b534cf` (test)

**Plan metadata:** (this commit) `docs(03-07): complete save-diff plan`

## Files Created/Modified

- `src/agent86/tui/screens/save_diff.py` (new, 96 lines) — `SaveDiffModal`
- `tests/tui/test_save_diff.py` — xfail marker removed; 2 new integration tests added (6 test
  functions total)
- `.planning/phases/03-secrets-model-provider-config/deferred-items.md` — logged 7 out-of-scope
  failures observed mid-run in files owned by parallel plans 03-06/03-08

## Decisions Made

- `ConfigWriteError`/`ValueError` handling lives entirely inside `_refresh` rather than being
  surfaced as an uncaught exception — matches the plan's explicit acceptance criterion ("renders
  the error text and disables `#save-confirm` rather than crashing") and keeps every dismissal
  path (confirm/cancel/escape) resolving to an explicit value even when the current scope's file
  is unreadable.

## Deviations from Plan

None — plan executed exactly as written, including the module-body content specified verbatim in
the plan's `<action>` block.

## Issues Encountered

None for this plan's own files. Running the full suite mid-execution showed 7 failures in
`tests/tui/test_connection_test.py` (`ModuleNotFoundError: agent86.tui.screens.connection_test`)
and `tests/tui/test_provider_manager.py` (`ImportError: CatalogPickerModal`) — both owned by
parallel plans 03-06 and 03-08, which were still in progress. Verified no file overlap with
`save_diff.py`; logged to `deferred-items.md` per the parallel-execution scope boundary rather
than fixed here. `pytest tests/tui/test_save_diff.py -q` reports 6 passed, 0 xfailed on its own,
both before and after that observation.

## User Setup Required

None.

## Next Phase Readiness

`SaveDiffModal` is ready for plan 03-08 (`provider_manager.py`) and 03-09 (full-app chain) to push
it with a computed `changes` list and, on receiving a non-`None` `ConfigEdit`, call
`config_writer.apply_edit(edit)` to commit. No additional seam work needed in this module.

---
*Phase: 03-secrets-model-provider-config*
*Completed: 2026-08-06*

## Self-Check: PASSED

`src/agent86/tui/screens/save_diff.py` confirmed present on disk; both task commits (a20c9fb,
4b534cf) confirmed in git history via `git log --oneline`.
