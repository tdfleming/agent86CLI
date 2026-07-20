# agent86 — Interactive Milestone (v0.6)

## What This Is

agent86 is a Python agentic harness on the command line: it connects to remote or local
models (Anthropic, OpenAI, OpenRouter, Groq, Ollama, llama.cpp) and lets them use tools,
skills, and MCP servers. This milestone makes the interactive experience **Claude-Code-like** —
a full-screen TUI with menus, in-CLI configuration of model connections and MCP servers, and a
status line that stays live while a turn is processing.

## Core Value

The user can run, configure, and steer the agent entirely from within an interactive terminal
app — switching models, wiring up MCP servers, and watching live progress — without hand-editing
TOML or restarting.

## Requirements

### Validated

<!-- Inferred from existing v0.5.8 code — shipped and relied upon. -->

- ✓ Interactive REPL (rich prompt_toolkit loop + plain fallback) — existing
- ✓ One-shot `run` command with `--json` for scripting — existing
- ✓ Layered TOML config (user → project → env → flags), Pydantic-validated — existing
- ✓ Live model switching via `/model` and `harness.set_model()` — existing
- ✓ MCP servers configurable via TOML (stdio/sse/http transports) — existing
- ✓ Persistent bottom status line at the prompt (model, ctx%, tokens, cost) — existing
- ✓ HITL approval gate with Shift+Tab mode cycle — existing
- ✓ Long-term memory, skills, guardrails, sandbox, flight-recorder trace — existing

### Active

<!-- This milestone. Hypotheses until shipped. -->

- [ ] **TUI-01**: Full-screen Textual app replaces the rich REPL as the default interactive UI
- [ ] **TUI-02**: Status line stays live and updates (model, ctx%, tokens, cost, phase) *during*
      turn processing, not just at the prompt
- [ ] **TUI-03**: Command palette with autocomplete for slash-commands
- [ ] **TUI-04**: Arrow-key selectable menus/modals for interactive choices
- [ ] **MODEL-01**: Add / switch / test model providers and models from within the CLI
- [ ] **MODEL-02**: Config changes written back to `~/.agent86/config.toml` non-destructively
- [ ] **SEC-01**: API keys stored in the OS keyring (env vars still take precedence)
- [ ] **MCP-01**: Add / remove / enable / test MCP servers from within the CLI, with connection
      validation

### Out of Scope

- Retaining the legacy `rich_loop` long-term — replaced by TUI + plain loop (two loops, not three)
- Storing secrets in plaintext config or a hand-rolled encrypted file — keyring only
- Rewriting the harness / cognitive loop — this milestone is a presentation + config-write layer
- Web or GUI front-ends — terminal only

## Context

- **Codebase**: `src/agent86/` — key modules for this milestone are `cli.py` (Typer surface),
  `ui/repl.py` (the two loops + threaded turn bridge), `ui/status.py` (`StatusState`,
  `format_status_line` — already has an unused `working`/`phase` branch), `config.py` (read-only
  today), `cognitive/base.py` + provider modules (each reads `os.getenv(api_key_env)` directly).
- **The turn bridge already exists**: `_run_turn_rich` runs `harness.run_turn()` (a sync
  generator) in a worker thread, drains a queue, and blocks the worker on a `threading.Event`
  for approvals. The TUI reuses this exact pattern, posting Textual messages instead of printing.
- **Secret seam**: providers call `os.getenv(config.api_key_env)`. A single
  `resolve_api_key(provider, pconf)` helper (env → keyring) is the only change needed to their
  key lookup.
- **Config is read-only**: `config.py` uses `tomllib`. Writing back non-destructively (preserving
  the comments already in user configs) needs `tomlkit`.

## Constraints

- **Performance**: Core deps are deliberately light so `agent86` starts fast. New deps
  (Textual, keyring, tomlkit) MUST be lazy-imported — `run` (one-shot) and `--plain` must not
  import them, and cold-start for scripting must not regress.
- **Compatibility**: The plain loop and `run --json` are the scripting/CI contract and must keep
  working unchanged. keyring absence (headless/CI) must silently fall through to env vars.
- **Tech stack**: Python ≥3.11, Textual (TUI), keyring (secrets), tomlkit (config write-back),
  prompt_toolkit (retained for plain loop), Rich, Typer, Pydantic v2.
- **Platform**: Primary dev/test on Windows 11 (console quirks already handled via UTF-8
  reconfigure in `cli.py`); must also work on macOS/Linux.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Full-screen **Textual** TUI (vs prompt_toolkit Application or incremental Rich) | Most Claude-Code-like; live footer during processing falls out of the async event loop | — Pending |
| Secrets in **OS keyring** (vs env-only or encrypted file) | Safe default, no hand-rolled crypto, env still wins for CI | — Pending |
| Config writes default to **user** scope (`~/.agent86`), project toggle offered | Applies across projects; repo-specific settings opt-in | — Pending |
| New deps **lazy-imported**; Textual a core-but-lazy dep | Preserve fast cold-start for `run`/`--plain` | — Pending |
| Reuse existing threaded turn bridge; post Textual messages | Approval + streaming already solved; don't re-derive | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-19 after initialization*
