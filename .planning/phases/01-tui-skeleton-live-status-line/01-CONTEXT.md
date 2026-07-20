# Phase 1: TUI Skeleton + Live Status Line - Context

**Gathered:** 2026-07-19
**Status:** Ready for planning
**Source:** Pre-agreed design conversation (locked decisions)

<domain>
## Phase Boundary

This phase stands up a full-screen **Textual** app as the default interactive UI for agent86,
replacing the `rich_loop` as the primary experience, and makes the status bar **live during turn
processing**. It reuses the existing threaded turn bridge and modal-izes tool approval.

**In scope:** Textual App shell (transcript + input + footer), streaming into the transcript from
a worker thread, a reactive status bar that updates while a turn runs, and a modal approval
dialog. Reaching parity with today's existing slash-commands (as plain typed commands is fine —
the autocompleting *palette* is Phase 2).

**Out of scope for this phase:** command palette / autocomplete (Phase 2), arrow-key menus
(Phase 2), keyring & model-config UI (Phase 3), MCP config UI (Phase 4), lazy-import packaging
hardening & release (Phase 5).
</domain>

<decisions>
## Implementation Decisions

### UI framework
- Use **Textual** for a full-screen app (`Agent86App(App)`). This was chosen over a
  prompt_toolkit Application and over an incremental Rich approach.
- New package: `src/agent86/tui/` — do NOT bloat `ui/repl.py`. Keep `ui/status.py` pure logic.

### App layout
- Vertical layout: scrollable **transcript** pane (top, expands) · **prompt input** (bottom) ·
  **footer status bar** (bottom-most).
- Transcript is a scrollable log widget (e.g. `RichLog` or a custom `VerticalScroll` of widgets)
  that appends streamed model text and tool-announce lines.
- Footer renders `format_status_line(StatusState)` from `ui/status.py` — reuse the existing
  formatter; do not reinvent it.

### The turn bridge (load-bearing)
- `Harness.run_turn(goal, state)` is a **synchronous generator** yielding `Delta` objects. Do NOT
  make it async.
- Run it in a **worker thread** via Textual's `run_worker(thread=True)`.
- The worker posts Textual `Message` subclasses back to the app (e.g. `TurnDelta`,
  `ToolAnnounce`, `ApprovalRequest`, `TurnDone`, `TurnError`) using the thread-safe post path
  (`app.call_from_thread(...)` or `post_message`).
- **Reuse the existing pattern** in `ui/repl.py::_run_turn_rich` (queue drain + `threading.Event`
  approval blocking). Lift the reusable core into `src/agent86/tui/turn_bridge.py` so the app and
  (optionally) the legacy loop can share it. Do not duplicate the approval/streaming logic.

### Live status line (the headline requirement)
- `ui/status.py::StatusState` already has `working: bool` and `phase: str` fields and
  `format_status_line` already renders a "working" branch — this is currently dead code. Make it
  live.
- Model the footer on a **reactive** `StatusState`: set `working=True` and update `phase`
  ("thinking", `running <tool>`) as messages arrive from the worker; Textual's event loop keeps
  ticking so the footer re-renders continuously during the turn.
- Update tokens/cost/ctx% from `state` per step (mirror `_Repl._refresh_status` in `ui/repl.py`).
- Derive the tool phase label the same way `ui/repl.py::_tool_label` does (`[tool] name(...)`).

### Approval modal
- Replace the inline `input("run it? [y/N]")` with a Textual **modal screen**
  (`ModalScreen[bool]`). The worker thread blocks on a `threading.Event`; the modal's result sets
  the shared box and fires the event — same contract as `approval_cb` in
  `ui/repl.py::_run_turn_rich`, just rendered as a dialog.
- The approval callback is wired via `self.harness.gate.prompt = approval_cb` (existing seam).

### Slash commands
- Port the existing dispatch (`/help /config /models /model /tools /skills /memory /mode /cost
  /clear /exit`) so behavior matches today. Typed commands are fine this phase; the palette is
  Phase 2. Reuse `_Repl.dispatch` logic where practical (consider extracting shared command
  handlers so both the TUI and plain loop call the same functions).

### Entry point & fallback
- `cli.py::main` currently calls `run_repl(cfg, resume, plain)`. Route the default (rich-capable,
  TTY) path to the new TUI. Keep `--plain` / `AGENT86_PLAIN` / non-TTY → plain loop unchanged.
- If Textual import fails or the app can't start on this terminal, **fall back to the plain
  loop** with a dim note (mirror the existing `try/except` fallback in `run_repl`).
- **Lazy-import Textual** inside the TUI entry path only — never at module import time in
  `cli.py`, so `agent86 run` / `--plain` cold-start is unaffected.

### Scope guardrails
- Do NOT modify the harness, cognitive loop, providers, or config schema in this phase.
- `run --json` and the plain loop must keep passing their existing tests.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing UI to reuse / replace
- `src/agent86/ui/repl.py` — the two current loops; `_run_turn_rich` (threaded queue-drain +
  approval `Event`), `_tool_label`, `_Repl.dispatch`, `_Repl._refresh_status`, `run_repl`
  fallback logic. This is the primary reference for the turn bridge and command dispatch.
- `src/agent86/ui/status.py` — `StatusState` (has `working`/`phase`), `format_status_line`,
  `context_window_for`, `context_percent`, `human_tokens`. Reuse as-is.
- `src/agent86/ui/spinner.py` — current spinner (Textual replaces it, but shows current behavior).

### Harness / entry seams
- `src/agent86/cli.py` — `main` callback (routes to `run_repl`), `_emit`, UTF-8 reconfigure.
- `src/agent86/orchestration/loop.py` — `Harness`: `run_turn` (sync generator), `new_session`,
  `resume`, `set_model`, `gate` (ApprovalGate with `.prompt` and `.mode`), `provider`, `registry`,
  `skills`, `memory`, notes (`memory_note`, `mcp_note`, `sandbox_note`).
- `src/agent86/types.py` — `Delta`, `ApprovalMode`, `ModelRef`.
- `src/agent86/config.py` — `UIConfig` (`status_line`, `spinner`, `mode_cycle_key`).

### Packaging
- `pyproject.toml` — core deps (add `textual`); the "kept light so agent86 starts fast" comment
  drives the lazy-import constraint.
</canonical_refs>

<specifics>
## Specific Ideas

- Footer target (parity with today's status line, live during work):
  `claude-opus · thinking… · sbx subprocess · mode: ask  [Shift+Tab]` while working, and the
  ctx%/tokens/cost variant when idle — exactly what `format_status_line` already produces.
- Preserve **Shift+Tab cycles approval mode** (currently `cfg.ui.mode_cycle_key`, `s-tab`). In
  Textual this is a binding that calls `cycle_mode` on the gate and updates the reactive state.
- Keep the startup notes (memory/mcp/sandbox/skills/session id) — render them into the transcript
  on launch (see `_Repl.print_notes`).
- Windows console already handled via the UTF-8 reconfigure in `cli.py`; test the TUI in the
  native Windows terminal early.
</specifics>

<deferred>
## Deferred Ideas

- Autocompleting command palette + descriptions → Phase 2 (TUI-03).
- Arrow-key selectable menus/modals for choices → Phase 2 (TUI-04).
- Theming / color schemes → v2 (POL-01).
- Session picker UI → v2 (POL-02).
</deferred>

---

*Phase: 01-tui-skeleton-live-status-line*
*Context gathered: 2026-07-19 from locked design decisions*
