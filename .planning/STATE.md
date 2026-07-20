---
gsd_state_version: 1.0
milestone: v0.6
milestone_name: milestone
status: unknown
last_updated: "2026-07-20T04:57:03.995Z"
progress:
  total_phases: 5
  completed_phases: 2
  total_plans: 9
  completed_plans: 9
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-19)

**Core value:** Run, configure, and steer the agent entirely from within an interactive terminal
app — no hand-editing TOML, no restarts.
**Current focus:** Phase 02 — command-palette-menus (complete; next: Phase 3 — Secrets + Model Config)

## Milestone

**v0.6 — Interactive** (agent86 currently at v0.5.8)
5 phases | 10 v1 requirements | 0 phases complete

## Progress

| Phase | Status | Plans | Progress |
|-------|--------|-------|----------|
| 1 — TUI Skeleton + Live Status | ● | 5/5 | 100% |
| 2 — Command Palette + Menus | ● | 4/4 | 100% |
| 3 — Secrets + Model Config | ○ | 0/? | 0% |
| 4 — MCP Config UI | ○ | 0/? | 0% |
| 5 — Packaging & Hardening | ○ | 0/? | 0% |

## Recent Activity

- 2026-07-20 — Quick task 260720-1rs complete: fixed Shift+Tab silently doing nothing in the TUI
  instead of cycling the approval mode. Root cause: Textual's `App` ships a default `shift+tab`
  binding for focus traversal that intercepted the key ahead of `Agent86App`'s `cycle_mode`
  binding whenever the prompt `Input` was focused — the same footgun 02-02 documented for `enter`.
  Fixed by marking the binding `priority=True` and guarding `action_cycle_mode` with `SkipAction`
  when a modal is pushed, mirroring the existing `action_palette_up`/`_down`/`_dismiss` pattern.
  New regression test presses the real key via `pilot.press("shift+tab")` (confirmed to fail
  pre-fix, pass post-fix). Full suite green (39 TUI tests).

- 2026-07-20 — Quick task 260720-1jw complete: fixed the TUI `/models` command printing
  `<rich.table.Table object at 0x...>` reprs. Root cause: `_models_tables` returned a tuple
  `(table, roles)` but `CommandResult.render` must be a single renderable and `RichLog.write`
  stringifies a non-renderable tuple. Fixed by returning `Group(table, roles)`; pinning test
  updated. Full suite green (196 tests).

- 2026-07-20 — Plan 02-04 complete (Phase 2 now feature-complete, 4/4 plans): `#palette`
  `OptionList` wired into `Agent86App` — typing `/` filters `COMMANDS` by prefix into a dropdown;
  priority `up`/`down`/`escape` App bindings navigate/dismiss it, each raising `SkipAction` when
  hidden so the key falls through to a focused modal's own widget (a bug found while wiring
  picker chaining — the same footgun 02-02 proved for `enter`, now closed for arrow keys too).
  Enter-routing follows the 02-02 Approach B decision exactly: no permanent priority `enter`
  binding; `on_input_submitted` checks the palette first, otherwise dispatches unchanged.
  Selecting `/model`/`/mode` chains into the Plan 03 pickers via `_run_or_chain`; every path —
  typed, plain-turn, or picker-chained — now funnels through one shared `_dispatch_line` helper.
  Full suite green (196 tests) including D-11 backward-compat and lazy-import guards.

- 2026-07-20 — Plan 02-01 complete: `tui/commands.py::handle_command` refactored from a flat
  if/else chain into a declarative `COMMANDS: list[CommandEntry]` registry (`CommandEntry` =
  name/usage/description/handler/needs_choice/terminal) with `find_command` lookup; `_help_table`
  now renders from `COMMANDS` instead of hand-written rows, so `/help` and the palette can never
  drift. `needs_choice` is `"model"` on `/model` and `"mode"` on `/mode` for Plan 03/04 to consume.
  All existing behavior preserved byte-for-byte (including the `/quit` alias and the `/models` vs
  `/model` prefix edge case), pinned by three new regression tests. Full suite green (190 tests).

