---
phase: 03-secrets-model-provider-config
plan: 08
subsystem: ui
tags: [textual, tui, modal, provider-config, model-catalog]

# Dependency graph
requires:
  - phase: 03-secrets-model-provider-config
    provides: "agent86.secrets.resolve_api_key/has_stored_key (03-02); agent86.cognitive.catalog.fetch_catalog/CatalogUnavailable (03-04); Wave 0 xfail-scaffolded tests/tui/test_provider_manager.py (03-01)"
provides:
  - "agent86.tui.screens.provider_manager: ProviderRow, provider_rows(cfg), ProviderManagerModal, CatalogPickerModal"
  - "Provider list surface with per-provider key status (key ok / no key / local, no key needed), never showing a key value"
  - "Type-to-filter model catalog picker with case-insensitive substring matching, mirroring the Phase 2 palette interaction"
  - "Free-text fallback path (empty catalog or unmatched filter) that always produces a valid provider:model ref, never a dead end"
affects: [03-09-full-app-chain]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "provider_rows(cfg) mirrors model_choices(cfg) from model_picker.py — a pure function producing view data, tested without a running app"
    - "CatalogPickerModal's on_input_changed rebuilds the OptionList and resets highlighted=0, mirroring Agent86App._sync_palette's filter interaction verbatim"
    - "_catalog_ref/_freetext_ref split avoids double-prefixing provider:model refs whose model segment itself contains a colon (e.g. ollama's llama3.1:8b)"

key-files:
  created:
    - src/agent86/tui/screens/provider_manager.py
  modified:
    - tests/tui/test_provider_manager.py

key-decisions:
  - "Kept the plan's reference implementation essentially verbatim, including the _catalog_ref/_freetext_ref split for colon-containing Ollama model names"
  - "Split the file into two write passes (ProviderRow/provider_rows/ProviderManagerModal, then CatalogPickerModal) so each task gets its own atomic commit, per the parallel-executor's per-task commit protocol"

requirements-completed: [MODEL-01]

# Metrics
duration: ~20min
completed: 2026-08-05
---

# Phase 3 Plan 8: Provider Manager + Catalog Picker Summary

**New `agent86.tui.screens.provider_manager` module: a provider list modal with per-provider key status, and a type-to-filter catalog picker that always falls back to free-text `provider:model` entry — never a dead end.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-08-05 (session start)
- **Completed:** 2026-08-05
- **Tasks:** 2/2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- `ProviderRow` dataclass + `provider_rows(cfg)`: lists every configured provider in config order,
  marks `ollama`/`llamacpp` as `keyless=True`, and derives `has_key` from `resolve_api_key` (env
  then keyring) — matching exactly what a real turn would resolve, never reading or exposing the
  key value itself (D-10).
- `ProviderManagerModal(ModalScreen[ProviderRow | None])`: OptionList of all providers with a
  `(key ok | no key | local, no key needed)` status suffix; selection dismisses with the chosen
  `ProviderRow`, Escape dismisses with `None`.
