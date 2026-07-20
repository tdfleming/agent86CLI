---
phase: 2
slug: command-palette-menus
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-19
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Populated from `02-RESEARCH.md` § Validation Architecture and the four PLAN.md `<validation>` blocks.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2+ with `pytest-asyncio` (`asyncio_mode = "auto"`), Textual `App.run_test()` / `Pilot` harness |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `pytest tests/tui/ -x -q` |
| **Full suite command** | `pytest -q` |
| **Estimated runtime** | ~5–10 seconds (full suite ~178 tests before this phase) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/tui/ -x -q`
- **After every plan wave:** Run `pytest -q` (full suite)
- **Before `/gsd:verify-work`:** Full suite green **and** the Open Question 1 spike (02-02) resolved
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | TUI-03 | unit | `pytest tests/tui/test_commands.py -x -q` | ✅ extend | ⬜ pending |
| 02-01-02 | 01 | 1 | TUI-03 | unit (incl. `/model` vs `/models` regression `test_models_vs_model_routing`) | `pytest tests/tui/test_commands.py -x -q` | ✅ extend | ⬜ pending |
| 02-02-01 | 02 | 1 | TUI-03/04 | spike / integration (Pilot — Open Question 1: priority `enter` vs `Input.Submitted`) | `pytest tests/tui/test_palette_keys.py -x -q` | ❌ W0 (write FIRST) | ⬜ pending |
| 02-03-01 | 03 | 1 | TUI-04 | integration (Pilot — `ModePickerModal` RadioSet) | `pytest tests/tui/test_pickers.py -x -q -k mode` | ❌ W0 | ⬜ pending |
| 02-03-02 | 03 | 1 | TUI-04 | integration (Pilot — `ModelPickerModal` OptionList + `model_choices` source/`[]` fallback) | `pytest tests/tui/test_pickers.py -x -q -k model` | ❌ W0 | ⬜ pending |
| 02-03-03 | 03 | 1 | TUI-04 | integration (Pilot — full picker select→callback) | `pytest tests/tui/test_pickers.py -x -q` | ❌ W0 | ⬜ pending |
| 02-04-01 | 04 | 2 | TUI-03 | integration (Pilot — `/` dropdown filters, name+description) | `pytest tests/tui/test_palette.py -x -q -k filter` | ❌ W0 | ⬜ pending |
| 02-04-02 | 04 | 2 | TUI-03/04 | integration (Pilot — priority key routing + picker chaining) | `pytest tests/tui/test_palette.py -x -q` | ❌ W0 | ⬜ pending |
| 02-04-03 | 04 | 2 | TUI-03/04 | regression (typed cmd + plain turn still work: `test_typed_command_still_works_with_palette`, `test_plain_turn_still_submits_with_palette`) | `pytest tests/tui/test_palette.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Backward-compat guards (success criterion 3, D-11) — must stay green unmodified in behavior:**
- `pytest tests/tui/test_commands.py -x -q` (typed slash-commands)
- `pytest tests/tui/test_app.py::test_turn_streams_and_footer_goes_live_then_idle -x` (plain-text turn submission with priority bindings registered)
- `pytest tests/tui/test_lazy_import.py -x` (no `textual` import from `agent86.cli` — lazy cold-start guarantee)

---

## Wave 0 Requirements

- [ ] `tests/tui/test_palette_keys.py` — **spike, write FIRST** — resolves Open Question 1 (priority `enter` binding + `Input.Submitted` fallthrough) before palette Enter-handling is built (Plan 02, gates Plan 04 Task 2)
- [ ] `tests/tui/test_palette.py` — new file: dropdown open/filter/select + `/model` and `/mode` picker chains + backward-compat (Plan 04)
- [ ] `tests/tui/test_pickers.py` — new file: `ModePickerModal` (RadioSet) and `ModelPickerModal` (OptionList) select→callback (Plan 03)
- [ ] `tests/tui/test_commands.py::test_help_matches_registry` — extend existing file: `_help_table` generated from `COMMANDS`, not hand-maintained (Plan 01)
- [ ] `tests/tui/test_commands.py::test_models_vs_model_routing` — extend existing file: `/model` vs `/models` prefix edge case (Plan 01)

*Picker-modal tests live in `test_pickers.py`/`test_palette.py` alongside existing patterns — mirroring how `ApprovalModal` is tested in-place today (no separate screens test dir needed).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Dropdown renders in the right place and coexists visually with the live `#stream` line and `StatusFooter` without flicker/overlap | TUI-03 (D-13) | Pilot asserts widget state/`display`, not pixel layout; final visual coexistence is a human judgment | Run `agent86` TUI, type `/`, confirm the palette appears between the stream line and prompt, filters as you type, dismisses on Esc, and the footer status still refreshes live during a turn |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-20 (strategy populated; `wave_0_complete` flips true once the Wave 0 test files land during execution)