- 2026-07-20 — Plan 02-02 complete: wave-0 spike (`tests/tui/test_palette_keys.py`) resolves
  RESEARCH Open Question 1 empirically — a permanent App-level priority `enter` Binding
  suppresses `Input.Submitted` even when its action no-ops. **Enter-routing decision: Approach B**
  — Plan 04 must dynamically bind/unbind `enter` only while the palette is open, never register
  it as a permanent priority binding. `up`/`down` confirmed safe as permanent priority bindings.
  Full suite green (190 tests).

- 2026-07-20 — Plan 01-05 complete: `run_repl` now routes the default rich-capable TTY path to
  `run_tui` (lazy-imported inside the branch), with `--plain`/`AGENT86_PLAIN`/non-TTY and any
  Textual import-or-start failure falling back to the plain loop with a dim note — proven by
  `tests/tui/test_fallback.py` (routing, both fallback paths, textual-free import). Phase 1 is
  now feature-complete (5/5 plans); full suite green (178 tests). Manual Windows Terminal
  verification per 01-VALIDATION.md is still outstanding before declaring the phase fully done.

- 2026-07-20 — Plan 01-04 complete: `Agent86App(App)` composes the RichLog transcript + streaming
  Static line + prompt Input + `StatusFooter`; turns run on a Textual thread worker
  (`run_turn_worker` + `post_message`), the footer stays live during processing, and
  `ApprovalModal` resolves the worker's blocked `threading.Event` on every dismissal path —
  proven by headless `App.run_test()` Pilot tests covering shell, live streaming, and both
  approve/deny approval outcomes. `run_tui(cfg, resume)` is the TUI entry point. Full suite green
  (174 tests).

- 2026-07-20 — Plan 01-02 complete: `StatusFooter(Static)` reactive widget (always_update=True on
  a `StatusState` attribute) makes `format_status_line`'s working/phase branch live, and
  `ApprovalModal(ModalScreen[bool])` resolves approve/deny/escape to an explicit bool on every
  dismissal path — proven by headless `App.run_test()` widget tests. Full suite green (170 tests).

- 2026-07-20 — Plan 01-03 complete: `agent86/tui/commands.py` ports `_Repl.dispatch` slash-command
  behavior into a `CommandResult`/`handle_command`/`startup_notes` adapter that returns renderables
  instead of printing to stdout — proven by parity tests mirroring `tests/integration/test_repl.py`.
  Full suite green (170 tests).

- 2026-07-20 — Plan 01-01 complete: tui package skeleton, textual core-but-lazy dep, Message
  vocabulary (TurnDelta/ToolAnnounce/ApprovalRequest/TurnDone/TurnError), and the turn_bridge
  worker/approval bridge — proven by headless unit tests + lazy-import guard. Full suite green
  (162 tests).

- 2026-07-19 — Phase 1 planned: 5 plans across 4 waves (foundation/turn-bridge → widgets+commands →
  app shell → entry routing/fallback). Wave 0 test scaffolds included per 01-VALIDATION.md.

- 2026-07-19 — Project initialized from a pre-agreed plan (brownfield; codebase already read in
  session, formal mapping skipped). PROJECT.md, config.json, REQUIREMENTS.md, ROADMAP.md written.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260720-1jw | Fix TUI /models rendering bug — wrap tables in a Group | 2026-07-20 | 47da657 | [260720-1jw-fix-tui-models-rendering-bug-wrap-tables](./quick/260720-1jw-fix-tui-models-rendering-bug-wrap-tables/) |
| 260720-1rs | Fix TUI shift+tab not cycling approval mode — priority binding | 2026-07-20 | 2050765 | [260720-1rs-fix-tui-shift-tab-not-cycling-approval-m](./quick/260720-1rs-fix-tui-shift-tab-not-cycling-approval-m/) |

## Next Step

Phase 2 complete (4/4 plans) — TUI-03 and TUI-04 delivered. Next: `/gsd:execute-phase 3` —
Secrets + Model Config.
