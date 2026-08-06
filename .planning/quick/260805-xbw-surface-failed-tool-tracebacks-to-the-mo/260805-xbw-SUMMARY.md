---
phase: quick-260805-xbw
plan: 01
subsystem: orchestration
tags: [tool-loop, guardrails, system-prompt, error-handling]

# Dependency graph
requires: []
provides:
  - "Harness._observe surfaces the real content of a failed ToolResult (traceback, stdout,
    stderr) to the model instead of the literal string 'error'"
  - "_BASE_IDENTITY debugging-discipline section instructing the model to print tracebacks,
    inspect data shape, and not blame the environment for attempt-to-attempt differences"
affects: [orchestration, cognitive-prompt]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Failure-path content resolution: error and content are merged (not one discarding the
      other) before the single shared guardrail scan site runs on the resolved observation"

key-files:
  created:
    - tests/unit/test_observe_failures.py
    - tests/unit/test_prompt_identity.py
  modified:
    - src/agent86/orchestration/loop.py
    - src/agent86/cognitive/prompt.py

key-decisions:
  - "Kept _summarize untouched — it was already correct and is the human-facing status line;
    only _observe (the model-facing path) had the bug"
  - "One guardrail scan site, not two: the failure path now resolves an observation body first,
    then falls through to the same self.ingress.inspect/wrap_untrusted logic as the success path"

patterns-established:
  - "Failed-result observation resolution: error and content combine when both present
    (error\\n\\nbody), otherwise fall back to whichever is non-empty, else the literal 'error'
    as a last-resort placeholder — never silently drop either field"

requirements-completed: [QUICK-260805-XBW]

# Metrics
duration: 25min
completed: 2026-08-06
---

# Quick Task 260805-xbw: Surface Failed Tool Tracebacks to the Model Summary

**`Harness._observe` now forwards the full traceback from a failed `python_exec`/`run_command`
result to the model (previously collapsed to the literal string `"error"`), and the system
prompt gained a debugging-discipline section teaching the model to actually use it.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-08-06T03:39:00Z
- **Completed:** 2026-08-06T04:04:49Z
- **Tasks:** 3
- **Files modified:** 4 (2 source, 2 new test files)

## Accomplishments
- Fixed `Harness._observe` (`src/agent86/orchestration/loop.py`) so a failed `ToolResult` with
  `error=None` and the real failure detail in `content` (the shape `python_exec`/`run_command`
  actually produce) delivers that content to the model, not a bare `"error"` string.
- Preserved and extended the approval-denial path: when both `error` and `content` are present
  (e.g. `"Not executed: approval denied."` plus partial stdout/stderr), both now reach the
  model; when only `error` is present, output stays byte-identical to before.
- Kept the failed-content path on the exact same injection-scan/`UNTRUSTED_BANNER` guardrail
  the success path already used — no separate scan site, no coverage gap.
- Added a `Debugging:` section to `_BASE_IDENTITY` in `src/agent86/cognitive/prompt.py`
  instructing the model to `print(traceback.format_exc())` on failure, inspect data shape
  (`.keys()`, `type()`, `len()`) before indexing, and treat attempt-to-attempt differences as
  a clue about its own code rather than proof of a flaky environment.
- Recorded the required RED evidence before any fix: 8 of 12 new tests failed pre-fix (the
  intended set), 4 passed pre-fix (the intended pins on already-correct behavior).

## Task Commits

Each task was committed atomically:

1. **Task 1: Write the RED regression tests** - `151baf1` (test)
2. **Task 2: Fix `_observe` to surface failed content** - `869cce6` (fix)
3. **Task 3: Add debugging discipline to `_BASE_IDENTITY`** - `0d69898` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## RED Evidence (Task 1, pre-fix)

Command: `python -m pytest tests/unit/test_observe_failures.py tests/unit/test_prompt_identity.py -q`

Pre-fix result: **8 failed, 4 passed**.

Failed (as intended — these exercise the bug/missing feature):
- `test_failed_result_with_only_content_reaches_model`
- `test_failed_result_preserves_full_traceback`
- `test_failed_result_with_error_and_content_keeps_both`
- `test_failed_content_still_guardrail_wrapped`
- `test_loop_delivers_traceback_to_transcript`
- `test_prompt_mentions_traceback_printing`
- `test_prompt_mentions_shape_inspection`
- `test_prompt_mentions_flaky_environment_discipline`

Passed (as intended — these pin already-correct pre-existing behavior):
- `test_failed_result_with_only_error_unchanged`
- `test_wholly_empty_failed_result_falls_back`
- `test_successful_result_path_unchanged`
- `test_summarize_still_single_line`

Post-fix (Task 2 + Task 3): all 12 pass. Full suite: **353 passed, 0 failed** (341 baseline +
12 new), confirmed via `python -m pytest -q`.

## Files Created/Modified
- `src/agent86/orchestration/loop.py` - `_observe` failure path now resolves `content` from
  `result.content`/`result.error` (joined when both present, falling back to either alone, else
  `"error"`) before running the shared guardrail scan; `_execute_tool`, `_summarize`, and
  `agents/subagent.py` untouched.
- `src/agent86/cognitive/prompt.py` - `_BASE_IDENTITY` gains a `Debugging:` block (traceback
  printing, data-shape inspection, flaky-environment discipline) appended after `Principles:`.
- `tests/unit/test_observe_failures.py` - 9 new tests covering content-only failures, full
  traceback (no truncation), error+content combination, error-only pin, wholly-empty fallback,
  guardrail wrapping of failed content, success-path non-regression, `_summarize` single-line
  pin, and a loop-level transcript-delivery proof (`Harness._execute_tool` monkeypatched to
  return a canned python_exec-shaped failure).
- `tests/unit/test_prompt_identity.py` - 3 new tests asserting the prompt mentions
  `traceback.format_exc`/`try`/`except`, `.keys()`/`type(`, and `flaky`.

## Decisions Made
- Merged `error` and `content` with a newline join rather than picking one — an approval
  denial's reason and any partial tool output are both operationally useful, and neither the
  plan nor any existing test wanted one discarded.
- Left `_summarize`, `_execute_tool`, `python_exec.py`, `shell.py`, `types.py`, and
  `agents/subagent.py` byte-unmodified, exactly as the plan's verification step requires.

## Deviations from Plan

None - plan executed exactly as written. All three tasks matched the plan's action blocks;
no Rule 1-4 auto-fixes were needed.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The fix is self-contained and already covered by regression tests; no follow-up work is
  implied for Phase 4 (MCP Config UI).
- Full suite green at 353 passed, 0 failed, confirming no regression to the existing 341.

## Self-Check: PASSED

All claimed files exist on disk; all three task commits (151baf1, 869cce6, 0d69898) found in
git history.

---
*Phase: quick-260805-xbw*
*Completed: 2026-08-06*
