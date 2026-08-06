---
phase: 04-mcp-config-ui
plan: 05
subsystem: ui
tags: [textual, mcp, pydantic, config, tui-modal]

# Dependency graph
requires:
  - phase: 04-mcp-config-ui
    provides: "04-01 xfail-marked test scaffolds (acceptance contract); 04-03 MCPServerConfig.enabled field"
provides:
  - "src/agent86/tui/screens/mcp_manager.py: MCPServerRow/mcp_server_rows, MCPManagerAction, MCPServerDraft, parse_kv_list, parse_server_json, build_manual_config, MCPManagerModal, MCPServerFormModal"
affects: ["04-06", "04-07", "04-08"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure-function-plus-modal shape mirrored from provider_manager.py (row dataclass, pure *_rows(cfg) function, ModalScreen[T] with explicit dismiss on every path)"
    - "Validator messages caught via pydantic.ValidationError and surfaced verbatim (never re-derived) — _first_validator_message strips the 'Value error, ' wrapper prefix"
    - "Inline error rendering + Continue-disable pattern mirrored from SaveDiffModal._refresh"

key-files:
  created:
    - src/agent86/tui/screens/mcp_manager.py
  modified:
    - tests/tui/test_mcp_manager.py
    - .planning/phases/04-mcp-config-ui/deferred-items.md

key-decisions:
  - "One combined implementation file/commit for all three tasks (row layer, list modal, form modal) rather than three separate task commits — the tasks are tightly coupled within a single new module built and TDD'd together in one pass; splitting after the fact would be artificial."
  - "Fixed a genuine test-scaffold bug: `error.renderable` does not exist on Textual 8.2.8's Static widget (attribute was removed/renamed upstream); replaced with `error.render()`, matching the exact pattern already used in tests/tui/test_save_diff.py. This is a real API mismatch, not a weakening of intent — the assertion still checks the rendered error text is non-empty / contains 'already'."
  - "Rewrote the one known-awkward ternary assertion in test_form_shows_validator_error_inline_and_disables_continue per plan instruction, into an unambiguous two-line form."

requirements-completed: [MCP-01]

duration: 45min
completed: 2026-08-06
---

# Phase 04 Plan 05: MCP Manager List + Form Modals Summary

**Built `mcp_manager.py` — a pure row/parser layer (mcp_server_rows, parse_server_json, build_manual_config, parse_kv_list) plus `MCPManagerModal` and `MCPServerFormModal`, giving `/config mcp` a full add/edit/remove/toggle surface with inline, verbatim validator-message feedback.**

## Performance

- **Duration:** ~45 min
- **Tasks:** 3 (all committed together — see Decisions)
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- `mcp_server_rows(cfg)` lists every configured server with name/transport/endpoint/enabled-status, byte-identical endpoint rendering to `agent86 mcp list` — opening the manager never spawns a subprocess or opens a transport (D-08), confirmed by a Pilot test that monkeypatches `subprocess.Popen` and `mcp_client._open_transport` to raise if called.
- `parse_server_json` accepts both the bare object and the `{"mcpServers": {...}}` / `{"servers": {...}}` (VS Code alias) wrapped README shapes, with the wrapped name winning over `name_hint`; malformed JSON and structurally-invalid configs both raise `ValueError` (JSON decoder message or the config validator's own message, verbatim).
- `build_manual_config` shlex-splits a single command-line string into `command`/`args`, and only honours an explicit `transport` choice when `url` is set (D-06).
- `MCPManagerModal` lists servers plus two peer "add" options (`+ Add from JSON`, `+ Add manually`, D-01), dispatches edit/remove/toggle via Enter/`d`/`t`, and dismisses `None` on Escape; `d`/`t` on an add row are no-ops.
- `MCPServerFormModal` serves add-from-JSON, add-manually, and edit (D-01/D-07) from one form: every keystroke re-validates via `_revalidate()`, which renders the validator's message inline under `#mcp-form-error` and disables `#mcp-form-continue` on any error — the typed input is never discarded. A name collision (against `existing_names`, excluding `original_name`) blocks with `"A server named '<name>' already exists. Pick another name."` (D-04).

## Task Commits

All three tasks landed in a single commit — see Decisions for rationale (one new file, built and TDD'd together in one pass rather than three separately-revertible states):

1. **Tasks 1-3: Pure row/parse layer + MCPManagerModal + MCPServerFormModal** - `fc57c7a` (feat)

**Plan metadata:** (this commit, following)

## Files Created/Modified
- `src/agent86/tui/screens/mcp_manager.py` - New module: `MCPServerRow`/`mcp_server_rows`, `MCPManagerAction`, `MCPServerDraft`, `parse_kv_list`, `parse_server_json`, `build_manual_config`, `MCPManagerModal`, `MCPServerFormModal`
- `tests/tui/test_mcp_manager.py` - Removed the Wave 0 module-level `pytestmark`; added explicit per-test `xfail` on the two 04-08 chain tests; fixed two `.renderable` → `.render()` scaffold bugs; rewrote one ambiguous ternary assertion
- `.planning/phases/04-mcp-config-ui/deferred-items.md` - Logged a still-reproducing, pre-existing, out-of-scope `CatalogPickerModal`/`#catalog-filter` test-order flake (not caused by this plan)

## Decisions Made
- See `key-decisions` in frontmatter (single combined commit; `.renderable` → `.render()` fix; ternary rewrite).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `Static.renderable` does not exist on installed Textual (8.2.8)**
- **Found during:** Task 3 verification (`pytest tests/tui/test_mcp_manager.py -q`)
- **Issue:** Two Wave 0 scaffold assertions (`test_form_shows_validator_error_inline_and_disables_continue`, `test_form_name_collision_blocks`) read `error.renderable`, which raises `AttributeError` on this Textual version — `Static` in 8.2.8 exposes `.render()` (returns the rich renderable) but not a `.renderable` property. This is a real API mismatch blocking task completion, not a change of test intent.
- **Fix:** Replaced `str(error.renderable)` with `str(error.render())` in both assertions — the exact pattern already used three times in `tests/tui/test_save_diff.py` for the identical `Static`-error-widget check.
- **Files modified:** `tests/tui/test_mcp_manager.py`
- **Verification:** `pytest tests/tui/test_mcp_manager.py -q` — 17 passed, 2 xfailed (0 failed)
- **Committed in:** `fc57c7a`

---

**Total deviations:** 1 auto-fixed (1 blocking), plus the plan-instructed ternary rewrite (not a deviation — explicitly authorized in the plan's `<prior_context>`).
**Impact on plan:** Necessary correctness fix for the installed Textual version; no scope creep, no weakening of assertion intent.

## Issues Encountered
- A full-suite `pytest -q` run intermittently fails exactly one test outside this plan's file scope — either `tests/tui/test_provider_manager.py::test_switch_is_immediate_persist_is_separate` or `tests/tui/test_app.py::test_catalog_failure_yields_empty_entries_with_error`, depending on which other test files are collected. Both pass individually and the failure traces into `CatalogPickerModal.on_mount` (`provider_manager.py`, untouched by this plan). Documented as a pre-existing, test-order-dependent flake in `deferred-items.md` (also flagged during plan 04-02's run) rather than fixed here (scope boundary — the failing file/tests are not this plan's files).
- A separate, expected transient failure was observed in `tests/unit/test_config.py::test_build_mcp_filters_disabled_servers`/`test_build_mcp_returns_none_when_all_disabled` during a `tests/unit tests/integration` run — this file is explicitly owned by a concurrently-running sibling agent per this plan's `<parallel_execution>` instructions (mid-edit state), not a defect in this plan's work.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `mcp_manager.py`'s `MCPManagerModal`/`MCPServerFormModal` are ready for plan 04-08 to wire into the `/config mcp` command (`needs_choice="config_mcp"`) and the full-app chain — the two chain tests (`test_config_mcp_command_is_in_registry`, `test_config_mcp_opens_manager_modal_in_full_app`) remain explicitly `xfail`-marked for that plan to close.
- Plans 04-06/04-07 (whatever they wire — e.g. remove/toggle persistence, connection test) can call `mcp_server_rows`, `parse_server_json`, `build_manual_config` directly; all are pure and fully unit-tested.
- `tests/tui/test_mcp_manager.py -q` is green (17 passed, 2 xfailed); `tests/tui/ -q` is green (109 passed, 8 xfailed). Full-suite `pytest -q` has one pre-existing, out-of-scope, order-dependent flake unrelated to this plan's files (see Issues Encountered / deferred-items.md).

---
*Phase: 04-mcp-config-ui*
*Completed: 2026-08-06*

## Self-Check: PASSED
- FOUND: src/agent86/tui/screens/mcp_manager.py
- FOUND: fc57c7a
