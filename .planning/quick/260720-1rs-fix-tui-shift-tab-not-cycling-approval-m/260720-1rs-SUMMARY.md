---
quick_id: 260720-1rs
description: Fix TUI shift+tab not cycling approval mode — priority binding
completed: 2026-07-20
commits:
  - 2050765
  - 1f5e03c
files_modified:
  - src/agent86/tui/app.py
  - tests/tui/test_app.py
---

# Quick Task 260720-1rs: Fix TUI shift+tab not cycling approval mode — Summary

**One-liner:** Added `priority=True` to the `shift+tab` App binding (which Textual's default
focus-traversal binding was intercepting) plus a `SkipAction` guard in `action_cycle_mode` so
pushed modals still get their own Shift+Tab.

## What Was Wrong

Textual's `App` ships a default `shift+tab` binding for focus traversal (`focus_previous`).
`Agent86App.BINDINGS` declared `Binding("shift+tab", "cycle_mode", ...)` without `priority=True`,
so whenever the prompt `Input` was focused (i.e. always, in normal use), the default focus-
traversal handling won and `action_cycle_mode` never fired — Shift+Tab silently did nothing
despite the footer advertising `[Shift+Tab]`.

This is the same "default binding intercepts the key" footgun that the 02-02 spike documented for
`enter`, and that arrow keys / `escape` already solved with `priority=True` + `SkipAction`
fallthrough in `action_palette_up`/`_down`/`_dismiss`.

## Fix

1. **`src/agent86/tui/app.py`** — `Binding("shift+tab", "cycle_mode", "cycle approval mode",
   priority=True)`. Priority bindings are checked before focus traversal and before the focused
   widget's own bindings, so the app hotkey now wins.
2. **`action_cycle_mode`** — before cycling, raises `textual.actions.SkipAction()` when
   `len(self.screen_stack) > 1` (a modal — `ApprovalModal`, `ModePickerModal`, or
   `ModelPickerModal` — is pushed), mirroring the existing `action_palette_up`/`_down`/`_dismiss`
   pattern. This lets Shift+Tab fall through to the modal's own focus/traversal handling instead
   of cycling the approval mode underneath it.

## Regression Test

Added `test_shift_tab_cycles_approval_mode` to `tests/tui/test_app.py`. It drives a real
`Agent86App` via `App.run_test()` and presses the actual key with
`await pilot.press("shift+tab")` (not a direct `action_cycle_mode()` call, which would not catch
a binding-interception regression since that path always worked). Asserts the approval mode
advances `ask` → `auto` → `deny` across two consecutive presses.

**Reproduction proof (per plan constraint):** Before committing the fix, temporarily reverted the
`priority=True` change and reran the new test in isolation:

```
python -m pytest tests/tui/test_app.py::test_shift_tab_cycles_approval_mode -q
```

Result: **FAILED** — `AssertionError: assert 'ask' == 'auto'` (the mode never advanced), confirming
the test genuinely reproduces the bug. The `priority=True` change was then reapplied and the same
test passed, along with the full suite.

## Verification

```
python -m pytest tests/tui -q
```

Result: **39 passed** (with the fix applied).

## Deviations from Plan

None — plan executed exactly as written. Both tasks (priority binding + `SkipAction` guard;
key-press regression test with pre-fix failure confirmation) completed as specified.

## Self-Check

- `src/agent86/tui/app.py` — FOUND, modified with `priority=True` and `SkipAction` guard.
- `tests/tui/test_app.py` — FOUND, contains `test_shift_tab_cycles_approval_mode`.
- Commit `2050765` — FOUND in `git log`.
- Commit `1f5e03c` — FOUND in `git log`.

## Self-Check: PASSED
