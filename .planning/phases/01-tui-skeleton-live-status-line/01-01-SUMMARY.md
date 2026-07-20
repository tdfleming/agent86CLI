---
phase: 01-tui-skeleton-live-status-line
plan: 01
subsystem: ui
tags: [textual, threading, worker-thread, message-passing, approval-gate]

# Dependency graph
requires: []
provides:
  - "src/agent86/tui/ package tree (textual-free __init__ files)"
  - "textual>=1.0 as a core-but-lazy pyproject.toml dependency"
  - "agent86.tui.messages: TurnDelta, ToolAnnounce, ApprovalRequest, TurnDone, TurnError"
  - "agent86.tui.turn_bridge.run_turn_worker + make_approval_cb (Textual-app-independent thread bridge)"
  - "tests/tui/ Wave 0 scaffolding: fake_harness/raising_harness fixtures, turn_bridge tests, lazy-import guard"
affects: [01-02, 01-03, 01-04, 01-05]

# Tech tracking
tech-stack:
  added: ["textual>=1.0 (core dep, lazy-imported)"]
  patterns:
    - "Worker thread posts Message subclasses (post_message, thread-safe) instead of a manual queue.Queue poll loop"
    - "threading.Event + shared result box for approval-blocking, mirroring ui/repl.py::_run_turn_rich exactly"
    - "Stub harness fixtures reuse the real ApprovalGate as the prompt seam rather than mocking it"

key-files:
  created:
    - src/agent86/tui/__init__.py
    - src/agent86/tui/widgets/__init__.py
    - src/agent86/tui/screens/__init__.py
    - src/agent86/tui/messages.py
    - src/agent86/tui/turn_bridge.py
    - tests/tui/__init__.py
    - tests/tui/conftest.py
    - tests/tui/test_turn_bridge.py
    - tests/tui/test_lazy_import.py
  modified:
    - pyproject.toml

key-decisions:
  - "textual added to [project].dependencies (core), not an extra — matches the CONTEXT.md 'core-but-lazy' decision"
  - "turn_bridge.py imports only agent86.tui.messages and agent86.ui.repl._tool_label — no textual widget/App imports, keeping it unit-testable without a running app"
  - "Approval blocking uses threading.Event + result box (not push_screen_wait), per RESEARCH.md Open Question 2 recommendation"

patterns-established:
  - "Pattern: worker thread body (run_turn_worker) takes a plain `post` callable so it's decoupled from any concrete App, enabling headless threading tests"

requirements-completed: [TUI-01, TUI-05]

duration: 20min
completed: 2026-07-20
---

# Phase 1 Plan 1: TUI Package Skeleton + Turn Bridge Summary

**Textual-app-independent worker/UI bridge (run_turn_worker + make_approval_cb) that streams ordered Message subclasses and blocks tool approval on a threading.Event, proven by headless unit tests before any Textual widgets exist.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-20T02:49:00Z (approx)
- **Completed:** 2026-07-20T03:03:56Z
- **Tasks:** 3
- **Files modified:** 10 (1 modified, 9 created)

## Accomplishments
- `textual>=1.0` added as a core-but-lazy dependency; the `agent86/tui/` package tree exists with textual-free `__init__.py` files at every level
- Five `Message` subclasses (`TurnDelta`, `ToolAnnounce`, `ApprovalRequest`, `TurnDone`, `TurnError`) define the worker→app contract
- `run_turn_worker` + `make_approval_cb` in `turn_bridge.py` reproduce `_run_turn_rich`'s proven Event/box approval-blocking pattern using Textual message posting instead of a manual `queue.Queue`
- Wave 0 test scaffolding (`tests/tui/`) unit-tests the bridge in isolation (ordered streaming, approval-blocking, error propagation) and guards the lazy-import constraint in a subprocess

## Task Commits

Each task was committed atomically:

1. **Task 1: Add textual dependency, create tui package skeleton, and define Message subclasses** - `6afff81` (feat)
2. **Task 2: Implement turn_bridge (run_turn_worker + make_approval_cb)** - `6f7a71b` (feat)
3. **Task 3: Wave 0 scaffolding — tests/tui package, stub harness fixture, turn_bridge tests, lazy-import guard** - `a15a284` (test)

**Plan metadata:** (this commit, see below)

## Files Created/Modified
- `pyproject.toml` - added `textual>=1.0` to core `[project].dependencies` with a lazy-import comment
- `src/agent86/tui/__init__.py`, `src/agent86/tui/widgets/__init__.py`, `src/agent86/tui/screens/__init__.py` - empty, textual-free package markers
- `src/agent86/tui/messages.py` - `TurnDelta`, `ToolAnnounce`, `ApprovalRequest`, `TurnDone`, `TurnError`
- `src/agent86/tui/turn_bridge.py` - `run_turn_worker`, `make_approval_cb`
- `tests/tui/__init__.py` - empty test package marker
- `tests/tui/conftest.py` - `fake_harness`/`raising_harness`/`fake_state` fixtures using the real `ApprovalGate`
- `tests/tui/test_turn_bridge.py` - `test_streams_deltas_in_order`, `test_approval_blocks_until_resolved`, `test_error_becomes_TurnError`
- `tests/tui/test_lazy_import.py` - `test_cli_import_does_not_import_textual`

## Decisions Made
- Followed CONTEXT.md/RESEARCH.md exactly: Event+box approval blocking over `push_screen_wait` (avoids an undocumented worker-context edge case), `textual` as a core dep with lazy import enforced only at the entry-path level (not yet reached in this plan — `turn_bridge.py`/`messages.py` themselves import `textual.message` at module level, which is fine since nothing in `cli.py`'s import graph reaches `agent86.tui` yet).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The turn bridge and Message vocabulary are ready for Plan 01-02 (widgets) and 01-03 (app shell) to consume without re-deriving the approval/streaming contract.
- Wave 0 test scaffolding (`fake_harness`, `raising_harness`) is ready for reuse in later TUI test files.
- No blockers. `pytest -q` (full suite, 162 tests) and the lazy-import smoke check both pass.

---
*Phase: 01-tui-skeleton-live-status-line*
*Completed: 2026-07-20*

## Self-Check: PASSED

All 9 created files verified present on disk; all 3 task commit hashes (6afff81, 6f7a71b, a15a284) verified in git log.
