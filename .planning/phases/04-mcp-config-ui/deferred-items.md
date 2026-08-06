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
