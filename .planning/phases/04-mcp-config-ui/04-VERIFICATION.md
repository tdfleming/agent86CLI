---
phase: 04-mcp-config-ui
verified: 2026-08-06T07:04:28Z
status: passed
score: 8/8 must-haves verified
---

# Phase 4: MCP Config UI Verification Report

**Phase Goal:** An in-app MCP modal to list, add, remove, and enable/disable servers, validating
a server's connection and listing its tools before saving.
**Verified:** 2026-08-06T07:04:28Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The modal lists configured MCP servers with transport and status | ✓ VERIFIED | `mcp_server_rows(cfg)` + `MCPManagerModal` in `src/agent86/tui/screens/mcp_manager.py`; wired via `app.py:_open_mcp_manager` → `self.push_screen(MCPManagerModal(mcp_server_rows(self.repl.cfg)), ...)`; `agent86 mcp list` CLI also shows an `Enabled` column (`cli.py:494`) |
| 2 | Adding a server (stdio/sse/http) runs a real connection test that starts it and enumerates its tools *before* the entry is written to config | ✓ VERIFIED | `MCPTestModal._run_test` calls `manager.start_server(...)` on a worker thread (real subprocess/session, not a stub) and only after `MCPTestOutcome.ok` does `app.py:_on_mcp_test_done` push `SaveDiffModal` → `apply_edit`. Real-stdio regression test `tests/integration/test_mcp_client.py::test_per_server_start_lists_real_tools` passes with the `mcp` extra installed |
| 3 | Removing or disabling a server updates config non-destructively (diff+confirm) and reflects immediately in the running app | ✓ VERIFIED | `app.py:_on_mcp_destructive` builds a `DELETE`-sentinel or `enabled=False` change list, routes through `SaveDiffModal`, then `_on_mcp_unmount_confirmed` calls `apply_edit` followed by `self.repl.harness.remove_mcp_server(name)`, which unregisters live tools and calls `mcp.stop_server(name)` |
| 4 | Stopping one MCP server does not tear down another server's session (D-23, task-per-server) | ✓ VERIFIED | `test_independent_teardown_leaves_other_server_intact` in `tests/integration/test_mcp_client.py` spawns two real stdio servers via `live_mcp_server.py`, stops one, asserts no "cancel scope"/"different task" `RuntimeError`, and confirms the other server still answers. Ran directly (not mocked): **PASSED** in this environment (the `mcp` extra is installed and exercised, not skipped) |
| 5 | A server added through the UI becomes callable in the current session without a restart (core milestone value) | ✓ VERIFIED | `Harness.ensure_mcp` / `add_mcp_server` / `remove_mcp_server` (`src/agent86/orchestration/loop.py:149-197`) mutate the live `MCPManager` and `ToolRegistry` directly; `app.py:_on_mcp_save_confirmed` calls `add_mcp_server` right after the config write succeeds, and `_build_request` reads `registry.specs()` fresh every turn, so the new tool is available on the very next turn |
| 6 | A ${VAR} secret reference resolves env-first then OS keyring, and an unresolved one prompts the user rather than silently connecting with an empty credential | ✓ VERIFIED | `secrets.py:expand_var_refs`/`find_var_refs`/`MissingSecretRef`; `app.py:_prompt_next_var` calls `unresolved_var_refs` and chains into `KeyEntryModal` before starting the test |
| 7 | A literal secret under a forbidden leaf key (e.g. `headers.Authorization`) is rejected by config_writer, but its `${VAR}` form is accepted (SEC-01 hole closure) | ✓ VERIFIED | `config_writer.py:_FORBIDDEN_LEAF_KEYS` includes `"authorization"`; `_is_var_ref` exception path lets `${VAR}` values through; `app.py:_mcp_changes` deliberately writes each header/env value as its own key path so the guard actually sees the leaf key |
| 8 | Cold-start (`agent86 run` / `--plain`) still does not import Textual/keyring/tomlkit | ✓ VERIFIED | `tests/tui/test_lazy_import.py` — 2 passed |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/agent86/secrets.py` | `find_var_refs`/`expand_var_refs`/`MissingSecretRef`, `redact` | ✓ VERIFIED | All present, substantive (not stubs), exercised by 147 passing tests |
| `src/agent86/config_writer.py` | `DELETE` sentinel, `_FORBIDDEN_LEAF_KEYS` incl. `authorization`, `${VAR}` exception | ✓ VERIFIED | Present and wired into `app.py` removal/disable/add flows |
| `src/agent86/config.py` | `MCPServerConfig.enabled: bool = True` | ✓ VERIFIED | Present; round-trips through hand-edited TOML |
| `src/agent86/tools/registry.py` | `ToolRegistry.unregister` | ✓ VERIFIED | Present, used by `Harness.remove_mcp_server` |
| `src/agent86/tools/mcp_client.py` | Task-per-server `MCPManager` (`start_server`/`stop_server`/`tools_for`), `${VAR}` expansion, `enabled` filter | ✓ VERIFIED | Real-stdio integration tests pass; independent teardown confirmed |
| `src/agent86/tui/screens/mcp_manager.py` | `MCPManagerModal`, `MCPServerFormModal`, pure parsers (`parse_server_json`, `build_manual_config`, `mcp_server_rows`) | ✓ VERIFIED | Present, imported and used by `app.py` |
| `src/agent86/tui/screens/mcp_test.py` | `MCPTestModal`, `MCPTestOutcome` (30s worker-thread test, tool enumeration, Save anyway) | ✓ VERIFIED | Present, imported and used by `app.py` |
| `src/agent86/orchestration/loop.py` | `Harness.ensure_mcp`/`add_mcp_server`/`remove_mcp_server` | ✓ VERIFIED | Present, substantive, called from `app.py` |
| `src/agent86/tui/commands.py` + `src/agent86/tui/app.py` | `/config mcp` registry entry + full app chain | ✓ VERIFIED | `needs_choice="config_mcp"` routes to `_open_mcp_manager`; full chain (form → var prompt → test → diff → save → live mount/unmount) present in `app.py` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `config_writer.py` | `secrets.py` | lazy import of `find_var_refs` in `_is_var_ref` | ✓ WIRED | Confirmed by grep and by passing `test_config_writer.py` cases exercising the `${VAR}` exception |
| `mcp_client.py` | `secrets.py` | `expand_var_refs` at connect time | ✓ WIRED | `_resolve_server_secrets`-style expansion confirmed via passing `test_mcp.py`/integration tests |
| `mcp_manager.py` | `agent86.config.MCPServerConfig` | validator errors surfaced verbatim | ✓ WIRED | `test_mcp_manager.py::test_form_shows_validator_error_inline_and_disables_continue` passes |
| `loop.py` | `tools/registry.py` | `registry.unregister` per unmounted tool | ✓ WIRED | `remove_mcp_server` loop confirmed in source |
| `loop.py` | `tools/mcp_client.py` | `mcp.tools_for` / `mcp.stop_server` | ✓ WIRED | Confirmed in source and by `test_loop.py` |
| `app.py` | `mcp_manager.MCPManagerModal` | `needs_choice == "config_mcp"` | ✓ WIRED | `_run_or_chain`/dispatch confirmed at `app.py:278-279` |
| `app.py` | `key_entry.KeyEntryModal` | unresolved `${VAR}` loop before test | ✓ WIRED | `_prompt_next_var`/`_on_var_entered` confirmed |
| `app.py` | `loop.Harness.add_mcp_server` | live mount after save confirmed | ✓ WIRED | `_on_mcp_save_confirmed` line 562 |
| `app.py` | `config_writer.DELETE` | removal change list to `SaveDiffModal` | ✓ WIRED | `_on_mcp_destructive` line 588 |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|--------------|--------|----------|
| MCP-01 | 04-01, 04-02, 04-03, 04-04, 04-05, 04-06, 04-07, 04-08 | List/add/remove/enable-disable MCP servers from the app, with a connection test that validates and enumerates tools before saving | ✓ SATISFIED (see traceability note below) | End-to-end chain confirmed live: list (`MCPManagerModal`), add-with-pre-save-test (`MCPTestModal` → `start_server` → tool enumeration → `SaveDiffModal` → `apply_edit` → `add_mcp_server`), remove/disable (`SaveDiffModal` → `apply_edit` → `remove_mcp_server`). All clauses independently verified against source, not SUMMARY claims |
| SEC-01 | 04-01, 04-02, 04-08 | Config never contains a plaintext secret; the SEC-01 hole in MCP headers is closed | ✓ SATISFIED | `_FORBIDDEN_LEAF_KEYS` includes `"authorization"`; `${VAR}` exception lets references through while literals are refused; `app.py:_mcp_changes` writes each header/env value under its own leaf key so the guard actually inspects it; `redact()` used in `MCPTestModal._finish` so a failed test never echoes a secret |

**Traceability note (adjudicated per instructions):** `requirements mark-complete MCP-01` was invoked
prematurely during execution — as early as plan 04-01, which shipped only xfail scaffolds with no
implementation. At that point the checkbox in `.planning/REQUIREMENTS.md` did not reflect reality.
However, verifying the **current, final state of the codebase** (not the plan-by-plan history of
when the checkbox was flipped): every clause of MCP-01 — list, add, remove, enable/disable, and a
pre-save connection test that starts the server for real and enumerates its tools — is now
genuinely and fully implemented and wired end to end, confirmed by direct source inspection and by
running the real-stdio integration tests (not mocks) in this environment. The checkbox is
premature-but-now-accurate. No gap is opened for this; it is noted here as a process finding for
future phases (mark-complete should not run until the requirement is actually met, even if the
final state later catches up).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | none found | — | Scanned all phase-modified source files (`secrets.py`, `config_writer.py`, `config.py`, `registry.py`, `mcp_client.py`, `mcp_manager.py`, `mcp_test.py`, `loop.py`, `commands.py`, `app.py`) for TODO/FIXME/placeholder/empty-handler/hardcoded-empty patterns; none matched a real anti-pattern (one incidental substring match was inside a docstring example, not a stub) |

### Test-Scaffold Integrity Check (contract-first approach)

- Full suite: **437 passed, 1 failed, 0 xfailed** (re-run twice; the 1 failure is the pre-existing,
  documented, order-dependent `test_catalog_failure_yields_empty_entries_with_error` flake in
  `provider_manager.py`/`CatalogPickerModal`, logged in `deferred-items.md` from plans 04-02 and
  04-05, unrelated to any file this phase's plans own for implementation; confirmed to pass in
  isolation).
- `grep -rn "xfail" tests/` — zero live xfail markers remain; the only hits are historical comments
  describing why collection needs to succeed, in `test_connection_test.py` and `test_mcp_manager.py`.
- `git log -p` review of every scaffold-to-implementation diff across
  `tests/tui/test_mcp_manager.py`, `tests/tui/test_mcp_test_modal.py`,
  `tests/integration/test_mcp_client.py`, and the phase's unit test files found exactly two
  assertion edits, both legitimate and matching the authorized descriptions:
  - `str(error.renderable)` → `str(error.render())` (Textual 8.2.8 `Static` API change, applied
    consistently to both occurrences in `test_mcp_manager.py`)
  - a malformed inline ternary `assert "{bad" in json_input.text if hasattr(...) else json_input.value`
    (which as written only conditionally executed the assertion) rewritten as a proper two-line
    `typed_text = ... ; assert "{bad" in typed_text` — a correctness fix, not a weakening
  - No other assertion was removed, loosened, or had its target value changed to match buggy
    behavior; scaffolds were turned green by real implementation.
- `mcp` extra dependency is present in this environment (`mcp>=1.0` listed as a project dev
  dependency, "exercise the live MCP transport test... in CI" per `pyproject.toml` comment), so
  `test_independent_teardown_leaves_other_server_intact` and its siblings ran for real (not
  `skipif`-skipped) and passed, confirming genuine real-stdio subprocess coverage rather than an
  untested guard.

### Human Verification Required

None. All success criteria and must-haves were verifiable by direct source inspection and by
running the real (non-mocked, non-skipped) automated test suite, including the real-stdio D-23
integration test.

### Gaps Summary

No gaps found. All 8 derived observable truths verified against the actual codebase (not
SUMMARY.md claims); all required artifacts exist, are substantive, and are wired; all key links
confirmed; both MCP-01 and SEC-01 are genuinely satisfied end to end as of the current codebase
state. One process finding is noted (premature `mark-complete MCP-01` during execution) but does
not block the phase — the final state is accurate. The one failing test in the full suite is a
pre-existing, documented, out-of-scope flake unrelated to this phase's ownership.

---

*Verified: 2026-08-06T07:04:28Z*
*Verifier: Claude (gsd-verifier)*
