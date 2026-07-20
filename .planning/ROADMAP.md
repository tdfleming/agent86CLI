# Roadmap: agent86 Interactive Milestone (v0.6)

**Created:** 2026-07-19
**Phases:** 5 | **Requirements mapped:** 10/10 ✓

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | TUI Skeleton + Live Status | 3/5 | In Progress|  |
| 2 | Command Palette + Menus | Autocompleting slash-command palette and arrow-key menus | TUI-03, TUI-04 | 3 |
| 3 | Secrets + Model Config | Keyring-backed keys; add/switch/test models with config write-back | SEC-01, MODEL-01, MODEL-02 | 4 |
| 4 | MCP Config UI | Add/remove/enable/test MCP servers from within the app | MCP-01 | 3 |
| 5 | Packaging & Hardening | Lazy-import packaging, graceful degradation, docs, release | TUI-06 | 4 |

---

## Phase Details

### Phase 1: TUI Skeleton + Live Status Line
**Goal:** Stand up a full-screen Textual app as the default interactive UI, reusing the existing
threaded turn bridge, with a footer status bar that updates continuously while a turn runs.

**Requirements:** TUI-01, TUI-02, TUI-05

**Success criteria:**
1. Launching `agent86` with no subcommand opens a Textual app with a scrollable transcript, a
   prompt input, and a footer status bar; existing slash-command behavior reaches parity.
2. Streamed model output appears incrementally in the transcript; a turn runs in a worker thread
   without freezing the UI.
3. The footer status bar updates model / ctx% / tokens / cost / phase *while a turn is processing*
   (the `StatusState.working`/`phase` branch is now live), not just at the prompt.
4. A tool-approval request shows a modal dialog whose choice unblocks the worker thread's
   approval event; the plain loop and `run --json` still work.

**Why first:** Proves the load-bearing architecture (async Textual ↔ sync threaded harness
generator + modal approval) and delivers the headline "live status line" on its own.

**Plans:** 3/5 plans executed
- [x] 01-01-PLAN.md — Foundation: textual dep, tui package skeleton, messages, turn_bridge, Wave 0 scaffolds (wave 1)
- [x] 01-02-PLAN.md — StatusFooter reactive widget + ApprovalModal screen (wave 2)
- [x] 01-03-PLAN.md — Slash-command adapter (commands.py) with renderable output (wave 2)
- [ ] 01-04-PLAN.md — Agent86App + run_tui: shell, worker turn bridge, live footer, modal, bindings (wave 3)
- [ ] 01-05-PLAN.md — Entry routing in run_repl to the TUI with graceful plain-loop fallback (wave 4)

### Phase 2: Command Palette + Menus
**Goal:** Replace hand-parsed slash-command strings with a Textual command palette (autocomplete)
and arrow-key selectable menus/modals.

**Requirements:** TUI-03, TUI-04

**Success criteria:**
1. Typing `/` (or a palette hotkey) shows an autocompleting list of commands with descriptions;
   selecting one runs it.
2. Commands that need a choice (e.g. pick a model) present an arrow-key `OptionList`/`RadioSet`
   rather than requiring typed arguments.
3. All existing slash-commands are reachable via the palette with behavior unchanged.

### Phase 3: Secrets + Model/Provider Config
**Goal:** Keyring-backed API keys and an in-app model-config modal that lists, switches, adds, and
live-tests providers/models, writing changes back to user config non-destructively.

**Requirements:** SEC-01, MODEL-01, MODEL-02

**Success criteria:**
1. `resolve_api_key(provider, pconf)` resolves env first, then keyring; providers use it and env
   vars keep working; config never stores a plaintext secret.
2. A model-config modal can add a provider/model, store its key in the keyring, and run a live
   connection test that confirms a response before saving.
3. Saving writes to `~/.agent86/config.toml` via tomlkit with existing comments preserved; a
   project-scope option is offered.
4. Switching the active model from the modal takes effect for the next turn.

### Phase 4: MCP Config UI
**Goal:** An in-app MCP modal to list, add, remove, and enable/disable servers, validating a
server's connection and listing its tools before saving.

**Requirements:** MCP-01

**Success criteria:**
1. The modal lists configured MCP servers with transport and status.
2. Adding a server (stdio/sse/http) runs a connection test that starts it and enumerates its
   tools before the entry is written to config.
3. Removing or disabling a server updates config non-destructively and reflects in the app.

### Phase 5: Packaging & Hardening
**Goal:** Finalize lazy-import packaging so cold-start for scripting doesn't regress, ensure
graceful degradation, and ship docs.

**Requirements:** TUI-06

**Success criteria:**
1. Textual/keyring/tomlkit are lazy-imported; `agent86 run` cold-start shows no measurable
   regression versus v0.5.8.
2. Missing Textual or keyring backend degrades cleanly (plain loop; env-var key resolution) with
   a clear note, not a crash.
3. `run --json` and the plain loop pass their tests unchanged; Textual `Pilot` headless tests
   cover the core TUI flows.
4. README + CHANGELOG updated; version bumped for the v0.6 release.

---
*Roadmap created: 2026-07-19*
