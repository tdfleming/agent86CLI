---
phase: quick-260922-bnr
plan: 01
subsystem: ui
tags: [tui, textual, rich, repl, transcript, scripting-contract]

# Dependency graph
requires: []
provides:
  - "ui/repl.py exports banner(cfg, *, compact=True) — the one identity-panel definition
    (agent86 v<version>, model <ref>; compact=False appends router/sandbox/approval/hint)"
  - "tui/app.py renders the banner as transcript entry 0 (survives _rerender, re-prepended on
    /resume and /clear) instead of the TUI carrying no identity at all"
  - "CommandResult.clears_transcript: bool — a structural signal (not string-matching on
    '/clear') the TUI uses to wipe its scrollback and reprint the banner"
  - "the plain loop suppresses the banner when stdout is not a TTY (piped/redirected output)"
affects: [tui-app, ui-repl, tui-commands, scripting-contract]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One shared render function with a compact flag, consumed by both an interactive
      surface (TUI, compact identity core) and a scriptable one (plain loop, full detail) —
      same shape as the existing per-turn cost line and approval-diff sharing"
    - "Structural CommandResult flags (clears_transcript) instead of the app matching on a
      command's literal name, so a shared registry can't drift per-surface"

key-files:
  created:
    - tests/tui/test_banner.py
  modified:
    - src/agent86/ui/repl.py
    - src/agent86/tui/app.py
    - src/agent86/tui/commands.py
    - src/agent86/tui/widgets/status_footer.py
    - tests/tui/test_transcript_escape.py
    - tests/tui/test_transcript_render.py
    - tests/tui/test_fallback.py
    - tests/integration/test_scripting_contract.py

key-decisions:
  - "banner()'s compact split follows the plan's Fork 1 exactly: the TUI's StatusFooter
    already reports sandbox/approval live so its splash can drop them for free, while the
    plain loop has no live status surface at all and needs them in the banner"
  - "The /clear transcript wipe discards the just-echoed '/clear' UserEntry too — _entries
    becomes exactly [banner], not [banner, echoed-command, 'conversation cleared']"
  - "Non-TTY suppression is stdout-gated (sys.stdout.isatty()), not stdin-gated, matching the
    plan's stated failure case (echo hi | agent86 painting the panel ahead of piped output)"

patterns-established:
  - "Identity-panel-as-transcript-entry: any future TUI splash/notice that must survive
    _rerender() goes through _write()/_append_entry(), never a bare log.write()"

requirements-completed: [QUICK-260922-BNR]

# Metrics
duration: 45min
completed: 2026-09-22
---

# Quick Task 260922-bnr: Startup Banner in the TUI, from One Shared Source Summary

**`ui/repl.py`'s bordered Rich banner Panel is now `banner(cfg, *, compact=True)`, rendered by
both the TUI (as transcript entry 0, survives `/clear`, re-render, and resume) and the plain
loop (compact=False, full detail) — one definition instead of the TUI carrying no identity at
all, plus non-TTY suppression so a piped plain session doesn't paint it ahead of the answer.**

## Performance

- **Duration:** 45 min
- **Started:** 2026-09-22T00:00:00Z (approx.)
- **Completed:** 2026-09-22
- **Tasks:** 6
- **Files modified:** 8 (4 source, 4 test — plus 1 new test file and 1 lint-only follow-up)

## Accomplishments

- `_banner(cfg)` renamed to the public `banner(cfg, *, compact: bool = True)`, exported from
  `ui/repl.py.__all__`. `compact=True` is the identity core only (`agent86 v<version>`,
  `model <ref>`); `compact=False` appends router, sandbox, approval, and the `/help` hint —
  byte-identical to the old plain-loop panel. Stays Rich-only/textual-free (`Panel` is a core
  dependency, so the import graph is unchanged).
- `tui/app.py`'s `on_mount` prepends `RawEntry(banner(cfg))` as transcript entry 0, before the
  `startup_notes` loop, so the TUI finally carries identity instead of none. Because it's an
  entry (not a bare `log.write()`), it survives `_rerender()` — proven by a test that expands
  a tool block (`ctrl+o`, which fires `_rerender()`) and re-asserts entry 0. `load_session`
  (the `/resume` path) re-prepends it when rebuilding the scrollback from a saved session's
  messages, closing the third call site the plan flagged.
