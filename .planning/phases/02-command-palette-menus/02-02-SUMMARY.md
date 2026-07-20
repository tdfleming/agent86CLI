---
phase: 02-command-palette-menus
plan: 02
subsystem: testing
tags: [textual, pilot-test, key-bindings, spike]

# Dependency graph
requires:
  - phase: 02-command-palette-menus (plan 01)
    provides: CommandEntry/COMMANDS registry (not consumed by this spike, but the phase's other
      wave-1 track)
provides:
  - Empirical proof that a permanent priority `enter` Binding suppresses Input.Submitted
  - Empirical proof that omitting the priority `enter` binding preserves Input.Submitted
  - The Enter-routing decision Plan 04 must implement against (Approach B)
affects: [02-04-app-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Wave-0 empirical spike test to resolve a MEDIUM-confidence RESEARCH open question before
      building on top of an assumed API behavior"

key-files:
  created: [tests/tui/test_palette_keys.py]
  modified: []

key-decisions:
  - "Enter-routing decision: Approach B (dynamic/flag-based enter binding) — a permanent
    App-level priority `enter` Binding fully consumes the key event once matched, even when its
    action body is a no-op, so Input.Submitted never fires. Plan 04 must NOT register a permanent
    priority `enter` Binding on Agent86App; it must add/remove the `enter` binding dynamically
    (or otherwise gate it) only while the palette OptionList is actually visible, leaving `enter`
    unbound at the App level whenever the palette is closed so Input's native Enter-submits
    behavior (and therefore D-11 backward compat) is preserved."

patterns-established:
  - "Priority up/down bindings are safe to register permanently (Input has no native up/down
    binding to conflict with), unlike enter which Input does natively bind — confirmed by
    test_up_down_are_free_keys_on_input."

requirements-completed: [TUI-03, TUI-04]

# Metrics
duration: 12min
completed: 2026-07-20
---

# Phase 2 Plan 02: Palette Enter-Routing Spike Summary

**Enter-routing decision: Approach B — a permanent priority `enter` Binding on Agent86App
suppresses Input.Submitted even when its action no-ops, so Plan 04 must dynamically bind/unbind
`enter` only while the palette is open, not register it permanently.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-20T04:40:32Z
- **Completed:** 2026-07-20T04:52:00Z
- **Tasks:** 1 completed
- **Files modified:** 1 created

## Accomplishments
- Wrote `tests/tui/test_palette_keys.py` with a minimal `_PrioritySpikeApp` reproducing the
  planned `Agent86App` priority-`enter`-binding shape (`Binding("enter", "palette_select",
  show=False, priority=True)` whose action no-ops when `palette_open` is False).
- Empirically proved the priority binding consumes the `enter` key event: `Input.Submitted` never
  fires, `app.submitted` stays empty, even though the bound action's body is a pure no-op.
- Added a second spike App (`_NoPriorityBindingApp`) with no App-level `enter` binding at all,
  proving `Input.Submitted` fires normally in that shape — confirming Approach B (dynamic/flag
  binding) is the correct fallback, not merely a theoretical option.
- Confirmed `up`/`down` remain free/safe keys for permanent priority bindings (`Input` has no
  native handling for them), de-risking that part of Plan 04's key-routing design.

## Task Commits

Each task was committed atomically:

1. **Task 1: Spike test — priority `enter` binding vs Input.Submitted fallthrough** - `d8150f9` (test)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified
- `tests/tui/test_palette_keys.py` - Spike Pilot tests proving the enter-binding fallthrough
  question empirically; also confirms up/down are free keys on Input.

## Decisions Made
- **Enter-routing decision: Approach B (dynamic/flag-based enter binding)** — see key-decisions
  above. This is the load-bearing output of this plan and the one Plan 04 must consume.

## Deviations from Plan

None — plan executed exactly as written. The plan itself anticipated either outcome ("If the
assertion PASSES... record Approach A... If Textual consumes the event... invert the test into
the documented fallback... record Approach B"); the empirical result was Approach B, and the test
file was written to assert and document that outcome directly (rather than shipping a test that
asserts the false Approach-A behavior and then inverting it), since the plan explicitly allows
either final shape as long as the committed test is green and states which approach was confirmed.

## Issues Encountered

The initial draft of `test_priority_enter_binding_falls_through_when_palette_closed` asserted the
Approach-A outcome (`app.submitted == ["hello world"]`) per the plan's initial code sketch; it
failed (`app.submitted == []`), which is the expected mechanism for resolving Open Question 1 per
the plan's own stated protocol. The test was then corrected in place to assert the actual
(Approach-B-confirming) result, and a second test (`test_input_submits_without_a_priority_enter_
binding`) was added to positively prove the Approach-B fallback works, rather than only proving
Approach A fails.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 04 (app integration) can now implement the palette's Enter-key routing with evidence: it
must NOT add a permanent `Binding("enter", ..., priority=True)` to `Agent86App.BINDINGS`. Instead
it should track palette-open state and dynamically add the `enter` binding (e.g. via `App.bind`)
only while the palette `OptionList` is visible, removing/unbinding it (or otherwise ensuring no
App-level `enter` binding is active) whenever the palette is closed, so that plain-text turn
submission and typed slash-commands (D-11) keep working unchanged via `Input.Submitted`. No
blockers for Plans 01/03 (parallel, unaffected by this test-only spike).

---
*Phase: 02-command-palette-menus*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: tests/tui/test_palette_keys.py
- FOUND: .planning/phases/02-command-palette-menus/02-02-SUMMARY.md
- FOUND: d8150f9 (commit exists in git log)
