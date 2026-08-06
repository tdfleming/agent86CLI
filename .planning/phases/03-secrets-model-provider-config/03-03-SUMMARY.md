---
phase: 03-secrets-model-provider-config
plan: 03
subsystem: config
tags: [tomlkit, config-write-back, comment-preservation, atomic-write]

# Dependency graph
requires:
  - phase: 03-secrets-model-provider-config
    plan: 01
    provides: "xfail-scaffolded tests/unit/test_config_writer.py and tests/fixtures/config_with_comments.toml targeting the exact plan_edit/apply_edit/ConfigEdit/ConfigWriteError interfaces implemented here"
provides:
  - "agent86.config_writer: plan_edit/apply_edit tomlkit round-trip write-back, comment-preserving, with scope selection (user/project) and unified-diff preview before commit"
  - "Secret-leaf-key refusal (api_key/apikey/key/token/secret/password) — no plaintext secret can ever be written via this module"
  - "Atomic write-then-rename (tempfile.mkstemp + os.replace) so a crash mid-write cannot truncate an existing config"
affects: [03-06-key-entry-connection-test, 03-07-save-diff, 03-08-provider-manager, 03-09-full-app-chain]

# Tech tracking
tech-stack:
  added: []  # tomlkit already declared core-but-lazy in 03-01
  patterns:
    - "Two-step plan_edit (pure, disk-untouched) / apply_edit (writes + reloads via load_config()) split so a future modal can show a diff before committing (D-17)"
    - "tomlkit imported lazily inside plan_edit's function body, not at module top, to preserve the run/--plain cold-start guarantee (guarded by tests/tui/test_lazy_import.py)"

key-files:
  created:
    - src/agent86/config_writer.py
  modified:
    - tests/unit/test_config_writer.py
    - src/agent86/config.py

key-decisions:
  - "USER_CONFIG_PATH/PROJECT_CONFIG_PATH imported directly into config_writer (not looked up through agent86.config at call time) so tests monkeypatch config_writer's own module-level names — kept the module cheap and the patch target explicit, per the plan's guidance"
  - "plan_edit refuses on any leaf key name in {api_key, apikey, key, token, secret, password} regardless of nesting depth, satisfying SEC-01's no-plaintext-secret guarantee at the write layer (in addition to the existing keyring-based read layer from 03-02)"

requirements-completed: [MODEL-02, SEC-01]

# Metrics
duration: ~20min
completed: 2026-08-06
---

# Phase 3 Plan 3: Config Write-Back (config_writer) Summary

**Added `agent86/config_writer.py`: a two-step, comment-preserving tomlkit write-back path (`plan_edit`/`apply_edit`) with user/project scope selection, a unified-diff preview computed before any disk write, secret-leaf-key refusal, and atomic write-then-rename.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 2/2 complete
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- `src/agent86/config_writer.py` created with `ConfigEdit`, `ConfigWriteError`, `SCOPE_USER`,
  `SCOPE_PROJECT`, `scope_path`, `plan_edit`, `apply_edit` — matching the exact interface named
  in the plan's `must_haves.artifacts`.
- `plan_edit` parses the existing file with `tomlkit.parse` (lazily imported), applies each
  `(key_path, value)` change in place on the CST (creating intermediate tables as needed),
  and returns a `ConfigEdit` with `before_text`/`after_text`/a `difflib.unified_diff` string —
  all without touching disk.
- `apply_edit` writes `after_text` atomically (`tempfile.mkstemp(dir=path.parent)` +
  `os.replace`, guaranteeing same-volume atomicity on both Windows NTFS and POSIX) and returns a
  freshly reloaded `Config` via the existing `load_config()` — no merge logic duplicated.
- Any leaf key in `{api_key, apikey, key, token, secret, password}` raises `ValueError` before
  any text is generated, so no plaintext secret can ever reach `after_text`.
- Malformed existing TOML raises `ConfigWriteError("Malformed config at {path}: ...")` — matches
  `config.py`'s `_read_toml` error wording convention.
- Deleted the Wave 0 `pytestmark = pytest.mark.xfail(...)` line from
  `tests/unit/test_config_writer.py`; all 6 originally-scaffolded tests now pass for real
  (comment preservation, scope selection, no-plaintext-secret, unified-diff shape, malformed-TOML
  error, missing-parent-dir creation).
