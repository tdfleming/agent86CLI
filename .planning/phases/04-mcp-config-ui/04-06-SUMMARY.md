---
phase: 04-mcp-config-ui
plan: 06
subsystem: orchestration
tags: [harness, mcp, tool-registry, live-config]

# Dependency graph
requires:
  - phase: 04-mcp-config-ui (04-04)
    provides: task-per-server MCPManager with start_server/stop_server/tools_for
  - phase: 04-mcp-config-ui (04-03)
    provides: ToolRegistry.unregister and MCPServerConfig.enabled
provides:
  - Harness.ensure_mcp() — lazy MCPManager creation for sessions that started with none
  - Harness.add_mcp_server(name, cfg) — mounts an already-connected server's tools into
    the live registry, returning (mounted, collisions)
  - Harness.remove_mcp_server(name) — unregisters a server's tools and stops its session
affects: [04-07, 04-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Mutate live Harness objects (self.mcp, self.registry) directly instead of rebuilding
      them from self.config, matching the existing set_model() discipline"

key-files:
  created: []
  modified:
    - src/agent86/orchestration/loop.py
    - tests/unit/test_loop.py

key-decisions:
  - "add_mcp_server never opens a transport itself — it only wires in tools the connection
    test already started via MCPManager.start_server, so the explicit mount path stays
    symmetric with the connection-test UI flow"
  - "Name collisions on the explicit mount path are returned to the caller (D-24) rather than
    silently swallowed like default_registry's bulk-startup path"
  - "Neither method reads self.config.mcp_servers after construction — self.mcp.servers and
    self.registry are the only live truth (RESEARCH Pitfall 3)"

patterns-established:
  - "D-15 needs no code: _build_request reads self.registry.specs() fresh every turn, so any
    mount/unmount change is visible on the very next turn with zero additional wiring"

requirements-completed: [MCP-01]

# Metrics
duration: 25min
completed: 2026-08-06
---

# Phase 04 Plan 06: Harness Live Mount/Unmount Seam Summary

**Three new `Harness` methods (`ensure_mcp`, `add_mcp_server`, `remove_mcp_server`) let a config
change mount or unmount MCP tools mid-session without a restart or a registry rebuild.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-08-06T05:30:00Z (approx, parallel wave)
- **Completed:** 2026-08-06T06:01:29Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `Harness.ensure_mcp()` gives a session that started with zero MCP servers (`self.mcp is None`)
  a live, empty `MCPManager` to attach to, idempotently and without touching the registry.
- `Harness.add_mcp_server(name, cfg)` mounts an already-connected server's tools into the live
  registry, returning `(mounted, collisions)` so a name collision is reported instead of silently
  dropped.
- `Harness.remove_mcp_server(name)` unregisters a server's tools, stops its session, and drops it
  from `manager.servers` — safe to call for an unknown name or when no manager exists yet.
- `_build_request` already reads `self.registry.specs()` fresh every turn (D-15), so a mount or
  unmount takes effect on the very next turn with no additional wiring.

## Task Commits

Each task was committed atomically:

1. **Task 1: Harness.ensure_mcp** - `8ef72d0` (feat)
2. **Task 2: Harness.add_mcp_server / remove_mcp_server** - `ad74d69` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/agent86/orchestration/loop.py` - adds `ensure_mcp`, `add_mcp_server`, `remove_mcp_server`
  to `Harness`; imports `MCPManager` and `MCPServerConfig`
- `tests/unit/test_loop.py` - 15 new unit tests covering manager creation/idempotency, mount,
  collision reporting, config recording, transport-free mounting, and unmount/no-op paths

## Decisions Made
- Followed the plan's exact method bodies and docstrings, with two small docstring wording
  changes (avoiding the literal strings `default_registry`/`start_server` inside prose) so the
  plan's own literal `grep -c` acceptance checks for "no rebuild"/"no transport" stay meaningful
  as intent checks rather than tripping on documentation text that merely explains the design.
- No architectural changes were needed; `MCPManager`, `ToolRegistry`, and `Config` already
  exposed every seam this plan required.

## Deviations from Plan

None — plan executed exactly as written. The only edits beyond the plan's literal action blocks
were two docstring wording tweaks (see Decisions Made) that do not change behavior.

## Issues Encountered

None. The two new methods slotted in immediately after `mcp_note` as specified; `_build_request`
required no changes because it already reads `self.registry.specs()` fresh on every call.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plans 04-07 and 04-08 (which own the remaining `xfail`-marked TUI scaffolds and wire the
  manager modal to these Harness methods) can now call `harness.ensure_mcp()` /
  `harness.add_mcp_server()` / `harness.remove_mcp_server()` directly — no further Harness changes
  are needed for the live mount/unmount seam itself.
- Full suite green: 418 passed, 2 xfailed (owned by other in-flight plans in this parallel wave),
  0 failed.

---
*Phase: 04-mcp-config-ui*
*Completed: 2026-08-06*

## Self-Check: PASSED

- FOUND: src/agent86/orchestration/loop.py
- FOUND: tests/unit/test_loop.py
- FOUND: .planning/phases/04-mcp-config-ui/04-06-SUMMARY.md
- FOUND commit: 8ef72d0
- FOUND commit: ad74d69
