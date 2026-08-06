---
phase: 03-secrets-model-provider-config
plan: 01
subsystem: testing
tags: [pytest, keyring, tomlkit, textual-pilot, wave-0-scaffold]

# Dependency graph
requires:
  - phase: 02-command-palette-menus
    provides: "COMMANDS registry, palette chaining hooks (needs_choice='model'/'mode') that plans 03-06..03-09 will wire into"
provides:
  - "keyring>=25.0 and tomlkit>=0.13 declared as core-but-lazy dependencies (installed, not imported at CLI cold-start)"
  - "tests/tui/test_lazy_import.py extended with a keyring/tomlkit import guard (2 passing tests)"
  - "4 backend xfail-scaffolded unit test modules (test_secrets, test_config_writer, test_catalog, test_providers_key_seam) targeting the exact interfaces plans 03-02/03-03/03-04 must implement"
  - "3 TUI xfail-scaffolded Pilot test modules (test_provider_manager, test_connection_test, test_save_diff) targeting the exact modal interfaces plans 03-06/03-07/03-08/03-09 must implement"
  - "6 fixture files (1 hand-commented TOML, 5 catalog JSON payloads) for round-trip and catalog-normalization tests"
affects: [03-02-secrets-seam, 03-03-config-writer, 03-04-catalog, 03-06-key-entry-connection-test, 03-07-save-diff, 03-08-provider-manager, 03-09-full-app-chain]

# Tech tracking
tech-stack:
  added: ["keyring>=25.0 (core-but-lazy)", "tomlkit>=0.13 (core-but-lazy)"]
  patterns:
    - "Wave 0 scaffold pattern: every test module implementing a not-yet-built interface starts with `pytestmark = pytest.mark.xfail(reason=..., strict=False)`; the implementing plan deletes that line as its first act"
    - "Keyring is monkeypatched at the agent86.secrets module boundary via a `_fake_keyring(monkeypatch, ...)` helper that installs a fake module into sys.modules before the lazy `import keyring` runs — never touches the real OS keychain"
    - "TUI Pilot tests copy the `_PickerHost` App shape from tests/tui/test_pickers.py locally per-module (not imported/shared)"

key-files:
  created:
    - tests/unit/test_secrets.py
    - tests/unit/test_config_writer.py
    - tests/unit/test_catalog.py
    - tests/unit/test_providers_key_seam.py
    - tests/tui/test_provider_manager.py
    - tests/tui/test_connection_test.py
    - tests/tui/test_save_diff.py
    - tests/fixtures/config_with_comments.toml
    - tests/fixtures/catalog/openai_models.json
    - tests/fixtures/catalog/groq_models.json
    - tests/fixtures/catalog/openrouter_models.json
    - tests/fixtures/catalog/anthropic_models.json
    - tests/fixtures/catalog/ollama_tags.json
  modified:
    - pyproject.toml
    - tests/tui/test_lazy_import.py

key-decisions:
  - "keyring and tomlkit added directly to [project] dependencies (core-but-lazy), matching the existing textual precedent, rather than to an optional extra — required by D-22"
  - "All Wave 0 scaffold tests use strict=False xfail so an implementing plan that accidentally makes a test pass early (xpass) doesn't fail the suite"

requirements-completed: []  # This Wave 0 plan scaffolds tests for SEC-01/MODEL-01/MODEL-02; full requirement completion happens across plans 03-02..03-09

# Metrics
duration: ~5min (pre-existing work verified; no new implementation needed)
completed: 2026-08-05
---

# Phase 3 Plan 1: Wave 0 Test Scaffolds Summary

**Added keyring/tomlkit as core-but-lazy deps and scaffolded 7 xfail-marked test modules (4 backend, 3 TUI Pilot) plus 6 fixtures, so every later Phase 3 plan's verification command resolves to a real, runnable test instead of `MISSING`.**

## Performance

- **Duration:** ~5 min (this session — verification only)
- **Started:** 2026-08-05 (verification session)
- **Completed:** 2026-08-05
- **Tasks:** 3/3 (all found already complete from prior session, commits 2814da7 / aaa0649 / 875015e dated 2026-07-21)
- **Files modified:** 15 (2 modified, 13 created)

## Accomplishments
- `keyring>=25.0` and `tomlkit>=0.13` declared as core dependencies in `pyproject.toml`, installed, and confirmed absent from `sys.modules` after `import agent86.cli` (lazy-import guard: 2 passing tests)
- 4 backend unit-test modules scaffolded against the exact interfaces plans 03-02/03-03/03-04 must implement (`resolve_api_key`, `ConfigEdit`/`plan_edit`/`apply_edit`, `fetch_catalog` family), all xfail-marked
- 3 TUI Pilot test modules scaffolded against the exact modal interfaces plans 03-06/03-07/03-08/03-09 must implement (`ConnectionTestModal`, `SaveDiffModal`, `ProviderManagerModal`/`CatalogPickerModal`/`KeyEntryModal` chaining), all xfail-marked
- 6 fixture files created: a hand-commented TOML config (proves round-trip comment preservation) and 5 catalog JSON payloads (OpenAI, Groq, OpenRouter, Anthropic, Ollama)
- Full suite verified green: 198 passed, 42 xfailed, 3 xpassed, 0 failed

