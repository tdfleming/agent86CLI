---
phase: 04-mcp-config-ui
plan: 03
subsystem: mcp
tags: [mcp, config, pydantic, tool-registry, typer, cli]

# Dependency graph
requires:
  - phase: 04-mcp-config-ui
    provides: "Wave 0 xfail-marked test scaffolds (test_config.py, test_mcp.py) defining the exact contract for this plan"
provides:
  - "MCPServerConfig.enabled: bool = True field, TOML round-trippable"
  - "agent86 mcp list Enabled column (Name | Transport | Enabled | Endpoint)"
  - "ToolRegistry.unregister(name) -> bool"
affects: ["04-04 (build_mcp filtering on enabled, MCPManager.start_server/stop_server)", "04-06 (Harness.add_mcp_server/remove_mcp_server)", "manager modal status column"]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Config schema seam added ahead of the feature that consumes it (enabled flag lands before build_mcp filtering)"]

key-files:
  created: []
  modified:
    - src/agent86/config.py
    - src/agent86/cli.py
    - src/agent86/tools/registry.py
    - tests/unit/test_config.py
    - tests/unit/test_mcp.py

key-decisions:
  - "enabled field placed after transport, before the _resolve_transport validator — enabled plays no part in transport inference"
  - "unregister uses dict.pop(name, None) is not None rather than a manual 'in' check + del, matching the plan's exact prescribed implementation"
  - "register/default_registry duplicate-swallow (except ValueError: pass) left untouched — explicit single-server mount collision surfacing is deferred to plan 04-06 (D-24)"

patterns-established:
  - "Registry mutation methods (register/unregister) stay symmetric: both operate on the same private _tools dict with no side channels"

requirements-completed: [MCP-01]

# Metrics
duration: 12min
completed: 2026-08-06
---

# Phase 04 Plan 03: MCP enabled flag + registry unregister Summary

**Added `MCPServerConfig.enabled` (defaulting True, TOML round-trippable) and `ToolRegistry.unregister` — the two schema/registry seams every later plan in this phase composes on top of.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-08-06T05:21:00Z
- **Completed:** 2026-08-06T05:33:00Z
- **Tasks:** 2 completed
- **Files modified:** 5

## Accomplishments
- `MCPServerConfig` now carries a per-server `enabled: bool = True` field (D-09) that survives a hand-edited `[mcp.servers.NAME]\nenabled = false` TOML block through the existing `_normalize`/`load_config` path, with `_resolve_transport` behavior unchanged.
- `agent86 mcp list` gained an `Enabled` column (`Name | Transport | Enabled | Endpoint`), rendering `"yes"`/`"no"` from `srv.enabled` — no new Typer subcommand added.
- `ToolRegistry.unregister(name) -> bool` added — pops a tool by name, returning whether it was present, so a removed/disabled MCP server's tools stop being callable immediately without rebuilding the whole registry (D-14). `register`, `default_registry`, and the bulk-mount `except ValueError: pass` duplicate-swallow are untouched.
- All four Wave 0 scaffold tests owned by this plan (`test_mcp_server_enabled_defaults_true`, `test_mcp_server_enabled_round_trips_false` in `test_config.py`; `test_registry_unregister_removes_a_tool`, `test_registry_unregister_unknown_returns_false` in `test_mcp.py`) now pass for real with their `xfail` markers removed. The four `build_mcp`/`start_server`/`stop_server` scaffolds owned by plan 04-04 were left untouched and still xfail-marked.

## Task Commits

Each task was committed atomically:

1. **Task 1: MCPServerConfig.enabled field + Enabled column on `agent86 mcp list`** - `b97cce6` (feat)
2. **Task 2: ToolRegistry.unregister** - `f018c42` (feat)

_No separate plan-metadata commit was made for per-task work; this SUMMARY and STATE/ROADMAP updates are captured in the final docs commit._

## Files Created/Modified
- `src/agent86/config.py` - `MCPServerConfig.enabled: bool = True` field + docstring sentence
- `src/agent86/cli.py` - `mcp_list_cmd` gains an `Enabled` column, `"yes"/"no"` row value
- `src/agent86/tools/registry.py` - `ToolRegistry.unregister(name) -> bool`
- `tests/unit/test_config.py` - removed `xfail` from the two `enabled` scaffolds (now real passing tests)
- `tests/unit/test_mcp.py` - removed `xfail` from the two `unregister` scaffolds (now real passing tests)

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - both deliverables are fully wired (schema field is TOML-round-trippable and CLI-visible; registry method is fully functional and tested).

## Self-Check: PASSED

- FOUND: `src/agent86/config.py` contains `enabled: bool = True`
- FOUND: `src/agent86/tools/registry.py` contains `def unregister`
- FOUND: commit `b97cce6`
- FOUND: commit `f018c42`
