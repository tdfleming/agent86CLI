# Roadmap: agent86 Interactive Milestone (v0.6)

**Created:** 2026-07-19
**Phases:** 5 | **Requirements mapped:** 10/10 ✓

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | TUI Skeleton + Live Status | 5/5 | Complete   | 2026-07-20 |
| 2 | Command Palette + Menus | 4/4 | Complete   | 2026-07-20 |
| 3 | Secrets + Model Config | 13/13 | Complete   | 2026-08-06 |
| 4 | MCP Config UI | 8/8 | Complete   | 2026-08-06 |
| 5 | Packaging & Hardening | TUI-06 | Complete   | 2026-09-19 |

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

**Plans:** 5/5 plans complete
- [x] 01-01-PLAN.md — Foundation: textual dep, tui package skeleton, messages, turn_bridge, Wave 0 scaffolds (wave 1)
- [x] 01-02-PLAN.md — StatusFooter reactive widget + ApprovalModal screen (wave 2)
- [x] 01-03-PLAN.md — Slash-command adapter (commands.py) with renderable output (wave 2)
- [x] 01-04-PLAN.md — Agent86App + run_tui: shell, worker turn bridge, live footer, modal, bindings (wave 3)
- [x] 01-05-PLAN.md — Entry routing in run_repl to the TUI with graceful plain-loop fallback (wave 4)

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

**Plans:** 4/4 plans complete
- [x] 02-01-PLAN.md — Declarative COMMANDS registry backing dispatch + /help (wave 1)
- [x] 02-02-PLAN.md — Wave-0 spike: priority `enter` binding vs Input.Submitted fallthrough (wave 1)
- [x] 02-03-PLAN.md — Arrow-key ModePicker (RadioSet) + ModelPicker (OptionList) + model_choices source (wave 1)
- [x] 02-04-PLAN.md — `/`-triggered palette dropdown + key routing + picker chaining in app.py (wave 2)

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

**Plans:** 13/13 plans complete
- [x] 03-01-PLAN.md — Wave-0 test scaffolds, fixtures, keyring/tomlkit deps + lazy-import guard (wave 0)
- [x] 03-02-PLAN.md — secrets.py resolve_api_key + provider key seam moved into provider_for_ref (wave 1)
- [x] 03-03-PLAN.md — config_writer.py: tomlkit round-trip, scope selection, diff, atomic write (wave 1)
- [x] 03-04-PLAN.md — cognitive/catalog.py: live models-endpoint fetch + per-provider normalization (wave 1)
- [x] 03-05-PLAN.md — `/config model` command entry, multi-word dispatch, keyring status in /config (wave 2)
- [x] 03-06-PLAN.md — KeyEntryModal (masked) + ConnectionTestModal (worker + 15s timeout + Save anyway) (wave 2)
- [x] 03-07-PLAN.md — SaveDiffModal: scope radio + TOML diff preview + confirm/cancel (wave 2)
- [x] 03-08-PLAN.md — ProviderManagerModal + type-to-filter CatalogPickerModal with free-text fallback (wave 2)
- [x] 03-09-PLAN.md — App wiring: /config model chain, session catalog cache, enriched /model picker (wave 3)

