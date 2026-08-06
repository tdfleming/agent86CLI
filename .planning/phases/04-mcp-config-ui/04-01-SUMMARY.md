---
phase: 04-mcp-config-ui
plan: 01
subsystem: tests
tags: [scaffold, xfail, mcp, tui, pilot]
requires: []
provides:
  - "xfail test contract for plans 04-02..04-08"
  - "D-23 independent-teardown regression guard"
affects:
  - tests/unit/test_secrets.py
  - tests/unit/test_config_writer.py
  - tests/unit/test_config.py
  - tests/unit/test_mcp.py
  - tests/integration/test_mcp_client.py
  - tests/tui/test_mcp_manager.py
  - tests/tui/test_mcp_test_modal.py
tech-stack:
  added: []
  patterns:
    - "Per-test @pytest.mark.xfail when appending to a module with existing passing tests"
    - "Module-level pytestmark xfail only for wholly-new scaffold modules"
    - "In-body imports of not-yet-existing modules so collection never errors"
    - "_HAS_FASTMCP boolean + skipif instead of module-level importorskip"
key-files:
  created:
    - tests/tui/test_mcp_manager.py
    - tests/tui/test_mcp_test_modal.py
  modified:
    - tests/unit/test_secrets.py
    - tests/unit/test_config_writer.py
    - tests/unit/test_config.py
    - tests/unit/test_mcp.py
    - tests/integration/test_mcp_client.py
key-decisions:
  - "Deferred every scaffold import into the test body rather than guarding at module top, so a missing implementation module produces an xfail rather than a collection error"
  - "Guarded the real-stdio integration tests with a module-level _HAS_FASTMCP boolean plus per-test skipif, never a module-level pytest.importorskip, so the existing mock-only tests in test_mcp_client.py keep running without the mcp extra"
requirements-completed: [MCP-01, SEC-01]
duration: resumed across sessions
completed: 2026-08-06
---

# Phase 04 Plan 01: Wave 0 Test Scaffolds Summary

Contract-first xfail scaffolds covering every automated verify command in `04-VALIDATION.md` —
25 net-new TUI Pilot tests, 5 real-stdio integration tests, and 21 backend unit tests written
against the exact interfaces plans 04-02..04-08 must implement.

**Tasks:** 3 | **Files:** 7 (2 created, 5 extended) | **Commits:** 3

| Task | Commit | What landed |
|------|--------|-------------|
| 1 | `01023b6` | Backend unit scaffolds — `${VAR}` expansion, `config_writer` DELETE + forbidden-leaf guard, `MCPServerConfig.enabled`, `ToolRegistry.unregister`, `MCPManager` per-server lifecycle |
| 2 | `a402012` | Integration scaffolds — real stdio spawn of `live_mcp_server.py`, per-server start/call, **D-23 independent-teardown guard**, clean close after partial stop, start-failure isolation |
| 3 | `31a718d` | TUI Pilot scaffolds — `MCPManagerModal`/`MCPServerFormModal` (D-01..D-08), `MCPTestModal` (D-18/D-19/D-20), `/config mcp` registry + full-app chain (D-21) |

## Verification

- `pytest -q` → **353 passed, 51 xfailed, 1 xpassed, 0 failed**
- `pytest tests/tui/test_lazy_import.py -q` → 2 passed (cold-start guard untouched)
- `pytest tests/unit/... -q` → 36 passed, 21 xfailed
- `pytest tests/tui/test_mcp_manager.py tests/tui/test_mcp_test_modal.py -q` → 25 xfailed, 0 failed
- `git diff --stat src/` → empty (no implementation code written, as required)

Every `-k` keyword named in `04-VALIDATION.md` now collects at least one test:
`var_ref` (4), `delete` (3), `forbidden_var_ref` (4), `unregister` (2), `per_server` (2),
`independent_teardown` (1), `list` (3).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

**Pre-existing flake (not a regression):** `tests/tui/test_app.py::test_catalog_failure_yields_empty_entries_with_error`
failed once during a full-suite run with `NoMatches: No nodes match '#catalog-filter' on
CatalogPickerModal()` raised from `provider_manager.py:126` `on_mount`. It passes in isolation and
passed on two consecutive full-suite reruns afterwards, and the suite is equally green with the new
scaffold files removed. This is a Textual mount/query timing race in `CatalogPickerModal.on_mount`
that predates this plan — worth a hardening pass (query the Input after `on_mount` settles, or
guard the `.focus()`), but out of scope here.

**Execution note:** Task 1 was committed by an earlier interrupted session (`01023b6`); Task 2's
work was present in the working tree but uncommitted. Both were verified against their acceptance
criteria before this session committed Task 2 and executed Task 3.

## Next Phase Readiness

Ready for wave 1 — plans 04-02 (`secrets.py` / `config_writer.py`) and 04-03
(`MCPServerConfig.enabled` / `ToolRegistry.unregister`) both have their full acceptance surface
already written and xfailing. Turning each xfail green is the definition of done.
