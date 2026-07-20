---
phase: 01-tui-skeleton-live-status-line
plan: 5
subsystem: ui
tags: [textual, tui, cli-entry, fallback, lazy-import]

# Dependency graph
requires:
  - phase: 01-tui-skeleton-live-status-line (waves 1-3)
    provides: "Agent86App(App) shell and run_tui(cfg, resume) entry point (Plan 4)"
provides:
  - "run_repl routes the default rich-capable TTY path to run_tui, preferring the Textual app"
  - "Graceful fallback to the plain loop on Textual ImportError or app-start Exception, with a
    dim console note (no crash, no exception propagation)"
  - "--plain / AGENT86_PLAIN / non-TTY continue to route straight to the plain loop unchanged"
  - "tests/tui/test_fallback.py proving routing + fallback + lazy-import headlessly"
affects: [phase-2 (command palette builds on this as the default entry), packaging/release
  hardening (phase-5) relies on the lazy-import guard proven here]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Entry-routing fallback: lazy `from agent86.tui.app import run_tui` wrapped in
      try/except ImportError (import-time failure) and a nested try/except Exception around
      run_tui(cfg, resume=resume) (start-time failure) — both paths print a `[dim]` note and
      fall through to the existing plain_loop() call, mirroring the prior rich_loop fallback
      shape instead of inventing a new one."

key-files:
  created:
    - tests/tui/test_fallback.py
  modified:
    - src/agent86/ui/repl.py

key-decisions:
  - "Kept `repl.rich_loop()` code and the `_Repl.rich_loop` method entirely intact but
    unreachable from run_repl, per plan instruction not to delete it this phase."
  - "run_tui builds its own `_Repl` internally (per Plan 4's `run_tui(cfg, resume)` signature),
    so run_repl's own `repl = _Repl(cfg, resume)` instance is only used for the
    notes/ProviderError-guard/plain-loop path, not passed into run_tui."

patterns-established:
  - "CLI entry fallback ladder: prefer richest UI -> catch import failure -> catch start failure
    -> degrade to the most dependable loop, each branch logging a one-line `[dim]` reason before
    falling through — reusable if a future phase adds another UI tier."

requirements-completed: [TUI-01]

# Metrics
duration: 14min
completed: 2026-07-20
---

# Phase 1 Plan 5: TUI Entry Routing + Fallback Summary

**`run_repl` now launches the Textual `Agent86App` by default on rich-capable TTYs (lazy-imported
inside the branch), with `--plain`/`AGENT86_PLAIN`/non-TTY and any Textual import-or-start failure
falling back to the existing plain loop — no crashes, no top-level `textual` import.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-07-20T03:16:43Z
- **Completed:** 2026-07-20T03:30:00Z
- **Tasks:** 2
- **Files modified:** 2 (1 modified, 1 created)

## Accomplishments
- `run_repl`'s rich-capable branch now attempts `run_tui(cfg, resume=resume)` first, importing
  `agent86.tui.app` lazily inside the branch (no module-level `textual` import anywhere in the
  cold-start path).
- Both failure modes are caught and degrade cleanly: `ImportError` on the lazy import prints
  `TUI unavailable (...); using plain REPL.` and an `Exception` raised by `run_tui` itself prints
  `TUI could not start (...); using plain REPL.` — both fall through to the unchanged
  `repl.plain_loop()` call.
- `--plain`, `AGENT86_PLAIN`, and non-TTY stdin/stdout are untouched — `_use_rich` gates entry
  into the TUI-attempt branch exactly as before.
- `cli.py`'s `run_repl(cfg, resume=resume, plain=plain)` call site needed no changes (signature
  unchanged, confirmed by reading `cli.py`).
- New `tests/tui/test_fallback.py` proves: `--plain` never touches the TUI spy, a `run_tui`
  start-time `RuntimeError` falls back to `plain_loop()` without raising, a simulated
  `ImportError` on `agent86.tui.app` also falls back without raising, and importing
  `agent86.ui.repl` in a fresh subprocess never puts `textual` in `sys.modules`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Route run_repl's rich-capable path to run_tui with graceful fallback** - `def0505` (feat)
2. **Task 2: Fallback + routing unit test** - `a3d4af6` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/agent86/ui/repl.py` - `run_repl`'s rich-capable branch now tries `run_tui` first (lazy
  import), with nested `except ImportError` / `except Exception` fallbacks to `plain_loop()`;
  `rich_loop`/`_use_rich` left in place but no longer reached from `run_repl`.
- `tests/tui/test_fallback.py` - four headless tests: plain-flag skip, TUI start-failure
  fallback, TUI import-failure fallback, and a subprocess guard that `agent86.ui.repl` import
  stays textual-free.

## Decisions Made
- Simulated the lazy `ImportError` in the test by monkeypatching `builtins.__import__` to raise
  for the exact `"agent86.tui.app"` module name, rather than uninstalling/hiding the real
  `textual` package — keeps the test fast, deterministic, and independent of whether `textual` is
  actually installed in the test environment.
- Used lightweight fake modules (`type(sys)("agent86.tui.app")` inserted into `sys.modules` via
  `monkeypatch.setitem`) instead of a real `unittest.mock.patch` on `agent86.tui.app.run_tui`, so
  the test never imports the real `textual`-backed module.

## Deviations from Plan

None - plan executed exactly as written. `run_repl`'s structure, the try/except shape, and the
dim fallback notes match the plan's code sketch verbatim; the test file covers exactly the four
behaviors the plan's `<behavior>` and `<action>` sections specified.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 1 (TUI Skeleton + Live Status Line) is now feature-complete across all 5 plans: the
  Textual app is the default interactive UI on rich-capable TTYs, live status during turn
  processing works, and every escape hatch (`--plain`, `AGENT86_PLAIN`, non-TTY, TUI
  import/start failure) degrades to the plain loop without crashing.
- `pytest tests/tui/ -q` and the full `pytest -q` suite are green (178 tests total after this
  plan). The lazy-import guard holds both for `agent86.cli` and `agent86.ui.repl`.
- Manual verification (Windows Terminal: launch `agent86`, submit a tool-using prompt, confirm
  the footer animates and Shift+Tab flips mode; launch `agent86 --plain` and confirm the plain
  loop still works) is called out in the plan's `<verification>` as Manual-Only and was not
  exercised by this automated executor — flagged for a human pass before Phase 1 is declared
  fully done.
- Ready to proceed to Phase 2 (Command Palette + Menus).

---
*Phase: 01-tui-skeleton-live-status-line*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: src/agent86/ui/repl.py
- FOUND: tests/tui/test_fallback.py
- FOUND commit: def0505
- FOUND commit: a3d4af6
