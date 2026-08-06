---
phase: 03-secrets-model-provider-config
plan: 05
subsystem: ui
tags: [textual, command-registry, keyring, rich, typer]

# Dependency graph
requires:
  - phase: 03-secrets-model-provider-config
    provides: "agent86.secrets module (resolve_api_key/keyring_available/has_stored_key) from 03-02"
  - phase: 02-command-palette-menus
    provides: "declarative COMMANDS registry (CommandEntry/find_command/handle_command/_help_table) that /help and the palette both read from"
provides:
  - "/config model registered in COMMANDS with needs_choice=\"config_model\", discoverable via /help and the / palette with zero per-surface wiring"
  - "find_command_for_line: longest-name-first multi-word command dispatch, used by handle_command"
  - "Key column (env/keyring/none/n/a) + OS keyring availability line in both the TUI /models table and agent86 config (bare)"
affects: [03-09-full-app-chain]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Multi-word slash commands: registry entries may contain a literal space in `name` (e.g. \"/config model\"); find_command_for_line matches longest-name-first (exact or name+\" \") so a multi-word entry always wins over its single-word prefix, while find_command (exact-name lookup used by the palette) stays untouched"
    - "_key_source(name, prov): env > keyring > none > n/a, defined identically in cli.py and tui/commands.py, never renders the key value itself (D-10)"

key-files:
  created: []
  modified:
    - src/agent86/tui/commands.py
    - src/agent86/cli.py
    - tests/tui/test_commands.py

key-decisions:
  - "Widened ChoiceKind to include \"config_model\"; the /config model CommandEntry's handler is only the non-TUI fallback text — Agent86App._run_or_chain (plan 03-09) intercepts needs_choice=\"config_model\" before the handler runs, exactly as it already does for \"model\"/\"mode\""
  - "The plan described the Key-column table as living in \"the config command\" in cli.py, but that table (Provider/Base URL/API key env) actually belongs to _list_models (backing `agent86 models`), while `agent86 config` was a bare Typer sub-app with only show/path subcommands and no default action. Resolved by adding a config_app callback (invoke_without_command=True) that calls _list_models when no subcommand is given, so `agent86 config` now shows the same providers+Key+keyring-status output the plan's acceptance criteria expect, without duplicating the table logic or touching `agent86 config show`/`agent86 config path`"

requirements-completed: [MODEL-01, SEC-01]

# Metrics
duration: ~20min
completed: 2026-08-06
---

# Phase 3 Plan 5: /config Model Command Registration + Keyring Visibility Summary

**`/config model` is now a first-class COMMANDS entry discoverable via `/help`/the palette with multi-word dispatch, and both `agent86 config` and the TUI `/models` table show a per-provider Key source (env/keyring/none/n/a) plus OS keyring availability, with no secret ever rendered.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-08-06T00:05Z (approx)
- **Completed:** 2026-08-06T00:15:46Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments
- `ChoiceKind` widened to `Literal[None, "model", "mode", "config_model"]`; new `/config model` `CommandEntry` added immediately after `/config` in `COMMANDS`, with `needs_choice="config_model"` for plan 03-09's modal chain and a non-TUI fallback handler for typed/plain-loop dispatch
- `find_command_for_line(line)` added: sorts `COMMANDS` longest-name-first and matches exact-or-followed-by-a-space, so `/config model` wins over `/config`, `/models` still beats the `/model` prefix, and `/model <arg>` / `/quit` / `/exit` dispatch unchanged; `handle_command` rewritten to use it while `find_command` (exact-name lookup, used by the palette) stays byte-identical
- `_key_source(name, prov)` helper (env → keyring → none → n/a) added to both `tui/commands.py` and `cli.py`; `_models_tables` (TUI `/models`) and `_list_models` (`agent86 models`, and now bare `agent86 config`) both gained a `Key` column and an `OS keyring: available/unavailable` status line
- `agent86 config` (no subcommand) now shows the same providers+Key+keyring-status output via a new `config_app` callback that delegates to `_list_models`; `agent86 config show`/`agent86 config path` unchanged
- 8 new regression tests added to `tests/tui/test_commands.py` covering `/config model` routing, `/config` vs `/config model`, `/models` vs `/model`, `/help` listing, palette prefix matching, and the new Key/keyring rendering (with keyring calls monkeypatched, never touching a real backend)
- Full suite green: 262 passed, 2 xfailed, 1 xpassed, 0 failed

## Task Commits

1. **Task 1: Add multi-word command lookup and the /config model registry entry** - `2dbdffb` (feat)
2. **Task 2: Surface keyring availability and per-provider key source in `agent86 config`** - `22242fc` (feat)

**Plan metadata:** (this commit) `docs(03-05): complete /config model command + keyring visibility plan`

## Files Created/Modified
- `src/agent86/tui/commands.py` - `ChoiceKind` widened; `/config model` `CommandEntry`; `find_command_for_line`; `handle_command` rewritten to use it; `_key_source` helper; `_models_tables` gains Key column + keyring status line
- `src/agent86/cli.py` - `import os` at module top (stdlib, no lazy-import concern); `config_app` callback delegating bare `agent86 config` to `_list_models`; `_list_models` gains `_key_source` helper (lazy `agent86.secrets` import inside the function body), Key column, and keyring status line
- `tests/tui/test_commands.py` - 8 new regression tests for multi-word dispatch and Key/keyring rendering

## Decisions Made
- See `key-decisions` in frontmatter: `/config model`'s handler is TUI-fallback-only text (plan 03-09 owns the real modal chain); `agent86 config`'s bare-invocation table was implemented by wiring a `config_app` callback to the existing `_list_models` helper rather than duplicating the providers-table logic, since the plan's described table already existed under `agent86 models` and `agent86 config` had no prior default action.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `agent86 config` had no bare-invocation behavior to attach the Key/keyring output to**
- **Found during:** Task 2
- **Issue:** The plan describes editing "the config command body... around line 222" to add the Key column and keyring line, and an acceptance criterion runs `agent86 config` expecting that output. In the actual codebase, line ~222 is inside `_list_models` (backing `agent86 models`), while `agent86 config` is a Typer sub-app (`config_app`) with only `show`/`path` subcommands and no default action — invoking it bare would just print Typer help, not a providers table.
- **Fix:** Added `_key_source` + the Key column + keyring status line to `_list_models` exactly as the plan's code blocks specify (this is genuinely the same table structure/columns the plan describes), then added a `config_app` callback (`invoke_without_command=True`) that calls `_list_models(load_config())` when no subcommand is given, so `agent86 config` now satisfies the plan's literal acceptance criteria without touching `config show`/`config path`.
- **Files modified:** `src/agent86/cli.py`
- **Verification:** `python -m agent86.cli config` prints the Providers table with a `Key` column and an `OS keyring:` line; `python -m agent86.cli config show`/`config path` still work; `python -c "import sys, agent86.cli; assert 'keyring' not in sys.modules"` exits 0; full suite green.
- **Committed in:** `22242fc` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking — plan/codebase drift on which command owns the providers table)
**Impact on plan:** Necessary to satisfy the plan's own acceptance criteria given the actual `cli.py` structure. No scope creep — no new command surface was invented, only a default action wired to an existing, already-planned table.

## Issues Encountered
None beyond the deviation above. Both tasks' acceptance-criteria greps (registry entry, `find_command_for_line` definition/usage/`__all__`, `_key_source` in both files, `add_column("Key")`, lazy-import guard) passed on first verification run.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
`/config model`'s `needs_choice="config_model"` is ready for plan 03-09's `Agent86App._run_or_chain` to intercept and chain into the provider-manager modal stack (03-06/03-07/03-08). No blockers for downstream plans in this wave; ran fully in parallel alongside 03-06/03-07/03-08 touching only `commands.py`, `cli.py`, and `test_commands.py` as scoped.

---
*Phase: 03-secrets-model-provider-config*
*Completed: 2026-08-06*

## Self-Check: PASSED

`src/agent86/tui/commands.py` and `src/agent86/cli.py` confirmed modified as described; commits `2dbdffb` and `22242fc` confirmed in git history.
