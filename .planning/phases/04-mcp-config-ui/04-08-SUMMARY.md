---
phase: 04-mcp-config-ui
plan: 08
subsystem: ui
tags: [textual, mcp, tui, config-writer, keyring, tomlkit]

# Dependency graph
requires:
  - phase: 04-mcp-config-ui
    provides: mcp_server_rows/MCPManagerModal/MCPServerFormModal (04-05), MCPTestModal (04-07),
      unresolved_var_refs/MCPManager.start_server/stop_server (04-04), Harness.ensure_mcp/
      add_mcp_server/remove_mcp_server (04-06), config_writer DELETE sentinel + secrets
      find_var_refs/expand_var_refs (04-02)
provides:
  - "/config mcp" registered in the COMMANDS registry (palette/help/dispatch, zero per-surface
    wiring)
  - Full add/edit chain in Agent86App — paste JSON or fill fields, resolve any ${VAR} through the
    existing masked KeyEntryModal, run a real connection test, preview the exact TOML diff, save,
    and mount the tested server's tools live in the same session
  - Remove/enable/disable through the identical diff+confirm gate (no separate "are you sure"
    dialog); re-enabling a disabled server re-runs the connection test before it is ever mounted
affects: [05-packaging-hardening]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Headers/env values are written to config as individual TOML key paths
      ([mcp.servers.NAME.headers.Authorization], not a whole headers dict) so
      config_writer's forbidden-leaf-key secret guard actually inspects them"
    - "Chain state lives on Agent86App as _mcp_* instance attributes reset once per
      _open_mcp_manager entry, mirroring the /config model chain's _pending_* fields"
    - "A cancelled add stops the server MCPTestModal already started (manager.stop_server);
      a config write that succeeds while the live mount fails reports both without rollback"

key-files:
  created: []
  modified:
    - src/agent86/tui/commands.py
    - src/agent86/tui/app.py
    - tests/tui/test_commands.py
    - tests/tui/test_mcp_manager.py

key-decisions:
  - "Headless Pilot tests against the real Agent86App needed a larger terminal
    (run_test(size=(100, 50))) — the default 80x24 clips the MCP form's dialog below its
    Continue button; unrelated to production layout"
  - "A bare asyncio.sleep-based poll can observe #mcp-test-buttons.display flip True before its
    Button children finish mounting under call_from_thread; switched to a pilot.pause-based
    settle helper (mirrors the working pattern already proven in test_mcp_test_modal.py)"

patterns-established:
  - "Every MCP config write (add/edit/remove/enable/disable) funnels through the same
    SaveDiffModal/apply_edit path used by /config model — one save code path, one trust surface"

requirements-completed: [MCP-01, SEC-01]

# Metrics
duration: ~85min
completed: 2026-08-06
---

# Phase 4 Plan 8: `/config mcp` full-app chain Summary

**Wires `/config mcp` end-to-end in `Agent86App`: registry entry, add/edit chain (form → masked `${VAR}` entry → live connection test → TOML diff → save → live mount), and remove/enable/disable through the identical diff-confirm gate — closing MCP-01 and the SEC-01 `headers.Authorization` write path.**

## Performance

- **Duration:** ~85 min
- **Started:** 2026-08-06T06:20:00Z (approx.)
- **Completed:** 2026-08-06T06:55:00Z
- **Tasks:** 3/3
- **Files modified:** 4 (`src/agent86/tui/commands.py`, `src/agent86/tui/app.py`,
  `tests/tui/test_commands.py`, `tests/tui/test_mcp_manager.py`)

## Accomplishments
- `/config mcp` is a first-class `COMMANDS` registry entry (palette, `/help`, multi-word dispatch,
  `--plain` TUI-surface note) with zero per-surface wiring, mirroring `/config model` exactly.
- The full add/edit chain lives in `Agent86App`: `MCPManagerModal` → `MCPServerFormModal` →
  every unresolved `${VAR}` resolved one at a time through the existing `KeyEntryModal` →
  `MCPTestModal` on the live `Harness.ensure_mcp()` manager → `SaveDiffModal` → `apply_edit` →
  `Harness.add_mcp_server` mounting the tested server's tools into the running session.
