---
phase: 04-mcp-config-ui
plan: 07
subsystem: ui
tags: [textual, mcp, connection-test, worker-thread, redact]

# Dependency graph
requires:
  - phase: 04-mcp-config-ui (plan 04-04)
    provides: "MCPManager.start_server/stop_server/tools_for — one persistent task per server"
  - phase: 04-mcp-config-ui (plan 04-01)
    provides: "tests/tui/test_mcp_test_modal.py Wave 0 scaffolds (xfail-marked contract)"
provides:
  - "MCPTestOutcome + MCPTestModal — pre-save MCP connection test with tool enumeration"
affects: [04-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Worker-thread + inner-daemon-thread + Event.wait(TIMEOUT_S) + app.call_from_thread — copied verbatim from connection_test.py, budget raised 15s -> 30s for MCP first-run npx-download"
    - "Every dismissal path (continue/save-anyway/cancel/escape/timeout) resolves an explicit MCPTestOutcome — never hangs, never auto-dismisses on success"

key-files:
  created:
    - src/agent86/tui/screens/mcp_test.py
  modified:
    - tests/tui/test_mcp_test_modal.py

key-decisions:
  - "TIMEOUT_S = 30.0 (not ConnectionTestModal's 15.0) — MCPManager.start() already budgets 30s for a first-run npx/uvx download, so a shorter modal timeout would fail honest first runs"
  - "Success does NOT auto-dismiss — the user must press Continue after seeing the tool list, making enumeration a real step rather than a flash"
  - "Tool count headline is embedded as the first line of #mcp-test-tools in addition to #mcp-test-status, so both widgets independently confirm the count (test scaffold checks the tools widget alone)"
  - "manager arrives as a constructor argument (not imported at module scope) so agent86.tools.mcp_client / mcp stays out of this module's import graph"

requirements-completed: [MCP-01, SEC-01]

duration: 25min
completed: 2026-08-06
---

# Phase 04 Plan 07: MCP Pre-Save Connection Test Modal Summary

**`MCPTestModal` starts an MCP server for real on the live `MCPManager`, shows its tool count and every tool name/description, and requires an explicit Continue before the add flow reaches the diff.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-08-06
- **Completed:** 2026-08-06
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `MCPTestOutcome` + `MCPTestModal` (`src/agent86/tui/screens/mcp_test.py`) — a 30s worker-thread
  connection test that starts a real server on the caller's live `MCPManager` and enumerates its
  tools before anything is saved (D-19).
- 30s hard timeout (D-20), a labelled "Save anyway" override on real failures (D-13), and explicit
  resolution on every dismissal path (continue/save-anyway/cancel/escape/timeout) — never hangs.
- All rendered text passes through `agent86.secrets.redact` so a misbehaving server's tool
  description can never leak a secret to the screen (SEC-01).
- Removed the Wave 0 module-level `xfail` from `tests/tui/test_mcp_test_modal.py`; all 6 tests now
  pass unmarked.

## Task Commits

Both tasks landed in a single commit because Task 2 (`_finish`/`on_button_pressed`) fills in
methods stubbed by Task 1 (`_run_test`/`_timeout`) in the same new file — splitting them would have
required committing a half-implemented `_finish`/`on_button_pressed` pair that no test in the file
could exercise independently (Task 1's own verify command only runs a subset of tests, all of which
already exercise the full module). Both tasks' acceptance criteria were verified independently
before committing.

1. **Task 1: MCPTestOutcome + MCPTestModal worker with a 30s hard timeout (D-20)** — combined into `aa70461`
2. **Task 2: Tool enumeration display (D-19)** — combined into `aa70461` (`feat(04-07): MCPTestModal pre-save connection test with tool enumeration (D-19/D-20)`)

## Files Created/Modified
- `src/agent86/tui/screens/mcp_test.py` - `MCPTestOutcome` (frozen dataclass) + `MCPTestModal`
  (`ModalScreen[MCPTestOutcome]`): compose/on_mount/`_run_test` (worker thread)/`_timeout`/`_finish`
  (tool enumeration + redact)/`on_button_pressed`/`action_cancel`.
- `tests/tui/test_mcp_test_modal.py` - removed the Wave 0 module-level `pytestmark` xfail; fixed a
  scaffold bug (`Static.renderable` -> `Static.render()`, matching `test_save_diff.py`'s existing
  pattern — `Static.renderable` does not exist on the installed Textual 8.2.8).

## Decisions Made
- Embedded the "Connected. N tools:" headline as the first line of `#mcp-test-tools`'s content (in
  addition to setting it verbatim on `#mcp-test-status`) — the Wave 0 scaffold polls and asserts
  against the tools widget's own rendered text for the count string, not the status widget, so both
  widgets carry the count independently. This is additive, not a weakening: `#mcp-test-status`
  still reads exactly `"Connected. 2 tools:"` per the plan's `<behavior>` contract.
