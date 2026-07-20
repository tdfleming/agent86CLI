---
phase: 02-command-palette-menus
plan: 01
subsystem: tui
tags: [python, textual, rich, slash-commands, registry-pattern]

# Dependency graph
requires:
  - phase: 01-tui-skeleton-live-status-line
    provides: "agent86/tui/commands.py CommandResult/handle_command adapter (01-03)"
provides:
  - "CommandEntry dataclass (name/usage/description/handler/needs_choice/terminal)"
  - "COMMANDS: list[CommandEntry] declarative registry, one entry per slash-command"
  - "find_command(name) exact-match lookup used by handle_command"
  - "_help_table() generated from COMMANDS (no hand-written rows, no drift)"
affects: [02-02, 02-03, 02-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Declarative command registry (CommandEntry + COMMANDS) backing both dispatch and help/palette rendering"

key-files:
  created: []
  modified:
    - src/agent86/tui/commands.py
    - tests/tui/test_commands.py

key-decisions:
  - "needs_choice is set to \"model\" on /model and \"mode\" on /mode; all other entries default to None — this is the field Plan 03 (pickers) and Plan 04 (palette) will branch on to decide whether a command needs a follow-up selector"
  - "handle_command keeps the /exit == /quit special-case OUTSIDE the registry (matching the plan's explicit instruction) rather than adding a second COMMANDS entry, since /quit is a pure alias with no distinct help row"
  - "COMMANDS list preserves the exact order of the old hand-written _help_table rows, so /help output is unchanged"

patterns-established:
  - "CommandEntry.handler is a `lambda repl, arg: CommandResult(...)` closure — new commands are added by appending one CommandEntry, not by editing an if/else chain"

requirements-completed: [TUI-03]

# Metrics
duration: 12min
completed: 2026-07-20
---

# Phase 2 Plan 1: Command Registry Refactor Summary

**Refactored `tui/commands.py::handle_command` from a flat if/else chain into a declarative `COMMANDS` registry (`CommandEntry` + `find_command`), and regenerated `_help_table` from that same registry so `/help` and the future command palette can never drift.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-20T04:28:00Z
- **Completed:** 2026-07-20T04:40:00Z
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- `CommandEntry` dataclass (frozen) with `name`, `usage`, `description`, `handler`, `needs_choice`, `terminal` — the single source of truth Plan 03/04 will consume for pickers and the palette dropdown
- `COMMANDS: list[CommandEntry]` with one entry per existing slash-command, in the original `/help` row order, each handler reproducing the exact prior branch body
- `find_command(name)` exact-match lookup; `handle_command` now partitions the line into `name`/`arg` and dispatches via `find_command` instead of a chain of `startswith` checks
- `/exit` / `/quit` alias preserved as a special-case check before registry dispatch (per plan instruction — `/quit` is not a COMMANDS entry)
- `_help_table()` now iterates `COMMANDS` to build rows — no more hand-written `add_row` calls, so help output structurally cannot drift from the registry
- Three new regression tests pin the behaviors the registry must preserve: help/registry parity, `/models` vs `/model` prefix routing, and trailing-whitespace argument handling

## Task Commits

Each task was committed atomically:

1. **Task 1: Introduce CommandEntry + COMMANDS registry and route handle_command through it** - `f43bfd2` (feat)
2. **Task 2: Generate _help_table from COMMANDS and add registry regression tests** - `9ff83f3` (feat)

_Note: tasks were marked `tdd="true"` in the plan, but the pre-existing test suite (`tests/tui/test_commands.py`) already provided full RED/GREEN coverage for Task 1's behavior contract before the refactor began, so Task 1 verified against that existing suite rather than writing new failing tests first; Task 2 added the three new registry-specific tests the plan calls for._

## Files Created/Modified
- `src/agent86/tui/commands.py` - Added `CommandEntry`, `COMMANDS`, `find_command`; rewrote `handle_command` to dispatch via the registry; rewrote `_help_table` to render from `COMMANDS`
- `tests/tui/test_commands.py` - Added `test_help_matches_registry`, `test_models_vs_model_routing`, `test_trailing_whitespace_arg`

## Decisions Made
- `needs_choice` values are exactly `"model"` (on `/model`) and `"mode"` (on `/mode`) — everything else is `None`. This is the field Plan 03's picker UI and Plan 04's palette will key off of to know which commands need a follow-up selection screen.
- Kept `/quit` as a special-cased alias outside `COMMANDS` rather than adding a duplicate entry, exactly as instructed — it has no independent help row and would otherwise appear twice in the palette.
- `COMMANDS` entry order intentionally mirrors the previous `_help_table` row order so `/help` output is byte-for-byte unchanged after the refactor.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

`COMMANDS` + `CommandEntry` + `find_command` are exported (`__all__` extended) and ready for Plan 02-03 (pickers, keyed on `needs_choice`) and Plan 02-04 (palette dropdown, iterating `COMMANDS` directly). No blockers. Full suite green (190 tests) including `tests/tui/test_lazy_import.py` (commands.py remains textual-free at import time).

---
*Phase: 02-command-palette-menus*
*Completed: 2026-07-20*

## Self-Check: PASSED

All files and commits verified present.
