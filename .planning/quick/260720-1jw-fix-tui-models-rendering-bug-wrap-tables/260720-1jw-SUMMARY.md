---
quick_id: 260720-1jw
subsystem: tui
tags: [bugfix, rich, commands]
requires: []
provides: [tui-models-single-renderable]
affects: [src/agent86/tui/commands.py, tests/tui/test_commands.py]
tech-stack:
  added: []
  patterns: ["rich.console.Group to combine multiple renderables into one CommandResult.render"]
key-files:
  created: []
  modified:
    - src/agent86/tui/commands.py
    - tests/tui/test_commands.py
decisions:
  - "Wrap the two /models tables in rich.console.Group rather than changing CommandResult to accept a list/tuple, keeping the render contract single-renderable everywhere."
metrics:
  duration: "~10 minutes"
  completed: 2026-07-20
---

# Quick Task 260720-1jw: Fix TUI `/models` rendering bug Summary

Wrapped `_models_tables(cfg)`'s two Rich tables in a single `rich.console.Group` so `CommandResult.render` stays a single renderable, fixing `/models` printing `(<rich.table.Table object at 0x...>, ...)` instead of rendering both tables in the TUI transcript.

## What Was Done

- **Task 1:** `_models_tables` in `src/agent86/tui/commands.py` now lazily imports `Group` from `rich.console` (alongside the existing lazy `Table` import) and returns `Group(table, roles)` instead of the bare tuple `table, roles`. `RichLog.write(result.render)` in `app.py` now renders a single `Group` renderable correctly, showing both the Providers and Model-roles tables.
- **Task 2:** Updated `test_models_vs_model_routing` in `tests/tui/test_commands.py` to assert `result.render` is a `rich.console.Group` and is NOT a tuple, replacing the old tuple-pinning assertions (`isinstance(result.render, tuple)` / `len(result.render) == 2`). The `/model` (singular) string assertions were left unchanged since that path was never affected.

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- `python -m pytest tests/tui/test_commands.py -q` → 8 passed.
- `python -m pytest tests/tui -q` → 38 passed.
- Manual check: `handle_command(FakeRepl(), "/models").render` is a `rich.console.Group` instance and not a tuple.

## Commits

- `c817df6` — fix(260720-1jw): wrap /models tables in a Group for RichLog rendering
- `253c738` — test(260720-1jw): pin /models Group return contract

## Self-Check: PASSED

- FOUND: src/agent86/tui/commands.py (contains `Group(table, roles)`)
- FOUND: tests/tui/test_commands.py (contains `Group` assertion)
- FOUND: commit c817df6
- FOUND: commit 253c738
