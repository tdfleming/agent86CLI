---
phase: 01-tui-skeleton-live-status-line
plan: 4
subsystem: ui
tags: [textual, tui, worker-thread, streaming, modal, status-line]

# Dependency graph
requires:
  - phase: 01-tui-skeleton-live-status-line (waves 1-2)
    provides: turn_bridge.run_turn_worker/make_approval_cb, tui.messages vocabulary,
      StatusFooter, ApprovalModal, commands.handle_command/startup_notes
provides:
  - "Agent86App(App): the full-screen TUI shell (transcript + streaming line + prompt + footer)"
  - "run_tui(cfg, resume): the TUI entry point that builds _Repl and launches the app"
  - "Live status footer during turn processing, driven by TurnDelta/ToolAnnounce messages"
  - "Approval modal wired to the worker thread's threading.Event via ApprovalRequest"
  - "Shift+Tab binding cycling the approval mode from inside the app"
affects: [01-05 (cli entry routing/fallback to run_tui), phase-2 (command palette will extend
  Agent86App's input handling)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Split-widget streaming: a RichLog for finalized transcript entries + a Static('#stream')
      updated wholesale on each TurnDelta, flushed into the RichLog on ToolAnnounce/TurnDone/
      TurnError (RESEARCH Pitfall 4)"
    - "post_message (thread-safe) from the @work(thread=True) worker; never call_from_thread or
      push_screen_wait from the worker"
    - "Approval resolves via push_screen(modal, callback) setting box['ok'] + event.set() on
      every dismissal path (button or Escape)"

key-files:
  created:
    - src/agent86/tui/app.py
    - tests/tui/test_app.py
  modified: []

key-decisions:
  - "Used the RESEARCH-recommended split transcript (RichLog for finalized lines, a bare Static
    for the in-flight streaming line) rather than repeated RichLog.write() per token."
  - "Test 2 (live footer) uses a small local _SlowTextProvider (time.sleep before the final
    delta) instead of the plain make_text_provider, because the plain fake completes fast enough
    that pilot.press('enter') could return control after the worker already finished, making the
    working=True assertion racy."

patterns-established:
  - "Agent86App message handlers (on_turn_delta/on_tool_announce/on_turn_done/on_turn_error) are
    the single place that mutates repl.status and reassigns footer.status; all worker-thread code
    only ever calls post_message."

requirements-completed: [TUI-01, TUI-02, TUI-05]

# Metrics
duration: 22min
completed: 2026-07-20
---

# Phase 1 Plan 4: TUI App Shell Summary

**`Agent86App(App)` composing a RichLog transcript, a streaming Static line, a prompt Input, and
a live `StatusFooter`, driving turns on a Textual thread worker and resolving tool approvals via
a modal that unblocks the worker's `threading.Event` — proven headlessly with `App.run_test()`.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-07-20T02:53:00Z
- **Completed:** 2026-07-20T03:15:51Z
- **Tasks:** 2
- **Files modified:** 2 (both created)

## Accomplishments
- `Agent86App` composes the full shell (transcript/input/footer) and `run_tui(cfg, resume)` is
  the TUI entry point, reusing `_Repl` for harness/state/status setup (incl. resume).
- Turns run on `run_worker(thread=True)` via `run_turn_worker`; deltas stream into the transcript
  live, the footer flips to the working/phase branch during processing and back to idle stats on
  completion.
- Tool approval pops `ApprovalModal` and resolves the worker's blocked `threading.Event` on every
  dismissal path (approve button, deny button, Escape).
- `Shift+Tab` cycles the approval mode and the footer's `mode:` segment updates immediately.
- Headless `Pilot` tests cover shell presence, live-footer streaming, and both approval outcomes
  (approve executes the tool + reaches the final reply; deny skips the tool but the turn still
  completes — no hang).

## Task Commits

Each task was committed atomically:

1. **Task 1: Agent86App + run_tui** - `961f78e` (feat)
2. **Task 2: Pilot integration test** - `ef3ea0f` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/agent86/tui/app.py` - `Agent86App(App)` shell, worker turn bridge wiring, message
  handlers, approval modal wiring, Shift+Tab binding, `run_tui` entry point.
- `tests/tui/test_app.py` - `App.run_test()`/`Pilot`-based integration tests for the shell, live
  footer during streaming, and approval-modal resolution (approve + deny/escape).

## Decisions Made
- Split-widget streaming approach (RichLog + Static) per RESEARCH Pitfall 4, avoiding per-token
  `RichLog.write()` line-fragmentation.
- Added a local `_SlowTextProvider` test helper (small `time.sleep`) so the "footer goes live"
  assertion has a reliable window to observe `status.working is True` before the fast in-process
  worker completes — the plan's plain `make_text_provider` case was too fast to assert against
  deterministically in a Pilot test.

## Deviations from Plan

None - plan executed exactly as written. The `_SlowTextProvider` addition is test-infrastructure
support for making a required assertion deterministic (avoiding a race condition), not a change
to `src/agent86/tui/app.py`'s planned behavior — it does not fall under Rule 4 (no architectural
change) and doesn't need to be tracked as a numbered auto-fix since it's purely additive test
scaffolding matching the plan's own guidance to keep waits bounded and non-flaky.

## Issues Encountered
- Initial version of `test_turn_streams_and_footer_goes_live_then_idle` was flaky: with the plain
  `make_text_provider("hello world")`, the fake provider's `stream()` yields immediately, so the
  worker thread could reach `TurnDone` (setting `working=False`) before the test's assertion ran,
  even though `_start_turn` sets `working=True` synchronously on the main thread first. Resolved
  by adding `_SlowTextProvider` (sleeps briefly before its final delta) so the working window is
  reliably observable; the assertion checks `repl.status.working is True` immediately after
  `pilot.press("enter")` returns (no polling needed for that half) and then polls for `working is
  False` to catch completion.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `Agent86App`/`run_tui` are ready for 01-05 to wire into `cli.py`'s entry routing (TTY-default
  TUI, `--plain`/non-TTY fallback to the plain loop, lazy Textual import preserved — `app.py`
  is only imported inside `run_tui`'s call path).
- Full test suite green (174 tests); `pytest tests/tui/ -q` and `pytest -q` both pass; the
  lazy-import guard (`'textual' not in sys.modules` after importing `agent86.ui.repl`) still
  holds.
- No blockers.

---
*Phase: 01-tui-skeleton-live-status-line*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: src/agent86/tui/app.py
- FOUND: tests/tui/test_app.py
- FOUND commit: 961f78e
- FOUND commit: ef3ea0f
