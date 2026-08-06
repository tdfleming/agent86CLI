# Deferred Items — Phase 03

## From plan 03-03 (config_writer)

- `tests/unit/test_providers_key_seam.py` (4 failures) and `tests/tui/test_app.py::test_turn_streams_and_footer_goes_live_then_idle` (1 failure)
  are out of scope for 03-03 — owned by parallel plans 03-02/03-04. Observed during full-suite run
  after implementing config_writer.py; not caused by config_writer.py changes (verified no overlap
  in files_modified). Not fixed here per parallel-execution scope boundary.

## From plan 03-07 (save diff modal)

- `tests/tui/test_connection_test.py` (5 failures, `ModuleNotFoundError: agent86.tui.screens.connection_test`)
  and `tests/tui/test_provider_manager.py::test_catalog_filter_narrows` /
  `::test_catalog_empty_falls_back_to_free_text` (2 failures, `ImportError: CatalogPickerModal`) —
  out of scope for 03-07, owned by parallel plans 03-06 (connection_test.py) and 03-08
  (provider_manager.py), which were still in progress at the time of this full-suite run. Not
  caused by save_diff.py changes (verified no overlap in files_modified). `pytest
  tests/tui/test_save_diff.py -q` reports 6 passed, 0 xfailed, on its own.