_Gap closure (UAT blockers 1-5, see 03-HUMAN-UAT.md):_
- [x] 03-10-PLAN.md — key never echoed to the transcript (event.stop + #prompt guard) + UNRESOLVED pass-through so a keyring key resolves on every test (gaps 1, 4) (wave 1)
- [x] 03-11-PLAN.md — no key in crash tracebacks: Typer show_locals off, secrets.redact, provider construction fails soft (gap 2) (wave 1)
- [x] 03-12-PLAN.md — cognitive/capabilities.py: omit temperature/top_p/top_k for models that removed them (gap 5) (wave 1)
- [x] 03-13-PLAN.md — anthropic SDK-version guard + fail-soft startup (gap 3, code hardening only) (wave 2)

### Phase 4: MCP Config UI
**Goal:** An in-app MCP modal to list, add, remove, and enable/disable servers, validating a
server's connection and listing its tools before saving.

**Requirements:** MCP-01

**Success criteria:**
1. The modal lists configured MCP servers with transport and status.
2. Adding a server (stdio/sse/http) runs a connection test that starts it and enumerates its
   tools before the entry is written to config.
3. Removing or disabling a server updates config non-destructively and reflects in the app.

**Plans:** 8/8 plans complete

Plans:
- [x] 04-01-PLAN.md — Wave 0 test scaffolds: secrets/config_writer/config/mcp units, real-stdio D-23 teardown guard, TUI Pilot modules (wave 0)
- [x] 04-02-PLAN.md — secrets.py ${VAR} resolver + config_writer DELETE sentinel & SEC-01 authorization guard (wave 1)
- [x] 04-03-PLAN.md — MCPServerConfig.enabled + ToolRegistry.unregister + `agent86 mcp list` Enabled column (wave 1)
- [x] 04-04-PLAN.md — MCPManager task-per-server lifecycle (D-23), connect-time ${VAR} expansion, build_mcp enabled filter (wave 2)
- [x] 04-05-PLAN.md — tui/screens/mcp_manager.py: server list modal + shared add/edit form with inline validation (wave 2)
- [x] 04-06-PLAN.md — Harness.ensure_mcp / add_mcp_server / remove_mcp_server live mount-unmount seam (wave 3)
- [x] 04-07-PLAN.md — tui/screens/mcp_test.py: 30s worker-thread connection test with tool enumeration (wave 3)
- [x] 04-08-PLAN.md — `/config mcp` registry entry + full app.py chain (form → key → test → diff → save → live mount) (wave 4)

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

**Status:** Complete (2026-09-19). Executed as a review-driven hardening pass rather than a
numbered plan set — see `phases/05-packaging-hardening/SUMMARY.md` for the commit-by-commit
breakdown: transcript markup escaping, single harness construction per process, the plain loop
routed through the shared command registry, turn cancellation and hang-free shutdown, a capped
live stream region, removal of the dead prompt_toolkit rich loop and spinner, the catalog-picker
flake, a clean ruff run, and the v0.6.0 docs + version bump.

---

# Roadmap: agent86 Trustworthy Milestone (v0.7)

**Created:** 2026-09-19
**Phases:** 1 | **Requirements mapped:** 8/8 ✓

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 6 | Trustworthy Harness | 8/8 | Complete | 2026-09-19 |

### Phase 6: Trustworthy Harness
**Goal:** close the gap between what the harness *reports* and what is true, and between what it
*claims* to defend and what it defends. Every item was a v0.6 review finding, not new surface.

**Requirements:** REL-01, REL-02, REL-03, REL-04, REL-05, SEC-02, SEC-03, SEC-04

**Success criteria:**
1. `limits.max_cost_usd` can trip, `/cost` and the status footer show real dollars for priced
   models, `$0.0000` only for genuinely local ones, and `cost n/a (unpriced model)` where the
   rate is unknown.
2. A typo in `model.router` / `sandbox.mode` / `guardrails.ingress` / `guardrails.egress` fails
   validation with the allowed values named, instead of silently disabling the feature.
3. A provider failure mid-stream retries when transient and, when not, aborts the turn into the
   ERROR phase with `turn_end status="error"` persisted — never a dangling turn; `limits.max_steps`
   is the only step budget.
4. `egress = "redact"` redacts what is streamed, what is stored, and what is later recalled, and
   tool-call arguments are scanned.
5. A delegated turn is bounded by `agents.max_steps`, trims its context, and bills its usage and
   cost to the parent turn and the cost cap.
6. `web_fetch` refuses loopback/private/link-local/reserved targets on every hop, tool and MCP
   subprocesses get a curated environment rather than the host's, and a timed-out command takes
   its whole process tree (and its container) with it.

**Status:** Complete (2026-09-19). Executed as a review-driven pass rather than a numbered plan
set — see `phases/06-trustworthy-harness/SUMMARY.md` for the commit-by-commit breakdown.

**Commits** (oldest-first, `b230909..`):

| Commit | Workstream |
|---|---|
| `3b75b24` fix(tui): close six mypy type holes in the TUI app shell | TUI types |
| `9a5aa0e` test(tui): cover the no-pending-row and None-dismissal guards | TUI types |
| `8a0d97b` feat(security): SSRF guard, redirect re-vetting and body cap for web_fetch | SEC-02 |
| `1d24d31` fix(loop): never leave a turn dangling when a provider stream fails | REL-03 |
| `7b5cb63` fix(sandbox): cross-platform env allowlist, opt-in passthrough, honest tool timeout | SEC-03 |
| `6479ad0` fix(sandbox): kill the whole process tree and the container on timeout | SEC-03 |
| `6bddd04` feat(cognitive): retry transient provider failures with backoff | REL-03 |
| `7c2efc2` feat(pricing): populate the price table so the cost cap is real | REL-01 |
| `4ac84ce` fix(guardrails): make egress redact mode actually redact | REL-04 |
| `7e65fb8` feat(config): make mode fields enums and add the v0.7 shared contract fields | REL-02 |
| `ad56066` fix(circuit): treat max_steps=None as "use limits.max_steps", not falsy | REL-03 |
| `a17a484` fix(mcp): scrub the environment handed to stdio servers, and accumulate notes | SEC-04 |
| `15d62b4` feat(tools): record and log tool-name collisions at startup | Tool registry |
| `fd02c44` fix(ui): give the status line the full provider:model ref for pricing | REL-01 |
| `9fa1519` fix(orchestration): drop the hidden 12-step cap and make sub-agents accountable | REL-03, REL-05 |
| `3f37105` fix(tools): tell the model its tool-call JSON was malformed | REL-03 |
| `2ea8642` fix(router): invalidate the provider cache when config changes | REL-03 |

---
*v0.6 roadmap created: 2026-07-19 · v0.6 complete: 2026-09-19 (5/5 phases)*
*v0.7 roadmap created: 2026-09-19 · v0.7 complete: 2026-09-19 (1/1 phase, 8/8 requirements)*
