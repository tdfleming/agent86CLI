---
phase: 05-packaging-hardening
subsystem: ui/packaging/docs
tags: [textual, tui, packaging, lazy-import, release, docs]
requirements: [TUI-06]
status: complete
completed: 2026-09-19
---

# Phase 5 — Packaging & Hardening

**Goal:** finalize lazy-import packaging so cold-start for scripting doesn't regress, ensure
graceful degradation, and ship the v0.6.0 release docs.

**Requirement:** TUI-06 — the plain loop and `run --json` continue to work unchanged;
keyring/Textual absence degrades cleanly.

Phase 5 was executed as a review-driven hardening pass rather than a numbered plan set: the
v0.6 feature work was complete after Phase 4, and what remained was the set of defects and
loose ends that only surface once the TUI is the *default* surface. The work below is grouped
by task; commits are listed oldest-first within each group.

---

## Task 1 — The TUI can't be crashed by text it didn't write

Bracketed text in a user line, a model response, a tool error, or a config value reached Rich's
markup parser unescaped and raised `MarkupError`, taking the transcript down mid-turn. Escaping
is now applied at the boundary, with a `MarkupError` guard behind it, and the same rule extends
to the renderables the command registry produces.

- `f8b1ead` fix(tui): escape untrusted text before it reaches the transcript
- `7e25730` fix(tui): escape untrusted text in command renderables, and clear ruff
- `8349d2f` fix(tui): /help showed "/mode" instead of "/mode [ask|auto|deny]" — the usage
  string's own literal brackets were being eaten as markup

## Task 2 — One harness per process, one command registry, honest `[ui]`

`run_tui` was building a second `_Repl`, which started every configured MCP server twice and
doubled startup cost. The harness is now constructed once in `ui/repl.py` and handed to
`run_tui`. With the rich loop gone, the plain loop's hand-parsed slash-command chain was the
last place the two surfaces could drift, so it now dispatches through the same declarative
`COMMANDS` registry; and `[ui]` stopped advertising keys the code no longer honoured
(`status_line` -> `tui`, with the legacy spelling still accepted; `mode_cycle_key` removed).

- `fc73b91` refactor(ui): drop the unreachable rich REPL loop and make [ui] honest
- `43ec87c` fix(tui): build the harness once — run_tui takes the already-built _Repl
- `de61116` refactor(ui): dispatch plain-loop slash commands through the shared registry
- `cc272ee` fix(ui): stop printing the banner and launch notes behind the TUI (plain mode only;
  the TUI renders the notes into the transcript)

## Task 3 — Interruptible turns and a shutdown that terminates

A long turn was uninterruptible, and quitting could block forever on an approval modal nobody
was left to answer. Escape (when no palette or modal owns it) and Ctrl+C now cancel a running
turn and return to the prompt; Ctrl+C with no turn running — or a second press — quits, as does
Ctrl+Q. Shutdown tears the workers down and releases pending approvals with a bounded wait, on
quit, unmount, and interrupt alike.

- `dbe327e` feat(tui,loop): let the user interrupt a running turn, and quit without hanging

## Task 4 — Layout that survives a long answer

- `24ca29b` fix(tui): keep a long response from pushing the prompt off screen — the live stream
  region holds only the tail and is capped (`max-height: 40%`), so the prompt and the status
  footer stay on screen on a short terminal

## Task 5 — Test and lint cleanliness

- `67a79ca` fix(tui): stop CatalogPickerModal.on_mount raising NoMatches during shutdown
  (the catalog-picker flake)
- `56707ff` style(lint): clear the ruff backlog across tests and two src lines

## Task 6 — Release documentation and packaging

- `09c2203` docs(changelog): add the 0.6.0 release section
- `8b684d1` docs(readme): document the v0.6 TUI and refresh the status block
- `c578b8e` docs(architecture): sync the contract to v0.6.0
- `d67baf0` chore(release): bump to 0.6.0 and drop prompt_toolkit

---

## Carried in from pre-phase quick tasks

These landed between the Phase 4 close (`48a671b`) and the Phase 5 work, and ship in v0.6.0:

- **`260813-adr`** — `/model` catalog picker inserts the active provider prefix
  (`2a63ada`, `dc160eb`, `ee7d558`, `816b7f4`)
- **`260813-atc`** — catalog-validated provider fallback for bare `/model` refs
  (`659bad3`, `93de48d`, `300c215`, `30d6477`, `b30c221`, `911c01c`)
- **`260813-jfk`** — configurable HTTP timeouts for streaming providers; no
  `httpx.stream(timeout=None)` call site remains (`b2dc151`, `8c1ed1d`, `a7a63f4`, `6616da8`,
  `c600987`, `f4e17c2`, `f32a1cb`)

---

## Success criteria

1. **Lazy imports hold.** `textual`, `keyring`, and `tomlkit` are core-but-lazy — imported only
   inside function bodies on the TUI/secrets/config-write paths, so `agent86 run` and `--plain`
   never load them. `tests/tui/test_lazy_import.py` pins this. Met.
2. **Degradation is clean.** A missing or unstartable Textual falls back to the plain loop with
   a one-line note rather than a crash (`ui/repl.py: run_repl`); an absent keyring backend falls
   through to env-var key resolution silently. Met.
3. **The scripting contract is unchanged.** `run`, `run --json`, and the plain loop pass their
   tests as written; headless Textual `Pilot` tests in `tests/tui/` cover the core TUI flows.
   532 tests collected. Met.
4. **Docs and version shipped.** README, `docs/ARCHITECTURE.md`, and CHANGELOG updated;
   version bumped to 0.6.0 in `pyproject.toml` and `src/agent86/__init__.py`. Met.

**TUI-06: Complete.** Phase 5 complete — v0.6 milestone feature-complete at 5/5 phases.
