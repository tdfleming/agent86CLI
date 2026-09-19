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

## Resolved

- **RESOLVED in 67a79ca** (`fix(tui): stop CatalogPickerModal.on_mount raising NoMatches during
  shutdown`) — both items above are the same bug. The guess recorded in plan 04-05 was right: a
  widget-mount race, not a shared-state leak between Pilot apps.

  Root cause: `CatalogPickerModal` is pushed from `Agent86App.on_catalog_ready`, i.e. off the back
  of a catalog-fetch worker, so the push can land at any moment — the app's shutdown window
  included. Once `App._running` flips False, `App._register` deliberately returns no widgets
  ("prevent awaiting of the widget tasks"), so `mount_all` stops awaiting the composed children
  and Textual dispatches `Mount` with the dialog still empty. The unguarded
  `query_one("#catalog-filter")` in `on_mount` then raised, Textual routed it to
  `App._handle_exception`, and `run_test()` re-raised it from whichever test's teardown happened
  to be in flight — which is why the failure wandered between `test_provider_manager.py` and
  `test_app.py` with collection order.

  That also explains the order-dependence that made it look like a test artifact: the trigger was
  `test_switch_is_immediate_persist_is_separate` selecting a provider that has a key on a
  developer machine, which kicked off a *live* `fetch_catalog` network call whose result landed at
  an unpredictable moment. 67a79ca stubs it (dropping that file from ~60s to under 4s) and makes
  `_focus_filter` query instead of `query_one`.

  Follow-up: 2854d19 applies the same guard to the five sibling modals with the same exposure
  (`key_entry`, `connection_test`, `mcp_test`, `mcp_manager`, `save_diff`), each with a regression
  test that reproduces the identical `NoMatches` against the unguarded code.