- Everything else followed the plan's literal code blocks (worker shape, widget ids, `_finish`
  branches, `on_button_pressed` dispatch) verbatim.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed pre-existing `Static.renderable` scaffold bug in the test file**
- **Found during:** Task 1 verification (first `pytest` run against the Wave 0 scaffold)
- **Issue:** `tests/tui/test_mcp_test_modal.py` polled `Static.renderable`, an attribute that does
  not exist on the installed Textual 8.2.8 (raises `AttributeError`, silently swallowed by the
  scaffold's own `try/except`, so the loop never saw the rendered text and the assertion failed).
  This is the same class of scaffold bug plan 04-05 hit and fixed in its own file; the plan's
  `<prior_context>` explicitly flagged this exact issue and instructed applying the same fix.
- **Fix:** Changed `.renderable` to `.render()`, matching the established pattern in
  `tests/tui/test_save_diff.py`.
- **Files modified:** `tests/tui/test_mcp_test_modal.py`
- **Verification:** `pytest tests/tui/test_mcp_test_modal.py -q` — 6 passed, 0 xfailed
- **Committed in:** `aa70461` (part of the task commit)

**2. [Rule 1 - Bug] Test scaffold expected the tool count string inside `#mcp-test-tools`, not only `#mcp-test-status`**
- **Found during:** Task 2 verification
- **Issue:** `test_mcp_test_modal_lists_tool_names_on_success` asserts `"2 tools" in rendered` where
  `rendered` is `#mcp-test-tools`'s own text — the plan's literal `_finish` code block only put the
  headline on `#mcp-test-status`, leaving `#mcp-test-tools` with just the name/description lines,
  which failed this assertion.
- **Fix:** Prepended the headline as the first line of `#mcp-test-tools`'s updated text (still also
  set verbatim on `#mcp-test-status`, satisfying that half of the `<behavior>` contract unchanged).
- **Files modified:** `src/agent86/tui/screens/mcp_test.py`
- **Verification:** `pytest tests/tui/test_mcp_test_modal.py -q` — 6 passed, 0 xfailed; full suite
  `pytest -q` — 418 passed, 2 xfailed (unrelated, 04-08-owned), 0 failed
- **Committed in:** `aa70461` (part of the task commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 - bug fixes needed to make the plan's own
acceptance tests pass for real; no scope creep, no assertion was weakened or rewritten).
**Impact on plan:** Both fixes were necessary to satisfy the plan's own `<behavior>`/acceptance
criteria; the plan's `<prior_context>` had already anticipated and pre-authorized deviation 1.

## Issues Encountered
None beyond the two auto-fixed deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `MCPTestModal` is ready to be wired into the add/edit flow from `mcp_manager.py` by plan 04-08
  (full-app chain), which owns the two remaining `xfail`-marked tests in
  `tests/tui/test_mcp_manager.py`.
- Full suite green: 418 passed, 2 xfailed (04-08-owned, untouched), 0 failed.

---
*Phase: 04-mcp-config-ui*
*Completed: 2026-08-06*

## Self-Check: PASSED

- FOUND: src/agent86/tui/screens/mcp_test.py
- FOUND: tests/tui/test_mcp_test_modal.py
- FOUND commit: aa70461