- `/clear` now wipes the TUI transcript, not just the session state. `CommandResult` gained
  `clears_transcript: bool = False`, set by `_clear_session` in `tui/commands.py`; the app's
  `_dispatch_line` acts on the flag structurally (never matching the string `"/clear"`),
  resetting `self._entries` to exactly `[RawEntry(banner(cfg))]` and re-rendering. The plain
  loop is untouched — `dispatch()` never inspects the new field, so `--plain`'s `/clear` keeps
  printing "conversation cleared" and nothing else, per the plan's Fork 2 ruling.
- `status_footer.py`'s stale docstring corrected: it claimed the plain loop renders the whole
  status line via `format_status_line`, but `_Repl.status_line` has no call site in the plain
  path at all — `format_status_line` is consumed only by `StatusFooter`. The corrected comment
  points at `banner(cfg, compact=False)` as the reason Fork 1 went the way it did.
- New `tests/tui/test_banner.py` (8 tests): compact-is-identity-core-only, full-has-
  router/sandbox/approval/hint, compact-is-the-default, **the drift test** (a real running TUI
  app's entry-0 text and the plain loop's printed banner agree on name/version/model from one
  function call — the point of the whole task), banner-is-entry-zero-on-mount,
  banner-survives-rerender-on-tool-expand, clear-wipes-to-exactly-the-banner, and
  resume-re-prepends-the-banner. `tests/integration/test_scripting_contract.py` gained an
  explicit assertion that `agent86 run` (json or not) never prints "agentic harness" on stdout
  or stderr.
- Non-TTY suppression (task 6's recommendation, implemented): `run_repl`'s plain path now
  gates `console.print(banner(cfg, compact=False))` on `sys.stdout.isatty()` — a piped/
  redirected `echo hi | agent86` no longer paints the panel ahead of the answer.
  `repl.print_notes()` is unaffected (notes still print). Pinned with a new
  `test_plain_path_suppresses_the_banner_when_stdout_is_not_a_tty` test.

## Task Commits

Each task was committed atomically:

1. **Task 1: `ui/repl.py` — one public `banner()`** - `aa8d038` (feat)
2. **Task 2: `tui/app.py` — the banner as a transcript entry** - `e811b5d` (feat)
3. **Task 3: `/clear` — wipe the transcript, reprint the banner** - `83b61cf` (feat)
4. **Task 4: `status_footer.py` — correct the stale docstring** - `73c5377` (docs)
5. **Task 5: Tests — the drift test and TUI/scripting-contract coverage** - `a76c27d` (test)
6. **Task 6: Decide the non-TTY plain case (suppression implemented)** - `7a9d808` (fix)

**Lint follow-up:** `572c82f` (chore: fix `ruff check` import ordering in `test_banner.py` —
`I001`, auto-fixed by `ruff check --fix`, no behavioral change)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified

- `src/agent86/ui/repl.py` - `_banner` → public `banner(cfg, *, compact=True)`; call site
  updated to `banner(cfg, compact=False)`, gated on `sys.stdout.isatty()`; exported.
- `src/agent86/tui/app.py` - imports `banner`; `on_mount` and `load_session` prepend
  `RawEntry(banner(cfg))`; `_dispatch_line`'s "handled"/"noop" branch acts on
  `result.clears_transcript`.
- `src/agent86/tui/commands.py` - `CommandResult` gains `clears_transcript: bool = False`;
  `_clear_session` sets it.
- `src/agent86/tui/widgets/status_footer.py` - module docstring corrected (no behavior change).
- `tests/tui/test_banner.py` - new, 8 tests (see Accomplishments).
- `tests/tui/test_transcript_escape.py`, `tests/tui/test_transcript_render.py` - two
  pre-existing `lines.count("agent86") == 1` assertions updated to `== 2` (the banner now
  contributes a second, unrelated "agent86" occurrence), each with an explanatory comment.
- `tests/tui/test_fallback.py` - two existing tests force `sys.stdout.isatty() -> True` (capsys
  never presents a real terminal) since they test the normal interactive case; one new test
  pins non-TTY suppression.
- `tests/integration/test_scripting_contract.py` - new
  `test_run_never_emits_the_startup_banner`.

## Decisions Made

- Kept the banner's `compact=False` body byte-identical to the pre-existing plain-loop panel
  text (same markup, same line breaks) so the drift test and the plain-loop UX are unaffected
  — only the identity-core lines are new/shared.
- The TUI's `/clear` handling discards the echoed `"/clear"` line itself along with the prior
  exchange, since `_dispatch_line` always appends a `UserEntry` for the typed line before
  dispatch runs; matching the plan's explicit test requirement ("`_entries` is exactly
  `[banner]`") meant the wipe has to happen after that echo, not skip it.
- Non-TTY suppression checks `sys.stdout` (not `sys.stdin`) because the plan's stated failure
  case is stdout getting the panel painted ahead of piped output — `_use_tui`'s existing
  stdin-non-tty check is what routes into the plain loop in the first place; this task only
  decides what the plain loop then prints.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test correctness] Updated two pre-existing "agent86" occurrence-count assertions**