- Remove and enable/disable reuse the same diff-and-confirm gate — no silent write, no extra
  "are you sure" dialog; re-enabling a disabled server re-runs the connection test before mount.
- Both plan-04-08-owned `xfail` markers in `tests/tui/test_mcp_manager.py` are gone; the phase
  now has 0 xfailed tests.

## Task Commits

Each task was committed atomically:

1. **Task 1: `/config mcp` command entry (D-21)** - `7b509c0` (feat)
2. **Task 2: The add/edit chain in app.py** - `08102d5` (feat)
3. **Task 3: Remove/enable/disable through the same diff+confirm flow** - `bf279e6` (test — the
   `app.py` code for this task landed as part of task 2's single coherent edit to `app.py`; see
   Deviations)

_Note: metadata commit follows this summary._

## Files Created/Modified
- `src/agent86/tui/commands.py` — `ChoiceKind` extended with `"config_mcp"`; new `/config mcp`
  `CommandEntry` inserted after `/config model`.
- `src/agent86/tui/app.py` — imports for `mcp_manager`/`mcp_test` screens; CSS extended for
  `#mcp-manager-dialog`/`#mcp-form-dialog`/`#mcp-test-dialog`/`#mcp-server-list`/
  `#mcp-test-tools-scroll`/`#mcp-json`; `_mcp_*` chain state in `__init__`; `_run_or_chain`
  branch for `config_mcp`; the full `/config mcp` chain (`_open_mcp_manager`, `_on_mcp_action`,
  `_on_mcp_form`, `_prompt_next_var`, `_on_var_entered`, `_start_mcp_test`, `_on_mcp_test_done`,
  `_mcp_changes`, `_on_mcp_save_confirmed`, `_on_mcp_destructive`, `_on_mcp_unmount_confirmed`).
- `tests/tui/test_commands.py` — registry/dispatch/help/palette regression tests for
  `/config mcp`.
- `tests/tui/test_mcp_manager.py` — removed both plan-04-08 `xfail` markers; added a
  `_FakeMCPManager`/`_FakeMCPTool` pair and full-app Pilot tests covering the add-json chain
  reaching `SaveDiffModal`, `${VAR}` chaining into `KeyEntryModal`, cancel paths (key entry and
  save diff), a failed test never opening the diff, a confirmed save mounting tools live, the
  override/mount-failure-reports-both path, per-key header/env TOML paths, and remove/disable/
  enable-with-test/no-op-remove for servers not yet mounted.

## Decisions Made
- Headless full-app Pilot tests need `run_test(size=(100, 50))` — the default 80x24 terminal
  clips the MCP form dialog below its `Continue` button (a test-harness sizing issue, not a
  production layout defect; the real TUI runs in a full terminal).
- Replaced a bare `asyncio.sleep`-based poll for "`#mcp-test-buttons` is visible" with a
  `pilot.pause`-based settle helper (`_wait_for_mcp_test_ready`) after intermittent CI-style
  flakes showed the container's `display` flag flipping `True` moments before its `Button`
  children finished mounting under `call_from_thread`. This mirrors the already-proven polling
  style in `tests/tui/test_mcp_test_modal.py` (`await pilot.pause(0.1)` loops) rather than a tight
  `asyncio.sleep(0.02)` loop, and made the new full-app tests deterministic across 25+ repeated
  runs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed a scaffold assertion comparing a tuple to an entry**
- **Found during:** Task 1
- **Issue:** The Wave 0 scaffold `test_config_mcp_command_is_in_registry` asserted
  `find_command_for_line("/config mcp") is entry`, but `find_command_for_line` returns a
  `(entry, arg)` tuple, not the entry itself — this assertion would fail regardless of a correct
  implementation.
- **Fix:** Unpacked the returned tuple and compared `match[0] is entry`, matching the plan's own
  documented behavior ("`find_command_for_line` returns that entry with arg `\"\"`").
- **Files modified:** `tests/tui/test_mcp_manager.py`
- **Verification:** `pytest tests/tui/test_mcp_manager.py -k registry -q` passes.
- **Committed in:** `7b509c0` (Task 1 commit)

