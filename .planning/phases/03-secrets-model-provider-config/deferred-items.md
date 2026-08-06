# Deferred Items — Phase 03

## From plan 03-03 (config_writer)

- `tests/unit/test_providers_key_seam.py` (4 failures) and `tests/tui/test_app.py::test_turn_streams_and_footer_goes_live_then_idle` (1 failure)
  are out of scope for 03-03 — owned by parallel plans 03-02/03-04. Observed during full-suite run
  after implementing config_writer.py; not caused by config_writer.py changes (verified no overlap
  in files_modified). Not fixed here per parallel-execution scope boundary.
