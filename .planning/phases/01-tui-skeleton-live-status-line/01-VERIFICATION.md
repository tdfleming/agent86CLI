---
phase: 01-tui-skeleton-live-status-line
verified: 2026-07-19T00:00:00Z
status: human_needed
score: 4/4 must-haves verified (automated); 1 item requires human verification
human_verification:
  - test: "Run `agent86` in a real terminal (Windows Terminal), submit a tool-using prompt, and watch the footer live"
    expected: "Footer animates through 'thinking'/'running <tool>' while the turn runs; streamed text is readable and doesn't flicker/tear; Shift+Tab visibly flips the approval mode segment; the approval modal renders centered and legibly"
    why_human: "Visual rendering smoothness, terminal compatibility, and real keypress/mouse interaction cannot be verified via headless Pilot tests or grep"
  - test: "Run `agent86 --plain` in the same terminal session"
    expected: "The plain stdlib-input loop runs exactly as before, with no visual regression"
    why_human: "Visual/manual confirmation of the fallback path in a real terminal"
---

# Phase 1: TUI Skeleton + Live Status Line Verification Report

**Phase Goal:** Stand up a full-screen Textual app as the default interactive UI, reusing the
existing threaded turn bridge, with a footer status bar that updates continuously while a turn
runs.
**Verified:** 2026-07-19
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Launching `agent86` with no subcommand opens a Textual app with a scrollable transcript, a prompt input, and a footer status bar; existing slash-command behavior reaches parity | ✓ VERIFIED | `src/agent86/tui/app.py` `Agent86App.compose()` yields `RichLog(id="transcript")`, `Static(id="stream")`, `Input(id="prompt")`, `StatusFooter(id="status")`; `src/agent86/ui/repl.py::run_repl` routes rich-capable TTYs to `run_tui` first; `src/agent86/tui/commands.py::handle_command` reproduces every branch of `_Repl.dispatch` (verified line-by-line against `ui/repl.py`); `tests/tui/test_commands.py` (5 tests) and `tests/tui/test_app.py::test_shell_has_transcript_input_footer` pass |
| 2 | Streamed model output appears incrementally in the transcript; a turn runs in a worker thread without freezing the UI | ✓ VERIFIED | `Agent86App._run_turn` is `@work(thread=True, exclusive=True)`, body is `run_turn_worker(...)`; `on_turn_delta` appends to `self._stream_buf` and updates `#stream` Static per delta; `tests/tui/test_app.py::test_turn_streams_and_footer_goes_live_then_idle` passes; `tests/tui/test_turn_bridge.py::test_streams_deltas_in_order` proves ordered delta posting off the Textual app entirely |
| 3 | The footer status bar updates model/ctx%/tokens/cost/phase WHILE a turn is processing (the StatusState.working/phase branch is now live), not just at the prompt | ✓ VERIFIED | `StatusFooter.watch_status` (with `reactive(None, always_update=True)`) calls the unmodified `format_status_line`; `on_turn_delta`/`on_tool_announce` set `status.working=True`, `status.phase=...` and reassign `footer.status` on every delta/tool-announce; `tests/tui/test_status_footer.py` proves the working/phase branch renders "thinking…"/"running write_file…" and omits "ctx"; `tests/tui/test_app.py::test_turn_streams_and_footer_goes_live_then_idle` proves this live during an actual (fake-provider) turn |
| 4 | A tool-approval request shows a modal dialog whose choice unblocks the worker thread's approval event; the plain loop and `run --json` still work | ✓ VERIFIED | `turn_bridge.make_approval_cb` posts `ApprovalRequest(event, box)` and blocks on `event.wait()`; `Agent86App.on_approval_request` calls `push_screen(ApprovalModal(...), _resolve)` where `_resolve` sets `box["ok"]` and `event.set()` on every dismissal path; `ApprovalModal` resolves via `dismiss(bool)` on approve/deny/Escape (no path leaves it unresolved); `tests/tui/test_app.py::test_approval_modal_resolves_worker` covers both approve and deny/escape without hanging; `_Repl.plain_loop` / `rich_loop` / `_run_turn_rich` are byte-for-byte unmodified in `ui/repl.py`; `run --json` doesn't route through `run_repl` at all (unaffected); full `pytest -q` (178 tests) is green |