## Task Commits

All three tasks were committed in a prior session (verified present in git history, dated 2026-07-21):

1. **Task 1: Add keyring + tomlkit deps and extend the lazy-import guard** - `2814da7` (chore)
2. **Task 2: Create backend unit-test scaffolds and fixtures** - `aaa0649` (test)
3. **Task 3: Create TUI Pilot test scaffolds** - `875015e` (test)

No new task commits were required this session — all deliverables verified present and passing against the plan's acceptance criteria.

**Plan metadata:** (this commit) `docs(03-01): complete Wave 0 scaffold plan`

## Files Created/Modified
- `pyproject.toml` - `keyring>=25.0` and `tomlkit>=0.13` added to `[project] dependencies` (core-but-lazy, not in any extras list)
- `tests/tui/test_lazy_import.py` - extended with `test_cli_import_does_not_import_keyring_or_tomlkit`; docstring updated to name all three lazy deps
- `tests/unit/test_secrets.py` - 7 xfail tests for `resolve_api_key`/`keyring_available`/`has_stored_key`/`store_api_key`/`clear_api_key` precedence and silent-degradation, with a local `_fake_keyring` sys.modules-injection helper
- `tests/unit/test_config_writer.py` - 6 xfail tests for `plan_edit`/`apply_edit`/`scope_path` comment-preservation, scope selection, no-plaintext-secret guard, diff shape, malformed-TOML error, missing-parent creation
- `tests/unit/test_catalog.py` - 8 xfail tests for `fetch_catalog`/`fetch_openai_compatible`/`fetch_anthropic`/`fetch_ollama` normalization, auth headers, URL tolerance, failure fallback
- `tests/unit/test_providers_key_seam.py` - 6 xfail tests for keyless-provider isolation, error-message preservation, custom-section-as-keyring-account, and explicit-key-argument precedence over keyring lookups
- `tests/tui/test_provider_manager.py` - 7 xfail Pilot tests for `provider_rows`, `ProviderManagerModal`, `CatalogPickerModal` filter/free-text/empty-catalog, plus full-app chained flows
- `tests/tui/test_connection_test.py` - 5 xfail Pilot tests for `ConnectionTestModal` success/failure/save-anyway/timeout/tiny-probe-request-shape
- `tests/tui/test_save_diff.py` - 4 xfail Pilot tests for `SaveDiffModal` diff-preview accuracy, default scope, scope switching, cancel
- `tests/fixtures/config_with_comments.toml` - hand-commented TOML with inline comment, blank line, and inter-section comment
- `tests/fixtures/catalog/*.json` (5 files) - fixture payloads for OpenAI, Groq, OpenRouter, Anthropic, Ollama catalog endpoints

## Decisions Made
- keyring/tomlkit declared as core (not optional-extra) dependencies to satisfy D-22's core-but-lazy requirement, mirroring the existing `textual` precedent
- All Wave 0 scaffold tests use `xfail(strict=False)` so accidental early passes (xpass) during later implementation don't break the suite — confirmed useful in practice: 3 tests in `test_providers_key_seam.py` already xpass today because the existing provider error-message wording happens to already satisfy the assertions, with no regression risk

## Deviations from Plan

None — plan executed exactly as written in the prior session. This session performed verification only: confirmed all 3 tasks' commits, files, and acceptance criteria from `03-01-PLAN.md` are present and correct, then produced the SUMMARY.md that was never created.

## Issues Encountered
None. All artifacts listed in the plan's `must_haves.artifacts` and `must_haves.key_links` were found on disk and passing their acceptance criteria:
- `grep -n 'keyring>=25.0'` / `'tomlkit>=0.13'` both match inside `[project] dependencies`, not in any extras list
- `pytest tests/tui/test_lazy_import.py -q` reports 2 passed
- All 6 fixture files exist
- All 7 scaffold modules contain `pytestmark = pytest.mark.xfail`
- Full suite (`pytest -q`): 198 passed, 42 xfailed, 3 xpassed, **0 failed**

## User Setup Required
None - no external service configuration required. (Keyring OS-integration and live-catalog verification remain manual-only items per `03-VALIDATION.md`, to be exercised once plans 03-02/03-04 implement the real code paths.)

## Next Phase Readiness
Every automated command in `03-VALIDATION.md`'s per-task verification map now resolves to a real, runnable test function — no `MISSING` entries remain. Plans 03-02 through 03-09 can proceed: each implementing plan's first act is to delete its module's `pytestmark = pytest.mark.xfail` line and make the corresponding scaffolded tests pass for real.

---
*Phase: 03-secrets-model-provider-config*
*Completed: 2026-08-05*

## Self-Check: PASSED

All 10 key files confirmed present on disk; all 3 task commits (2814da7, aaa0649, 875015e) confirmed in git history.