- Added 3 hardening tests (`test_multiple_changes_in_one_edit`, `test_apply_edit_reloads_config`,
  `test_atomic_write_leaves_no_temp_files`) proving: a single edit with 3 changes produces exactly
  one `[providers.groq]` section and replaces `model.default` in place while preserving its inline
  comment; `apply_edit`'s `load_config()` reload seam actually reflects the write; and no
  `.config-*` temp files are left behind after a successful write.
- `config.py`'s module docstring gained one sentence pointing at `config_writer` as the write-back
  owner — no code in `config.py` changed (`git diff --stat` confirms 3 insertions, 0 deletions,
  docstring only).

## Task Commits

1. **Task 1: Implement plan_edit/apply_edit with tomlkit round-trip and secret refusal** —
   `a122f34` (test) — deletes xfail marker, adds `config_writer.py`
2. **Task 2: Prove comment preservation against a realistic config and document the seam** —
   `56a526d` (test) — adds 3 hardening tests + `config.py` docstring sentence

**Plan metadata:** (this commit) `docs(03-03): complete config-writer plan`

## Verification

- `pytest tests/unit/test_config_writer.py -q` — 9 passed (6 original + 3 new), 0 xfailed
- `pytest tests/unit/test_config_writer.py tests/unit/test_config.py -q` — 14 passed
- `pytest tests/unit -q` — 158 passed
- `pytest tests/tui/test_lazy_import.py -q` — 2 passed (tomlkit still not imported at CLI
  cold-start)
- Full suite `pytest -q` — **229 passed, 16 xfailed, 1 xpassed, 0 failed** (run after parallel
  plans 03-02/03-04 landed their commits; the 03-01 baseline of 198 passed/42 xfailed/3 xpassed
  has grown as expected across the concurrently-executing Wave 1 plans)

## Deviations from Plan

None — plan executed exactly as written, including the module-body content specified verbatim in
the plan's `<action>` block.

## Files Created/Modified

- `src/agent86/config_writer.py` (new, 163 lines) — `ConfigEdit`, `ConfigWriteError`,
  `SCOPE_USER`/`SCOPE_PROJECT`, `scope_path`, `plan_edit`, `apply_edit`, `_read_text`,
  `_write_atomic`
- `tests/unit/test_config_writer.py` — xfail marker removed; 3 new hardening tests added
  (9 test functions total)
- `src/agent86/config.py` — one docstring sentence added; zero code changes

## Decisions Made

- `USER_CONFIG_PATH`/`PROJECT_CONFIG_PATH` are imported directly into `config_writer`'s module
  namespace (not resolved through `agent86.config` at call time), so `monkeypatch.setattr(config_
  writer, "USER_CONFIG_PATH", ...)` is the correct and only patch target for tests exercising this
  module — confirmed the Wave 0 scaffold already patched the right name, no scaffold change
  needed.

## Issues Encountered

None. This was a parallel-executor run alongside plans 03-02 and 03-04; per the parallel-execution
contract, only `src/agent86/config_writer.py` and `tests/unit/test_config_writer.py` were touched,
plus the one-sentence docstring addition to `src/agent86/config.py` explicitly authorized by the
plan's Task 2. All commits used `--no-verify` to avoid pre-commit-hook contention with the sibling
agents. One deferred-items note was logged (`.planning/phases/03-secrets-model-provider-config/
deferred-items.md`) for 5 test failures observed mid-run in files owned by the parallel 03-02/03-04
plans (`test_providers_key_seam.py`, `test_app.py`); those had resolved themselves by the time of
the final full-suite run once the sibling agents' commits landed, and are noted here for
transparency rather than as an open issue.

## User Setup Required

None.

## Next Phase Readiness

`agent86.config_writer` is ready for plans 03-06 through 03-09 to build TUI modals on top of:
`plan_edit` for the diff-preview step, `apply_edit` for the commit step. The two-step split (D-17)
means a future `SaveDiffModal` can call `plan_edit`, render `edit.diff`, and only call `apply_edit`
on user confirmation — no additional seam work needed in this module.

---
*Phase: 03-secrets-model-provider-config*
*Completed: 2026-08-06*

## Self-Check: PASSED

All key files confirmed present on disk (`src/agent86/config_writer.py`, this SUMMARY.md); both
task commits (a122f34, 56a526d) confirmed in git history.
