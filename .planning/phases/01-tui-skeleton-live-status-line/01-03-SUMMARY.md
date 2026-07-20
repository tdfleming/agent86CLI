---
phase: 01-tui-skeleton-live-status-line
plan: 3
subsystem: tui
tags: [textual, commands, repl-parity]
dependency_graph:
  requires:
    - agent86.ui.repl._Repl (harness/state/status, _refresh_status, _cycle_approval)
    - agent86.guardrails.policy (cycle_mode, parse_mode)
  provides:
    - agent86.tui.commands.CommandResult
    - agent86.tui.commands.handle_command
    - agent86.tui.commands.startup_notes
  affects:
    - future TUI app shell (plan 01-04) will call handle_command/startup_notes to populate the transcript
tech_stack:
  added: []
  patterns:
    - "Command adapter returns renderables (str / rich renderables) instead of printing to a Console, so a Textual RichLog can consume them"
key_files:
  created:
    - src/agent86/tui/commands.py
    - tests/tui/test_commands.py
  modified: []
decisions:
  - "handle_command mutates the passed-in _Repl object in place (state/gate/status), matching _Repl.dispatch's contract exactly, rather than returning a diff/patch object"
  - "/models returns a tuple of two Rich Table renderables (providers, roles) since the original _list_models prints two separate tables"
metrics:
  duration: "~15m"
  completed: 2026-07-20
---

# Phase 1 Plan 3: TUI command adapter (slash-command parity) Summary

Ported `_Repl.dispatch`'s slash-command behavior into `agent86/tui/commands.py` as a pure
adapter — `handle_command(repl, line) -> CommandResult` — that returns renderables (str or Rich
`Table`) instead of printing to a `Console`, so the future Textual app can write results into its
transcript `RichLog`. `ui/repl.py` and the plain loop are unchanged.

## What Was Built

- `CommandResult` dataclass: `action` ("handled" | "turn" | "exit" | "noop") + optional `render`.
- `handle_command(repl, line)`: reproduces every branch of `_Repl.dispatch` — `/help`, `/config`,
  `/models`, `/tools`, `/skills`, `/memory`, `/cost`, `/clear`, `/mode[ arg]`, `/model[ arg]`,
  unknown `/...`, empty line, `/exit`/`/quit`, and non-slash lines (`"turn"`). `/mode` and
  `/model` mutate `repl.harness.gate.mode` / `repl.harness.set_model` and refresh
  `repl.status` exactly as the original branches do, just without any stdout writes.
- `startup_notes(repl) -> list[str]`: the memory/mcp/sandbox/skills/session-id note strings
  from `_Repl.print_notes`, as plain strings for the transcript.
- `tests/tui/test_commands.py`: parity tests mirroring `tests/integration/test_repl.py` —
  dispatch routing, `/mode` set + bare-cycle + invalid-mode-no-op, `/model` switch (keyless
  ollama) + bad-ref/missing-key rejection, and `/clear` new-session behavior.

## Verification

- `pytest tests/tui/test_commands.py -q` — 5 passed.
- `pytest tests/tui/ -q` — 12 passed (full tui suite, including turn_bridge/lazy-import from
  plan 01-01).
- `pytest -q` (full suite) — 170 passed.
- `grep -nE "console\.print|(^|[^_])print\(" src/agent86/tui/commands.py` — no matches (no
  stdout side effects).
- `git status --short src/agent86/ui/repl.py` — empty (untouched).

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: src/agent86/tui/commands.py
- FOUND: tests/tui/test_commands.py
- FOUND commit 255ec9a (feat(01-03): add Textual command adapter returning renderables)
- FOUND commit 2e84f2c (test(01-03): add commands adapter parity tests)
