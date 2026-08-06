# Deferred Items — Phase 04 (MCP Config UI)

## From plan 04-02

- `tests/tui/test_app.py::test_catalog_failure_yields_empty_entries_with_error` failed during
  the full-suite run at the end of plan 04-02, with a `NoMatches: No nodes match '#catalog-filter'`
  raised from `src/agent86/tui/screens/provider_manager.py:126` (`CatalogPickerModal.on_mount`).
  `provider_manager.py` is outside this plan's file scope (`secrets.py`/`config_writer.py` and
  their unit tests only) and was being concurrently edited by a sibling parallel-wave agent at
  the time this suite ran — most likely a transient mid-edit artifact, not something introduced
  by this plan. Not fixed here (Rule: scope boundary — only auto-fix issues directly caused by
  the current task's changes). Re-run `pytest tests/tui/test_app.py -q` after all Wave 1 agents
  land to confirm whether it's still failing; if so, file as a real bug against whichever plan
  owns `provider_manager.py`.

## From plan 04-05

- Same `CatalogPickerModal.on_mount` / `#catalog-filter` `NoMatches` flake still reproduces during
  a full-suite run at the end of plan 04-05 (parallel Wave 2), manifesting as either
  `tests/tui/test_provider_manager.py::test_switch_is_immediate_persist_is_separate` or
  `tests/tui/test_app.py::test_catalog_failure_yields_empty_entries_with_error` failing depending
  on collection order/count — both pass individually and in isolated `--ignore` reruns. Neither
  `provider_manager.py` nor `test_provider_manager.py`/`test_app.py` were touched by this plan
  (files modified were `src/agent86/tui/screens/mcp_manager.py` and
  `tests/tui/test_mcp_manager.py` only). Confirmed test-order-dependent, not caused by this
  plan's changes: `pytest -q` (full suite, includes `test_mcp_manager.py`) fails
  `test_provider_manager.py::test_switch_is_immediate_persist_is_separate`;
  `pytest -q --ignore=tests/tui/test_mcp_manager.py` fails a *different* test
  (`test_app.py::test_catalog_failure_yields_empty_entries_with_error`) instead. Still not fixed
  here (scope boundary) — needs a real fix (likely a `CatalogPickerModal` widget-mount race or
  shared-state leak between Pilot apps) filed against whichever plan next touches
  `provider_manager.py`.