**Score:** 4/4 truths verified (all automated checks pass); footer visual smoothness and real-terminal modal rendering flagged for human verification (see below).

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `src/agent86/tui/messages.py` | TurnDelta/ToolAnnounce/ApprovalRequest/TurnDone/TurnError Message subclasses | ✓ VERIFIED | All 5 classes present, exact fields match plan spec, `__all__` exported |
| `src/agent86/tui/turn_bridge.py` | run_turn_worker + make_approval_cb | ✓ VERIFIED | Both functions present; imports `_tool_label` from `agent86.ui.repl` (reused, not reimplemented); no textual widget/App import |
| `tests/tui/conftest.py` | fake_harness fixture | ✓ VERIFIED | `fake_harness`/`raising_harness`/`fake_state` fixtures present, reuse real `ApprovalGate` |
| `src/agent86/tui/widgets/status_footer.py` | StatusFooter(Static) reactive on StatusState | ✓ VERIFIED | `reactive(None, always_update=True)`, `watch_status` calls `format_status_line` |
| `src/agent86/tui/screens/approval.py` | ApprovalModal(ModalScreen[bool]) | ✓ VERIFIED | `on_button_pressed` + `action_deny`, both dismiss with explicit bool |
| `src/agent86/tui/commands.py` | handle_command(repl, line) -> CommandResult | ✓ VERIFIED | Reproduces every `_Repl.dispatch` branch; zero `print(`/`console.print` calls (grep confirmed) |
| `src/agent86/tui/app.py` | Agent86App(App) + run_tui(cfg, resume) | ✓ VERIFIED | Full shell composition, worker wiring, all 5 message handlers, Shift+Tab binding, `run_tui` entry present |
| `src/agent86/ui/repl.py` (edit) | run_repl routes rich-capable path to run_tui with fallback | ✓ VERIFIED | `from agent86.tui.app import run_tui` inside `_use_rich` branch; `except ImportError` and `except Exception` both fall through to `repl.plain_loop()`; no top-level `agent86.tui` import |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `turn_bridge.py` | `harness.gate.prompt` | `make_approval_cb` assignment before iterating `run_turn` | ✓ WIRED | `harness.gate.prompt = make_approval_cb(post)` precedes the `for delta in harness.run_turn(...)` loop |
| `turn_bridge.py` | `agent86.ui.repl._tool_label` | import + reuse | ✓ WIRED | `from agent86.ui.repl import _tool_label`, called per-delta |
| `status_footer.py` | `agent86.ui.status.format_status_line` | `watch_status` calling it | ✓ WIRED | Direct call inside `watch_status` |
| `approval.py` | `self.dismiss(bool)` | button press + escape action | ✓ WIRED | `on_button_pressed` and `action_deny` both call `dismiss(<bool>)` |
| `commands.py` | `cycle_mode`/`parse_mode` | `/mode` handling | ✓ WIRED | `_set_mode` uses both helpers |
| `commands.py` | `repl.harness.set_model`/`repl._refresh_status` | `/model` handling | ✓ WIRED | `_set_model` calls both |
| `app.py` | `turn_bridge.run_turn_worker` | `@work(thread=True)` body | ✓ WIRED | `_run_turn` worker body is exactly `run_turn_worker(self.repl.harness, line, self.repl.state, self.post_message)` |
| `app.py` | `screens.approval.ApprovalModal` | `on(ApprovalRequest)` -> `push_screen` | ✓ WIRED | `on_approval_request` pushes the modal with a resolving callback |
| `app.py` | `widgets.status_footer.StatusFooter` | `footer.status` reassignment | ✓ WIRED | Reassigned in `on_mount`, `on_input_submitted`, `_start_turn`, all 4 message handlers, `action_cycle_mode` |
| `app.py` | shift+tab binding -> cycle_mode | `BINDINGS` + `action_cycle_mode` | ✓ WIRED | `Binding("shift+tab", "cycle_mode", ...)` + `action_cycle_mode` calls `repl._cycle_approval()` |
| `ui/repl.py` | `agent86.tui.app.run_tui` | lazy import inside `_use_rich` branch | ✓ WIRED | Confirmed in `run_repl` |
| `ui/repl.py` | plain loop fallback | except ImportError/Exception -> `plain_loop()` | ✓ WIRED | Both except branches fall through to unconditional `repl.plain_loop()` at function end |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| TUI-01 | 01-01, 01-03, 01-04, 01-05 | Full-screen Textual app launches as default interactive UI, slash-command parity | ✓ SATISFIED | Shell composes correctly; `run_repl` routes to `run_tui`; `handle_command` has full parity coverage; REQUIREMENTS.md marks TUI-01 `[x]` Complete |
| TUI-02 | 01-02, 01-04 | Live status bar during turn processing | ✓ SATISFIED | `StatusFooter` + working/phase branch wired live in `app.py`'s message handlers; REQUIREMENTS.md marks TUI-02 `[x]` Complete |
| TUI-05 | 01-01, 01-02, 01-04 | Tool-approval modal unblocks worker thread | ✓ SATISFIED | `ApprovalRequest`/`ApprovalModal`/`_resolve` wiring confirmed end-to-end, both approve and deny/escape paths tested; REQUIREMENTS.md marks TUI-05 `[x]` Complete |