- `CatalogPickerModal(ModalScreen[str | None])`: an `Input` + `OptionList` pair. Typing narrows
  the option list case-insensitively against both ref and label (mirroring the Phase 2 command
  palette's `_sync_palette` rebuild-and-reset-highlighted pattern). Submitting the filter with an
  empty catalog, or with text that matches nothing, is taken as a free-text model name (D-01) —
  the picker never dead-ends.
- Colon-containing Ollama model refs (e.g. `llama3.1:8b`) are handled correctly: catalog
  selections always prefix with `{provider}:`, while free-text input only skips the prefix when
  the text already starts with `{provider}:` — proven by `test_ollama_model_with_colon_is_prefixed`
  plus a `ModelRef.parse` round-trip check.
- Wave 0 module-level `pytestmark = pytest.mark.xfail(...)` removed from
  `tests/tui/test_provider_manager.py`; per-function `@pytest.mark.xfail(reason="chain wiring
  lands in plan 03-09", strict=False)` added to exactly the 3 tests plan 03-09 owns
  (`test_no_key_provider_chains_to_key_entry`, `test_save_anyway_override`,
  `test_switch_is_immediate_persist_is_separate`).
- 6 new tests added: `test_catalog_filter_is_case_insensitive`,
  `test_catalog_filter_no_match_submits_as_free_text`, `test_catalog_escape_returns_none`,
  `test_ollama_model_with_colon_is_prefixed` (per plan), plus the two Wave 0 scaffold tests for
  Task 1 already covered `provider_rows`/`ProviderManagerModal` behavior.
- Full suite green: 262 passed, 2 xfailed, 1 xpassed (a plan-03-09-owned test that currently
  passes ahead of schedule because it only needs `provider_rows`/`ProviderManagerModal` to reach
  its first assertion — harmless under `strict=False`, matches the same pattern already
  documented in 03-01/03-02's summaries), 0 failed.

## Task Commits

1. **Task 1: ProviderRow + provider_rows + ProviderManagerModal** - `dea385e` (feat)
2. **Task 2: CatalogPickerModal — type-to-filter list with free-text fallback** - `689f0da` (feat)

**Plan metadata:** (this commit) `docs(03-08): complete provider manager plan`

## Files Created/Modified

- `src/agent86/tui/screens/provider_manager.py` - new module: `ProviderRow`/`provider_rows`/
  `ProviderManagerModal`/`CatalogPickerModal`, exported via `__all__`.
- `tests/tui/test_provider_manager.py` - Wave 0 module-level xfail removed; per-function xfail
  added to the 3 plan-03-09 chain tests; 4 new tests added for Task 2's filter/fallback/escape/
  colon-handling behavior.

## Decisions Made

- Followed the plan's reference implementation essentially verbatim, including the
  `_catalog_ref`/`_freetext_ref` split that avoids double-prefixing colon-containing Ollama model
  names.
- Split the single-file implementation into two separate write+commit passes (rather than writing
  the whole file once) so Task 1 and Task 2 each get their own atomic commit per the per-task
  commit protocol, even though the plan presented both as one file.
- In `test_ollama_model_with_colon_is_prefixed`, explicitly focused `#catalog-list` before
  pressing Enter (the modal auto-focuses `#catalog-filter` on mount per D-03/D-19, so an
  unfocused Enter press would submit the empty filter Input instead of selecting the highlighted
  option) — this is test-only, not a behavior change.

## Deviations from Plan

None affecting behavior or scope. One incidental cross-agent git-index interaction is worth
recording (see Issues Encountered).

## Issues Encountered

While running in parallel with plans 03-05/03-06/03-07, a concurrent agent's `git add` for its
own untracked file (`src/agent86/tui/screens/connection_test.py`, owned by plan 03-06) landed in
the shared git index between this plan's `git add <files>` and `git commit` for Task 2, so that
file was swept into commit `689f0da` alongside this plan's own two files. The file's content is
untouched by this plan and the commit is not destructive — it simply means plan 03-06's file
appears in this plan's Task 2 commit rather than its own. No action taken beyond noting it here,
since resetting/rewriting a shared index mid-parallel-execution risks discarding a concurrent
agent's in-progress work. Flagging for the orchestrator in case 03-06's own commit for that file
comes back empty.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

`ProviderRow`, `provider_rows`, `ProviderManagerModal`, and `CatalogPickerModal` are ready for
plan 03-09 to chain together: selecting a no-key `ProviderRow` from `ProviderManagerModal` into
`KeyEntryModal` (03-06), then `CatalogPickerModal` sourced from `fetch_catalog`/`CatalogUnavailable`
(03-04) for the model choice, then `SaveDiffModal` (03-07) for the write-back. The 3 chain tests
in `tests/tui/test_provider_manager.py` remain (loosely) xfailed for 03-09 to un-mark. No
blockers.

---
*Phase: 03-secrets-model-provider-config*
*Completed: 2026-08-05*

## Self-Check: PASSED

`src/agent86/tui/screens/provider_manager.py` confirmed present; commits `dea385e` and `689f0da`
confirmed in git history.
