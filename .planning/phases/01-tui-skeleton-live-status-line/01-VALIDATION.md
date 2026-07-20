---
phase: 1
slug: tui-skeleton-live-status-line
status: draft
nyquist_compliant: false
wave_0_complete: false
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
| `format_status_line` renders the "working" branch (model · phase…) | TUI-02 | unit | `pytest tests/test_status.py -q` | pure function; extend existing status tests |
| turn_bridge streams generator deltas → messages in order | TUI-01 | unit | `pytest tests/test_turn_bridge.py -q` | drive a fake generator; assert message sequence |
| turn_bridge approval blocks worker until result set | TUI-05 | unit | `pytest tests/test_turn_bridge.py -q` | fake gate; assert Event wait + resolve |
| App launches, shows transcript/input/footer | TUI-01 | integration | `pytest tests/test_tui_app.py -q` | `async with App().run_test() as pilot` |
| Footer updates to working state during a turn | TUI-02 | integration | `pytest tests/test_tui_app.py -q` | assert footer text flips while worker runs |
| Approval modal appears and its result unblocks the turn | TUI-05 | integration | `pytest tests/test_tui_app.py -q` | Pilot presses the modal's Yes/No |
| Non-TTY / Textual import failure falls back to plain loop | TUI-01 | unit | `pytest tests/test_repl_fallback.py -q` | monkeypatch to force fallback path |

*Status per task: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_turn_bridge.py` — new file; fixtures for a fake harness/generator + fake gate
- [ ] `tests/test_tui_app.py` — new file; `Pilot`-based harness for the Textual app
- [ ] `tests/test_repl_fallback.py` — new file (or extend existing REPL test) for fallback path
- [ ] Add `textual` to the dev/test environment (already a core dep once added to pyproject)

*Existing `tests/test_status.py` (if present) covers the pure status-line logic; extend it for the
working-branch assertions.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Visual smoothness of live footer + streaming in a real terminal | TUI-02 | Rendering fidelity/flicker isn't asserted headlessly | Run `agent86` in Windows Terminal; submit a prompt that calls a tool; confirm footer animates through "thinking"/"running <tool>" and streamed text is readable |
| Shift+Tab cycles approval mode visibly | TUI-01 | Key-binding + visual feedback | In the app, press Shift+Tab; confirm footer mode flips ask→auto→deny |

---

## Validation Sign-Off

- [ ] Every implementation task has an `<automated>` verify or a Wave 0 dependency
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all missing test files
- [ ] No watch-mode flags in any command
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter (by planner once tasks are mapped)

**Approval:** pending
