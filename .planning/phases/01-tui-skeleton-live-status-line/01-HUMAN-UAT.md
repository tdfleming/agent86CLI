---
status: partial
phase: 01-tui-skeleton-live-status-line
source: [01-VERIFICATION.md]
started: 2026-07-19
updated: 2026-07-19
---

## Current Test

[awaiting human testing]

## Tests

### 1. Live footer animation + streaming in a real terminal
expected: Running `agent86` (no subcommand) in a real terminal (e.g. Windows Terminal) opens the
full-screen Textual app with a scrollable transcript, prompt input, and footer. Submitting a
prompt that triggers a tool call shows the footer flip to the working branch and animate through
"thinking…" / "running <tool>…", and streamed model text appears incrementally in the transcript
without the UI freezing.
result: [pending]

### 2. Approval modal rendering + keyboard interaction
expected: When a side-effecting tool needs approval (approval mode = ask), a modal dialog appears;
approving or denying (and pressing Escape) resolves it correctly and the turn continues/aborts
accordingly. Shift+Tab cycles the approval mode (ask → auto → deny) and the footer reflects it.
result: [pending]

### 3. Plain-loop fallback unchanged in a real terminal
expected: `agent86 --plain` (and a piped/non-TTY invocation) still runs the plain REPL with no
visual or behavioral regression; `agent86 run "<goal>" --json` still emits structured JSON.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
