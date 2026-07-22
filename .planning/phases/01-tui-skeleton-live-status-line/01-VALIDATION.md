---
phase: 1
slug: tui-skeleton-live-status-line
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-19
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio (asyncio_mode = "auto", already configured) |
| **Config file** | pyproject.toml (`[tool.pytest.ini_options]`) |
| **Quick run command** | `pytest tests/ -q -k "tui or status or turn_bridge"` |
| **Full suite command** | `pytest -q` |
| **Estimated runtime** | ~30–60 seconds |

Textual ships `App.run_test()` / `Pilot` — no extra test dependency. Headless TUI tests run under
the existing `pytest-asyncio` auto mode.

---

## Sampling Rate

- **After every task commit:** Run the quick command
- **After every plan wave:** Run the full suite
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

Task IDs are finalized by the planner; this maps the phase's testable behaviors to requirements
and test types. The planner MUST attach an automated verify (or a Wave 0 dependency) to each.

| Behavior | Requirement | Test Type | Automated Command | Notes |
|----------|-------------|-----------|-------------------|-------|
| `format_status_line` renders the "working" branch (model · phase…) | TUI-02 | unit | `pytest tests/unit/test_status.py -q` | pure function; working branch already covered |
| turn_bridge streams generator deltas → messages in order | TUI-01 | unit | `pytest tests/tui/test_turn_bridge.py -q` | drive a fake generator; assert message sequence |
| turn_bridge approval blocks worker until result set | TUI-05 | unit | `pytest tests/tui/test_turn_bridge.py -q` | fake gate; assert Event wait + resolve |
| Footer widget flips to the working branch on status update | TUI-02 | integration | `pytest tests/tui/test_status_footer.py -q` | mount StatusFooter under `App.run_test()` |
| Slash-command adapter parity (routing, /mode, /model, /clear) | TUI-01 | unit | `pytest tests/tui/test_commands.py -q` | mirrors tests/integration/test_repl.py |
| App launches, shows transcript/input/footer | TUI-01 | integration | `pytest tests/tui/test_app.py -q` | `async with App().run_test() as pilot` |
| Footer updates to working state during a turn | TUI-02 | integration | `pytest tests/tui/test_app.py -q` | assert footer text flips while worker runs |
| Approval modal appears and its result unblocks the turn | TUI-05 | integration | `pytest tests/tui/test_app.py -q` | Pilot presses the modal's approve/deny |
| Non-TTY / Textual import or start failure falls back to plain loop | TUI-01 | unit | `pytest tests/tui/test_fallback.py -q` | monkeypatch to force fallback path |
| `agent86.cli` / `agent86.ui.repl` import does not import textual | (cross-cutting) | unit | `pytest tests/tui/test_lazy_import.py -q` | subprocess `sys.modules` guard |

*Status per task: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/tui/__init__.py` + `tests/tui/conftest.py` — new test package; stub harness/generator +
      fake gate fixture (created in 01-01 Task 3)
- [x] `tests/tui/test_turn_bridge.py` — turn-bridge streaming + approval-blocking (01-01 Task 3)
- [x] `tests/tui/test_lazy_import.py` — cli/repl import stays textual-free (01-01 Task 3 / 01-05 Task 2)
- [x] `tests/tui/test_status_footer.py` — live footer working branch (01-02 Task 3)
- [x] `tests/tui/test_commands.py` — slash-command adapter parity (01-03 Task 2)
- [x] `tests/tui/test_app.py` — Pilot app shell / streaming / approval (01-04 Task 2)
- [x] `tests/tui/test_fallback.py` — entry routing + graceful fallback (01-05 Task 2)
- [x] Add `textual` to the environment (added to pyproject core deps in 01-01 Task 1; `pip install
      -e .[dev]` picks it up; `Pilot`/`run_test()` ship with `textual`)

*Existing `tests/unit/test_status.py` already covers the pure status-line working-branch logic
(`test_status_line_working_shows_phase`) — no new pure-function test needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Visual smoothness of live footer + streaming in a real terminal | TUI-02 | Rendering fidelity/flicker isn't asserted headlessly | Run `agent86` in Windows Terminal; submit a prompt that calls a tool; confirm footer animates through "thinking"/"running <tool>" and streamed text is readable |
| Shift+Tab cycles approval mode visibly | TUI-01 | Key-binding + visual feedback | In the app, press Shift+Tab; confirm footer mode flips ask→auto→deny |

---

## Validation Sign-Off

- [x] Every implementation task has an `<automated>` verify or a Wave 0 dependency
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all missing test files
- [x] No watch-mode flags in any command
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter (by planner once tasks are mapped)

**Approval:** approved 2026-07-19