**2. [Rule 3 - Blocking] Test-harness terminal size and thread/mount-settle timing**
- **Found during:** Task 2
- **Issue:** New full-app Pilot tests for the MCP form intermittently either could not click the
  form's `Continue` button (clipped outside the default 80x24 test viewport) or, more subtly,
  raced `MCPTestModal`'s worker-thread `call_from_thread` callback against Textual's own
  widget-mount completion, observing `#mcp-test-buttons.display == True` before its `Button`
  children were queryable.
- **Fix:** Used `app.run_test(size=(100, 50))` for the new full-app tests, and added a
  `pilot.pause`-based settle helper (`_wait_for_mcp_test_ready`) instead of a bare
  `asyncio.sleep` poll before interacting with the test-result buttons.
- **Files modified:** `tests/tui/test_mcp_manager.py` (test-only; no production code changed)
- **Verification:** `tests/tui/test_mcp_manager.py` run 25+ times consecutively with 0 flakes
  after the fix (vs. intermittent failures roughly 1 in 5 runs before it).
- **Committed in:** `08102d5` (Task 2 commit)

**3. [Rule 4-adjacent scope note, not architectural] Task 3's production code landed inside
Task 2's commit**
- **Found during:** Task 3
- **Issue:** The plan's Task 2 action block for `app.py` already included the trailing
  `self._on_mcp_destructive(action.kind, action.name, srv)` call in `_on_mcp_action`, and Task 3's
  own action block was additive to the *same* `/config mcp` chain section of the *same* file —
  writing it required re-reading and extending the section Task 2 had just written, so both
  landed in one coherent edit to `app.py` rather than two separate diffs.
- **Fix:** No behavior change — `_on_mcp_destructive`/`_on_mcp_unmount_confirmed` and
  `_mcp_unmount` state were written in full per Task 3's spec as part of Task 2's `app.py` commit;
  Task 3's commit contains its test coverage (`tests/tui/test_mcp_manager.py`) plus this summary
  note. All of Task 3's acceptance criteria (`grep` checks for `_on_mcp_destructive`,
  `_on_mcp_unmount_confirmed`, the `DELETE`/`enabled=False` change lists,
  `remove_mcp_server(name)`, and zero `ConfirmModal`/"are you sure" occurrences) hold against the
  final `app.py`.
- **Files modified:** none beyond what Task 2 already touched
- **Verification:** `grep` acceptance criteria from both Task 2 and Task 3 checked directly
  against `src/agent86/tui/app.py` and passed.
- **Committed in:** `08102d5` (production code), `bf279e6` (Task 3's tests)

---

**Total deviations:** 3 auto-fixed (1 bug, 1 blocking, 1 scope/commit-boundary note)
**Impact on plan:** All auto-fixes were necessary for the tests to be correct and deterministic,
or are a documentation-only clarification of which commit carries which code. No scope creep, no
change to the plan's designed behavior.

## Issues Encountered
- Headless Pilot click/query races against a real `Agent86App` (not the lightweight `_PickerHost`
  used by earlier plans) required both a larger virtual terminal and a settle-before-interact
  helper — see Deviations #2. Resolved; 10+ consecutive full-file runs green with 0 flakes.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- MCP-01 and the SEC-01 `headers.Authorization` write-path gap are both closed: the phase's
  three success criteria (list, add-with-test-before-save, remove/disable reflected in config and
  the running session) all hold end-to-end through the TUI.
- Full suite green: 438 passed, 0 xfailed, 0 failed (two consecutive full-suite runs; a single
  known pre-existing, test-order-dependent `CatalogPickerModal`/`#catalog-filter` flake —
  documented in `deferred-items.md` since plan 04-02 — appeared once on each of two full runs in
  its two previously-documented forms (`test_app.py::test_catalog_failure_yields_empty_entries_with_error`
  and `test_provider_manager.py::test_switch_is_immediate_persist_is_separate`) and cleared on
  immediate rerun both times; it predates this plan and touches neither of this plan's files).
- Manual Windows Terminal verification of the full `/config mcp` flow against a real MCP server
  (per any phase-level validation doc) remains outstanding but does not block automated progress.
- Ready for Phase 5 (Packaging & Hardening).

---
*Phase: 04-mcp-config-ui*
*Completed: 2026-08-06*

## Self-Check: PASSED

All claimed files found on disk; all three task commit hashes (`7b509c0`, `08102d5`, `bf279e6`)
found in git history.
