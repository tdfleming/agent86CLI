---
phase: 04-mcp-config-ui
plan: 02
subsystem: secrets-config
tags: [secrets, keyring, tomlkit, mcp, config-writer]

# Dependency graph
requires:
  - phase: 03-secrets-model-provider-config
    provides: "resolve_api_key (env-first-then-keyring), _KEY_SHAPES, plan_edit/apply_edit tomlkit round-trip, _FORBIDDEN_LEAF_KEYS guard"
provides:
  - "secrets.find_var_refs / expand_var_refs / MissingSecretRef — ${VAR} reference resolution for MCP server configs"
  - "config_writer.DELETE sentinel — whole-key-path deletion composable with ordinary set changes in one plan_edit call"
  - "config_writer._is_var_ref — SEC-01 guard exception letting a ${VAR} form through a secret-shaped leaf key while a literal (even with a decoy ${notreal} appended) is refused"
affects: [04-03, 04-04, 04-05, 04-06, 04-07, 04-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Secret precedence lives in exactly one place: expand_var_refs calls resolve_api_key(name, name) rather than re-deriving env-first-then-keyring logic"
    - "config_writer stays the single seam for both writing and deleting config — DELETE is a sentinel value in the same changes list, not a second function/parameter"
    - "tomlkit trailing-trivia re-homing: a hand-written comment attached to a deleted table's own body (tomlkit quirk — comments between two table headers parse as trailing content of the preceding table) is popped and re-appended to the parent container instead of being silently discarded"

key-files:
  created: []
  modified:
    - src/agent86/secrets.py
    - src/agent86/config_writer.py
    - tests/unit/test_secrets.py
    - tests/unit/test_config_writer.py

key-decisions:
  - "expand_var_refs reuses resolve_api_key(name, name) verbatim rather than reimplementing env/keyring precedence, so SEC-01's one precedence rule can never drift between the API-key path and the MCP ${VAR} path"
  - "DELETE is a distinct sentinel object (_Delete instance), not None or a string, so plan_edit can distinguish 'delete this key' from 'set this key to a falsy value' via identity comparison"
  - "authorization added to _FORBIDDEN_LEAF_KEYS with a ${VAR}-reference carve-out (_is_var_ref), closing the SEC-01 gap where an MCP server's headers.Authorization could carry a literal bearer token straight into config.toml"

patterns-established:
  - "Pattern: any new secret-shaped leaf key added to _FORBIDDEN_LEAF_KEYS must be paired with the _is_var_ref exception check, not a separate allow-list"

requirements-completed: [MCP-01, SEC-01]

# Metrics
duration: ~20min
completed: 2026-08-06
---

# Phase 04 Plan 02: Secret References + Config Deletion Summary

**`${VAR}` secret reference resolver (`secrets.py`) and a `DELETE` sentinel plus `authorization` guard hole closure (`config_writer.py`) — the two pure-backend seams every later Phase 4 plan composes.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-08-06T05:37:18Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- `find_var_refs`/`expand_var_refs`/`MissingSecretRef` added to `secrets.py`: `${VAR}` references in MCP server config resolve env-first-then-keyring by variable name, reusing `resolve_api_key(name, name)` with zero duplicated precedence logic; unresolved references raise `MissingSecretRef` carrying `.var_name` for the caller to turn into a masked key prompt.
- `DELETE` sentinel added to `config_writer.py`: `plan_edit` can now remove a whole `[mcp.servers.NAME]` table via `(["mcp","servers","name"], DELETE)` in the same call as ordinary key sets — one function, one changes list, one diff, no new `plan_delete`/`deletions=` API surface.
- `_FORBIDDEN_LEAF_KEYS` gained `"authorization"`, closing the SEC-01 hole where a literal bearer token under `headers.Authorization` (or any secret-shaped `env.TOKEN` value) passed the guard entirely; `_is_var_ref` lets the `${VAR}` form through while still rejecting a key-shaped literal with a decoy `${notreal}` appended.
- Fixed a tomlkit-specific correctness gap discovered while making the delete scaffold pass for real (see Deviations): a hand-written comment between two table headers is parsed as trailing content of the *preceding* table, so a naive `del node[key]` silently discarded a sibling's comment. `_apply_delete` now pops that trailing trivia and re-appends it to the parent container before deleting.

## Task Commits

Each task was committed atomically:

1. **Task 1: ${VAR} reference resolver in secrets.py** - `cb3c8e5` (feat)
2. **Task 2: DELETE sentinel + SEC-01 authorization guard in config_writer.py** - `9a529db` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/agent86/secrets.py` - `_VAR_REF_RE`, `MissingSecretRef`, `find_var_refs`, `expand_var_refs`; `__all__` extended
- `src/agent86/config_writer.py` - `_Delete`/`DELETE`, `_is_var_ref`, `_apply_delete` (+ `_pop_trailing_trivia` helper), `_FORBIDDEN_LEAF_KEYS` extended, `plan_edit`'s per-change loop updated; `__all__` extended
- `tests/unit/test_secrets.py` - removed `xfail` markers from the 6 Wave 0 `-k var_ref` scaffolds (now real passing tests)
- `tests/unit/test_config_writer.py` - removed `xfail` markers from the 7 Wave 0 `-k delete`/`-k forbidden_var_ref` scaffolds (now real passing tests)

## Decisions Made
- `expand_var_refs` deliberately calls `resolve_api_key(name, name)` rather than writing a second env-then-keyring implementation — see `patterns-established` above.
- `DELETE` is a dedicated sentinel class instance (not `None`/a string) so `plan_edit` can use identity comparison (`value is DELETE`) and never confuse it with a legitimate falsy config value.
- Left the empty-`[mcp.servers]`-table cosmetic debt from deleting the last server unaddressed, per the plan's explicit RESEARCH Open Question 2 acceptance.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Trailing comment silently dropped by a naive DELETE implementation**
- **Found during:** Task 2, running `test_delete_removes_a_server_table` for the first time after removing its `xfail` marker
- **Issue:** The plan's `_apply_delete` reference implementation (a straightforward walk-then-`del`) passed the "does the table disappear" assertions but failed `assert "# keep me" in edit.after_text`. Root cause: tomlkit parses a comment written between two table headers (`[mcp.servers.foo]` ... `# keep me` ... `[mcp.servers.bar]`) as a trailing, key-`None` body item *inside* the preceding table (`foo`)'s own container — not as a standalone item at the parent level. Deleting `foo` outright therefore deleted the comment that visually belongs to `bar` along with it.
- **Fix:** Added `_pop_trailing_trivia(table)`, which pops trailing `Whitespace`/`Comment` items (key `is None`) off the end of the target table's own tomlkit container before the delete, then `_apply_delete` re-appends them to the parent container via `Container._raw_append(None, item)` after the delete. `_raw_append` with a `None` key never touches the container's `_map`, so this is safe to do after the keyed delete without corrupting index bookkeeping used by later `node[key] = value` set-operations in the same `plan_edit` call.
- **Files modified:** `src/agent86/config_writer.py`
- **Verification:** `test_delete_removes_a_server_table` and `test_delete_and_set_in_one_edit` (which chains a DELETE and a set in one `plan_edit` call, exercising the map-bookkeeping path right after a delete) both pass; full `tests/unit/test_config_writer.py` — 16 passed, 0 failed.
- **Committed in:** `9a529db` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix, within the current task's own new code — no scope creep)
**Impact on plan:** Necessary for `plan_edit`'s DELETE support to actually preserve comments as the plan's own `must_haves` truths require ("config_writer can delete a whole table... in the same plan_edit call"); the plan's reference `_apply_delete` snippet was a correct starting point but under-specified this tomlkit trivia-ownership quirk.

## Issues Encountered
- A transient `NoMatches: No nodes match '#catalog-filter'` failure appeared in `tests/tui/test_app.py::test_catalog_failure_yields_empty_entries_with_error` during one full-suite run, traced to `src/agent86/tui/screens/provider_manager.py` — a file outside this plan's scope, being concurrently edited by a sibling parallel-wave agent. Logged to `.planning/phases/04-mcp-config-ui/deferred-items.md` rather than fixed (scope boundary). A second full-suite run immediately after was clean (370 passed, 0 failed, 35 xfailed), confirming it was a mid-edit race, not a regression from this plan.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `secrets.py` and `config_writer.py` now expose the full seam (`find_var_refs`/`expand_var_refs`/`MissingSecretRef`, `DELETE`/`_is_var_ref`) that the MCP client, connection-test flow, and TUI server-editor modals in the remaining Phase 4 plans (04-03..04-08) are expected to compose directly, per the plan's `key_links` contract.
- No blockers. Full suite green: 370 passed, 35 xfailed (unrelated Wave 0 scaffolds for later plans), 0 failed.

---
*Phase: 04-mcp-config-ui*
*Completed: 2026-08-06*

## Self-Check: PASSED

- FOUND src/agent86/secrets.py
- FOUND src/agent86/config_writer.py
- FOUND commit cb3c8e5
- FOUND commit 9a529db
- FOUND find_var_refs in secrets.py
- FOUND `DELETE = _Delete()` in config_writer.py
