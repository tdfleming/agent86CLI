---
phase: 04-mcp-config-ui
plan: 04
subsystem: mcp-client
tags: [mcp, asyncio, anyio, keyring, secrets, config]

# Dependency graph
requires:
  - phase: 04-mcp-config-ui (plan 04-02)
    provides: "find_var_refs/expand_var_refs/MissingSecretRef in agent86.secrets"
  - phase: 04-mcp-config-ui (plan 04-03)
    provides: "MCPServerConfig.enabled and ToolRegistry.unregister"
provides:
  - "MCPManager.start_server/stop_server/tools_for — task-per-server lifecycle, each server owning its own AsyncExitStack"
  - "Independent per-server teardown with no cross-task anyio cancel-scope RuntimeError (D-23)"
  - "_resolve_server_secrets/unresolved_var_refs — connect-time ${VAR} expansion in args/env/url/headers, command never expanded"
  - "build_mcp filters cfg.enabled=false servers before construction (D-09)"
affects: [04-05, 04-06, 04-07, 04-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One asyncio.Task per external resource, each owning and unwinding its own AsyncExitStack in place (anyio cancel-scope-per-task rule)"
    - "Lazy per-call import indirection (_get_client_session) so a module-scope monkeypatch can still intercept a function-local `from mcp import X`"

key-files:
  created: []
  modified:
    - src/agent86/tools/mcp_client.py
    - tests/unit/test_mcp.py
    - tests/unit/test_config.py
    - tests/integration/test_mcp_client.py

key-decisions:
  - "Each MCP server gets its own asyncio.Task + AsyncExitStack (not a shared stack), because anyio binds a transport's cancel scope to the task that entered it — aclose() from a different task raises 'cancel scope in a different task' (python-sdk #79/#922)"
  - "ClientSession is resolved via _get_client_session(), which checks module globals before importing — the only way to keep _serve's real `from mcp import ClientSession` lazy while still letting tests monkeypatch mcp_client.ClientSession"
  - "command is never ${VAR}-expanded — only args/env/url/headers — closing a foot-gun where an env var could redirect which subprocess is spawned"
  - "enabled=false filtering lives in build_mcp, not MCPManager, so MCPManager.servers is always exactly the set that should be running"

patterns-established:
  - "Per-resource task ownership for anyio-based async lifecycles needing independent teardown"

requirements-completed: [MCP-01, SEC-01]

duration: 45min
completed: 2026-08-06
---

# Phase 04 Plan 04: Task-per-server MCPManager lifecycle Summary

**Rewrote MCPManager from one shared AsyncExitStack to one persistent asyncio Task per server (D-23), added connect-time `${VAR}` resolution at the transport boundary (D-17/D-25), and filtered disabled servers in `build_mcp` (D-09).**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-08-06T05:05:00Z
- **Completed:** 2026-08-06T05:51:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- `MCPManager.start_server(name, cfg)` / `stop_server(name)` / `tools_for(name)` — each server runs in its own asyncio Task, owning its own `AsyncExitStack`, so stopping one server's task never touches another's cancel scope.
- `test_independent_teardown_leaves_other_server_intact` — the D-23 regression guard, the single highest-value test in this phase — passes for real against two live stdio `FastMCP` servers: stopping `alpha` raises no "cancel scope" / "different task" `RuntimeError`, `beta` keeps answering `call_tool`, and a subsequent `call_tool("alpha", ...)` correctly raises.
- `_resolve_server_secrets` expands `${VAR}` in `args`/`env`/`url`/`headers` at connect time (override > env > OS keyring, reusing `agent86.secrets.expand_var_refs`); `command` is never expanded. Returns a copy — the caller's config is never mutated.
- `unresolved_var_refs` gives the TUI a pre-flight list of `${VAR}` names nothing can resolve, so a future connection-test/save flow can chain into `KeyEntryModal` (D-18) instead of failing mid-connect.
- `build_mcp` now filters `cfg.enabled=false` servers before constructing `MCPManager`, and returns `None` if every server is disabled — `MCPManager.servers` is therefore always exactly the set of servers that should be running.

## Task Commits

1. **Task 1: Task-per-server lifecycle — start_server / stop_server / tools_for (D-23)** - `52bc1ab` (feat)
2. **Task 2: Connect-time ${VAR} resolution at the transport boundary (D-17/D-25)** - `7407f7b` (feat)
3. **Task 3: build_mcp filters disabled servers (D-09)** - `3778759` (feat)

_Note: tasks were marked `tdd="true"` in the plan, but the target behavior was already fully specified by the existing Wave 0 xfail scaffolds (the acceptance contract), so each task landed as a single feat commit that turns its scaffolds green rather than a separate RED commit — no new failing-test-first step was needed beyond what Wave 0 already wrote._

## Files Created/Modified

- `src/agent86/tools/mcp_client.py` - Rewrote `MCPManager`'s lifecycle half (task-per-server `start_server`/`stop_server`/`tools_for`/`_ensure_loop`/`_launch`/`_serve`), added `_get_client_session`, `_resolve_server_secrets`, `unresolved_var_refs`, and the `build_mcp` enabled-filter. `MCPTool`, `_streamable_http`, `_content_to_text`, `_sanitize`, `_open_transport` left unchanged apart from a docstring note.
- `tests/unit/test_mcp.py` - Removed `xfail` from the 3 Wave-0 lifecycle scaffolds; added 5 new `${VAR}`-resolution tests.
- `tests/unit/test_config.py` - Removed `xfail` from the 2 Wave-0 `build_mcp` filter scaffolds.
- `tests/integration/test_mcp_client.py` - Removed `xfail` from the 5 real-stdio Wave-0 scaffolds, including the D-23 regression guard.

## Decisions Made

- **`_get_client_session()` indirection (deviation from the plan's literal code sketch):** The plan's action text showed `_serve` doing a bare function-local `from mcp import ClientSession`. The Wave-0 scaffold `test_manager_start_server_registers_tools_for_lookup` monkeypatches `mcp_client.ClientSession` (with `raising=False`) expecting the implementation to consult that name — and since the real `mcp` package is installed in this environment, a literal local import would silently use the *real* `ClientSession` against fake `object()` streams and fail non-obviously. Added `_get_client_session()`, which checks `globals().get("ClientSession")` first and only falls back to a fresh `from mcp import ClientSession` if nothing was monkeypatched. This is a minimal, test-driven correction to the plan's sketch, not an architectural change: it preserves the "no module-level `from agent86.secrets import ...` / `import keyring`" lazy-import guarantee, keeps the real live-stdio integration tests using the genuine `ClientSession` (untouched, since nothing patches the module global there), and makes the unit-level fake-session scaffolds pass for real instead of accidentally exercising the real SDK against fake streams.
- Everything else in Tasks 1-3 was implemented exactly as specified in the plan's action blocks (state shape, `_ensure_loop`, `_launch`/`_serve` split, `stop_server`, `close`, `_resolve_server_secrets`, `unresolved_var_refs`, `build_mcp` filter) — verified byte-for-byte against the plan's acceptance criteria (`grep -c "self._stack"` → 0, `grep -c "cfg.enabled\|srv.enabled"` → 1, no module-level `from agent86.secrets import` / `import keyring`, byte-identical note wording preserved).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `ClientSession` lookup made monkeypatch-visible via `_get_client_session()`**

- **Found during:** Task 1, while making `test_manager_start_server_registers_tools_for_lookup` pass for real (not just xpass on a lucky accident).
- **Issue:** The plan's literal code sketch imports `ClientSession` with a function-local `from mcp import ClientSession` inside `_serve`. Because the real `mcp` package is installed in this dev environment, that import would resolve to the genuine SDK class every time, so the test's `monkeypatch.setattr(mcp_client, "ClientSession", _FakeSession, raising=False)` would have no effect — the real `ClientSession` would be constructed against two bare `object()` fake streams and fail with an unrelated `AttributeError` deep in the SDK, not the intended fake-session behavior the scaffold describes.
- **Fix:** Added `_get_client_session()`, which returns `globals().get("ClientSession")` if a test (or future caller) has set that module attribute, otherwise lazily imports the real `mcp.ClientSession`. `_serve` now calls this helper instead of importing `ClientSession` directly.
- **Files modified:** `src/agent86/tools/mcp_client.py`
- **Verification:** `pytest tests/unit/test_mcp.py -k start_server_registers_tools_for_lookup -q` and `pytest tests/unit/test_mcp.py -k stop_server_drops -q` both pass for real (not skipped, not accidentally green); the 5 live-stdio integration tests (which never monkeypatch `ClientSession`) still exercise the genuine SDK class unchanged.
- **Committed in:** `52bc1ab` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in the plan's literal code sketch vs. its own test contract)
**Impact on plan:** Necessary to make the Wave-0 acceptance contract pass for real rather than accidentally; no scope creep, no architectural change, no test assertions weakened or rewritten.

## Issues Encountered

None beyond the deviation above.

## Next Phase Readiness

- `MCP-01`'s core engineering risk (D-23 independent per-server teardown) is now closed and proven against real stdio servers — plans 04-05 through 04-08 (the TUI manager/add/edit/test-connection surfaces) can build on `start_server`/`stop_server`/`tools_for`/`unresolved_var_refs` without re-deriving lifecycle safety.
- `unresolved_var_refs` and `_resolve_server_secrets` are the exact seam the connection-test modal (D-19/D-20) and key-entry chain (D-18) need; no further backend work is required for those flows to be wired up in the TUI plans.
- Full suite green: 402 passed, 8 xfailed (unrelated, later-plan scaffolds owned by sibling plans 04-05..04-08), 0 failed.

---
*Phase: 04-mcp-config-ui*
*Completed: 2026-08-06*

## Self-Check: PASSED

All created/modified files and all 3 task commit hashes verified present.