No orphaned requirements found — REQUIREMENTS.md's Phase 1 row (TUI-01, TUI-02, TUI-05) exactly matches the union of `requirements:` fields declared across all 5 plans.

### Anti-Patterns Found

None blocking. Scanned `src/agent86/tui/*.py` and the `src/agent86/ui/repl.py` diff for TODO/FIXME/placeholder/stub markers, empty handlers, and hardcoded-empty renders — none found. All widgets are backed by real logic (no `return <div>Placeholder</div>`-equivalent stubs); `handle_command` and `run_turn_worker` are fully implemented, not scaffolds.

### Scope Guardrails

Confirmed via `git diff --stat` across the phase's commit range (`6efa64b..e3143ec`): the only source files touched outside the new `src/agent86/tui/` package and its tests were `pyproject.toml` (added `textual>=1.0` dependency) and `src/agent86/ui/repl.py` (the planned `run_repl` routing edit — 17 lines changed). `src/agent86/orchestration/loop.py` (Harness/cognitive loop), `src/agent86/cognitive/`, `src/agent86/gateway/` (providers), and `src/agent86/config.py` (config schema) were NOT modified.

### Test Suite / Lazy-Import Guard

- `pytest -q` — 178 passed (full suite, no regressions).
- `pytest tests/tui/ -q` — 20 passed.
- `python -c "import sys, agent86.ui.repl as r; assert 'textual' not in sys.modules"` — exits 0.
- `python -c "import sys, agent86.cli; assert 'textual' not in sys.modules"` — exits 0.

### Human Verification Required

### 1. Real-terminal footer animation and modal rendering

**Test:** Run `agent86` in a real terminal (e.g. Windows Terminal), submit a tool-using prompt with approval mode `ask`.
**Expected:** The footer visibly animates through "thinking…" and "running <tool>…" while the turn runs, streamed text is readable without flicker/tearing, the approval modal renders centered and legibly, and Shift+Tab visibly flips the mode segment.
**Why human:** Visual smoothness, terminal-emulator compatibility, and real keyboard/mouse interaction with the modal cannot be verified via headless `Pilot`/`run_test()` assertions or static analysis — this is explicitly called out as "Manual-Only" in the 01-05 plan's `<verification>` section and was not exercised by the automated executor.

### 2. Plain-loop fallback in a real terminal

**Test:** Run `agent86 --plain` in the same terminal.
**Expected:** The stdlib `input()`-based plain loop runs exactly as before phase 1, with no visual or behavioral regression.
**Why human:** Confirms no unintended interaction between the new TUI code path and the untouched plain-loop code path in an actual terminal session.

### Gaps Summary

No gaps. All automated must-haves (truths, artifacts, key links, requirements) verified against the actual codebase — not just SUMMARY claims. Every plan's declared `must_haves` was independently checked against the real files (`messages.py`, `turn_bridge.py`, `status_footer.py`, `approval.py`, `commands.py`, `app.py`, `ui/repl.py`), and all cross-references (Message classes, `_tool_label`, `format_status_line`, `cycle_mode`/`parse_mode`, `run_turn_worker`, `push_screen`) are genuinely wired, not stubbed. The full test suite (178 tests) is green, the lazy-import constraint holds for both `agent86.cli` and `agent86.ui.repl`, and scope guardrails were respected (only `pyproject.toml` and `ui/repl.py` touched outside the new `tui/` package). The only outstanding item is manual/visual confirmation in a real terminal, which the plan itself flagged as Manual-Only and out of scope for the automated executor.

---

*Verified: 2026-07-19*
*Verifier: Claude (gsd-verifier)*
