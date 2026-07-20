---
phase: 02-command-palette-menus
plan: 03
subsystem: ui
tags: [textual, modalscreen, radioset, optionlist, pilot-tests]

# Dependency graph
requires:
  - phase: 01-tui-skeleton-live-status-line
    provides: "ApprovalModal(ModalScreen[bool]) — the proven modal push/dismiss pattern this plan mirrors"
provides:
  - "ModePickerModal(ModalScreen[str | None]) — arrow-key RadioSet emitting 'ask'/'auto'/'deny'"
  - "ModelPickerModal(ModalScreen[str | None]) — arrow-key OptionList emitting a 'provider:model' ref"
  - "model_choices(cfg) — config-sourced (label, value) pairs deduped by ref (D-12)"
affects: [02-04, phase-3-secrets-model-config]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ModalScreen[str | None] with a 'cancel' Escape binding dismissing None, mirroring ApprovalModal exactly"
    - "Config-sourced picker options built as (label, value) tuples with dedup-by-value and role-name aggregation"

key-files:
  created:
    - src/agent86/tui/screens/mode_picker.py
    - src/agent86/tui/screens/model_picker.py
    - tests/tui/test_pickers.py
  modified: []

key-decisions:
  - "model_choices(cfg) sources only the three role slots (default, route.cheap, route.frontier), deduped by ref with role names aggregated in the label — no attempt to synthesize entries for providers with no role reference (D-12, deferred to Phase 3's per-provider catalog)"
  - "Mode picker dismisses the exact lowercase RadioButton label string, never compares against the ApprovalMode enum, avoiding RESEARCH Pitfall 4"

patterns-established:
  - "New ModalScreen[str | None] pickers mirror ApprovalModal's compose/on_event/dismiss shape exactly for consistency and testability"

requirements-completed: [TUI-04]

# Metrics
duration: 25min
completed: 2026-07-20
---

# Phase 2 Plan 3: Arrow-Key Choice Pickers Summary

**Two standalone `ModalScreen[str | None]` pickers — `ModePickerModal` (RadioSet ask/auto/deny) and `ModelPickerModal` (OptionList of config-sourced model refs via `model_choices(cfg)`) — mirroring the proven `ApprovalModal` pattern, ready for Plan 04 to chain into from the palette.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-20T04:16:00Z
- **Completed:** 2026-07-20T04:41:00Z
- **Tasks:** 3
- **Files modified:** 3 (all new)

## Accomplishments
- `ModePickerModal("ask")` renders a `RadioSet` of ask/auto/deny with the current mode pre-pressed; selecting a radio dismisses the exact lowercase string; Escape dismisses `None`.
- `model_choices(cfg)` builds deduped `(label, value)` pairs from the three config role slots, aggregating role names that share a ref into one label (e.g. `"default, route.frontier — anthropic:claude-opus-4-8"`), with a `[]` fallback when no slot has a ref.
- `ModelPickerModal(choices)` renders those pairs as an `OptionList`; selecting an option dismisses with its ref value; Escape dismisses `None`.
- Six Pilot tests (`tests/tui/test_pickers.py`) cover both pickers' select/cancel paths, the model-choices dedup invariant, and the empty-fallback branch, driven via a minimal host `App` (`push_screen` + dismiss-callback), matching the existing `ApprovalModal` test style in `tests/tui/test_app.py`.

## Task Commits

Each task was committed atomically:

1. **Task 1: ModePickerModal — RadioSet of ask/auto/deny** - `8429a45` (feat)
2. **Task 2: ModelPickerModal + model_choices(cfg) source helper (D-12)** - `5af9352` (feat)
3. **Task 3: Pilot tests for both pickers** - `f192a22` (test)

**Plan metadata:** committed separately with STATE.md/ROADMAP.md updates.

_Note: All three files were built implementation-first per the plan's explicit task ordering (mode_picker.py and model_picker.py in Tasks 1-2, the full Pilot-test file in Task 3), rather than strict per-file RED/GREEN, since the plan's own task structure defers all test authorship to Task 3._

## Files Created/Modified
- `src/agent86/tui/screens/mode_picker.py` - `ModePickerModal(ModalScreen[str | None])`
- `src/agent86/tui/screens/model_picker.py` - `ModelPickerModal(ModalScreen[str | None])` + `model_choices(cfg)`
- `tests/tui/test_pickers.py` - Pilot tests for both pickers' select/cancel paths + `model_choices` invariants

## Decisions Made
- Mode picker: emit `str(event.pressed.label)` directly on `RadioSet.Changed`, never compare against `ApprovalMode` enum members (RESEARCH Pitfall 4).
- Model picker: build the list from only the three role slots (`default`/`route.cheap`/`route.frontier`), deduped by ref; no synthesis of entries for providers without a role reference (explicitly deferred to Phase 3's per-provider catalog per D-12).
- Test harness: a minimal host `App` subclass (`_PickerHost`) that pushes the picker on mount and stores the dismissed value via callback — avoids depending on the full `Agent86App`/`_Repl` wiring these standalone screens don't need.

## Deviations from Plan

None - plan executed exactly as written. Task ordering (implementation in Tasks 1-2, full Pilot-test file in Task 3) follows the plan's own task structure, which front-loads both modal implementations before the shared test file.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `ModePickerModal(current: str)` and `ModelPickerModal(choices: list[tuple[str, str]])` constructor signatures, plus `model_choices(cfg) -> list[tuple[str, str]]`, are stable and ready for Plan 04 to `push_screen(..., callback)` from the palette's `needs_choice` chaining (D-10).
- Both pickers dismiss `None` on cancel and the resolved value (mode string or model ref) on selection — Plan 04's callbacks can rely on this contract to synthesize `/mode <value>` / `/model <ref>` and run them through the existing `handle_command` path.
- No blockers.

---
*Phase: 02-command-palette-menus*
*Completed: 2026-07-20*

## Self-Check: PASSED
All created files and task commits verified present on disk / in git history.