- **Found during:** Task 2 (banner as a transcript entry)
- **Issue:** `test_response_is_labelled_once_per_turn` and
  `test_markdown_reply_renders_without_exceptions` asserted `lines.count("agent86") == 1` to
  pin "the reply is labelled exactly once." Adding the banner (which also contains the literal
  text "agent86" in "agent86 v1.0.0") made the count 2 for a reason unrelated to what either
  test actually verifies — the reply label count didn't regress.
- **Fix:** Updated both assertions to `== 2` with a comment explaining the banner's
  contribution, preserving each test's original intent (the reply is still labelled once).
- **Files modified:** `tests/tui/test_transcript_escape.py`, `tests/tui/test_transcript_render.py`
- **Verification:** Full TUI suite green (337 passed) after the change.
- **Committed in:** `e811b5d` (Task 2 commit)

**2. [Rule 3 - Blocking] Forced `sys.stdout.isatty()` in two test_fallback.py tests**
- **Found during:** Task 6 (non-TTY banner suppression)
- **Issue:** `test_plain_path_prints_banner_and_notes` and
  `test_tui_failure_fallback_still_prints_banner_and_notes` asserted the banner appears in
  `capsys`-captured output. pytest's `capsys` stdout replacement always reports
  `isatty() is False`, so the new suppression logic would make both tests fail — not because
  the feature is wrong, but because they were unknowingly exercising the (now-suppressed)
  non-interactive case.
- **Fix:** Both tests now `monkeypatch.setattr(sys.stdout, "isatty", lambda: True)` before
  calling `run_repl`, making them explicitly test the normal interactive case; a new sibling
  test (`test_plain_path_suppresses_the_banner_when_stdout_is_not_a_tty`) pins the suppression
  itself.
- **Files modified:** `tests/tui/test_fallback.py`
- **Verification:** `pytest tests/tui/test_fallback.py -q` — 12 passed (11 original + 1 new).
- **Committed in:** `7a9d808` (Task 6 commit)

**3. [Rule 3 - Blocking] Fixed a ruff `I001` import-order violation in the new test file**
- **Found during:** post-task check suite (`ruff check .`)
- **Issue:** `tests/tui/test_banner.py`'s combined-name import
  (`from agent86.ui.repl import banner, console as plain_console`) violated ruff's import
  sort/format rule.
- **Fix:** `ruff check --fix` split it into two `from agent86.ui.repl import ...` lines.
- **Files modified:** `tests/tui/test_banner.py`
- **Verification:** `ruff check .` reports "All checks passed!"; test file re-run, still 8/8.
- **Committed in:** `572c82f` (separate lint-only commit, no behavioral change)

---

**Total deviations:** 3 auto-fixed (1 test-correctness update spanning 2 files, 1 blocking test
adjustment, 1 lint fix). **Impact on plan:** All three are direct, necessary consequences of
implementing the plan's own tasks exactly as specified — none represent scope creep or
functional changes beyond what the plan asked for.

## Issues Encountered

None beyond the deviations above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The plan's "Out of scope" list (ASCII wordmark, `Header` widget, `--no-banner` flag, plain
  loop live status line) was respected — none of it was touched.
- Full check suite green: `ruff check .` clean, `mypy src/agent86` clean (93 source files, no
  issues), `pytest` — 1241 passed, 14 deselected (packaging-marker tests, excluded by design).
- Import-graph and cold-start tests (`tests/tui/test_lazy_import.py`,
  `tests/integration/test_smoke_cli.py`, `tests/integration/test_scripting_contract.py`'s
  `test_the_scripting_paths_never_import_textual`) are unchanged and still pass — the
  scripting/CI contract is intact.
- This work precedes § 999.0a in `docs/BACKLOG.md` per the plan's frontmatter; no code here
  blocks or depends on that backlog item.

## Self-Check: PASSED

All claimed files exist on disk; all seven commits (`aa8d038`, `e811b5d`, `83b61cf`,
`73c5377`, `a76c27d`, `7a9d808`, `572c82f`) found in `git log --oneline`.

---
*Phase: quick-260922-bnr*
*Completed: 2026-09-22*
