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

- ✓ **TUI-01**: Full-screen Textual app is the default interactive UI (transcript + input +
  footer, slash-command parity) — Phase 1
- ✓ **TUI-02**: Status bar stays live during turn processing (model/ctx%/tokens/cost/phase) — Phase 1
- ✓ **TUI-05**: Tool-approval requests use a modal dialog that unblocks the worker thread — Phase 1
- ✓ **TUI-03**: Command palette with autocomplete for slash-commands (declarative `COMMANDS`
  registry + `/`-triggered `OptionList` dropdown) — Phase 2
- ✓ **TUI-04**: Arrow-key selectable menus/modals for interactive choices (`ModePickerModal`
  RadioSet + `ModelPickerModal` OptionList, chained from palette selection) — Phase 2
- ✓ Interactive REPL (rich prompt_toolkit loop + plain fallback) — existing
- ✓ One-shot `run` command with `--json` for scripting — existing
- ✓ Layered TOML config (user → project → env → flags), Pydantic-validated — existing
- ✓ Live model switching via `/model` and `harness.set_model()` — existing
- ✓ MCP servers configurable via TOML (stdio/sse/http transports) — existing
- ✓ Persistent bottom status line at the prompt (model, ctx%, tokens, cost) — existing
- ✓ HITL approval gate with Shift+Tab mode cycle — existing
- ✓ Long-term memory, skills, guardrails, sandbox, flight-recorder trace — existing
- ✓ **MODEL-01**: Add / switch / test model providers and models from within the CLI
  (`/config model` manager, key-entry + connection-test modals, live provider catalogs) — Phase 3
- ✓ **MODEL-02**: Config changes written back to `~/.agent86/config.toml` non-destructively
  (`config_writer.py` on tomlkit, with a save-diff confirmation modal) — Phase 3
- ✓ **SEC-01**: API keys stored in the OS keyring, env vars still take precedence; keys never
  reach the transcript or a traceback (`secrets.py` + `redact()`, fail-soft provider
  construction) — Phase 3
- ✓ **MCP-01**: List / add / remove / enable / disable MCP servers from within the app via
  `/config mcp`, with a pre-save connection test that starts the server for real and enumerates
  its tools; servers mount and unmount live in the running session (no restart) — Phase 4
- ✓ **TUI-06**: Plain loop and `run --json` keep working unchanged; Textual/keyring/tomlkit
  are core-but-lazy (never imported on the `run`/`--plain` path, pinned by
  `tests/tui/test_lazy_import.py`) and their absence degrades to the plain loop / env-var key
  resolution rather than crashing — Phase 5

### Active

<!-- This milestone. Hypotheses until shipped. -->

_None — all 10 v1 requirements validated; v0.6 shipped as v0.6.0 on 2026-09-19._
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
| Full-screen **Textual** TUI (vs prompt_toolkit Application or incremental Rich) | Most Claude-Code-like; live footer during processing falls out of the async event loop | ✓ Good (Phase 1) |
| Reuse threaded turn bridge: `run_worker(thread=True)` + `post_message`; Event-based approval (not `push_screen_wait`) | Approval + streaming already solved in `_run_turn_rich`; avoids under-documented async-worker API | ✓ Good (Phase 1) |
| Secrets in **OS keyring** (vs env-only or encrypted file) | Safe default, no hand-rolled crypto, env still wins for CI | ✓ Good (Phase 3) |
| Config writes default to **user** scope (`~/.agent86`), project toggle offered | Applies across projects; repo-specific settings opt-in | ✓ Good (Phase 3) |
| `UNRESOLVED` sentinel for "key not yet looked up" (vs `None`) | `None` conflates "absent" with "unresolved", which silently defeated keyring retest | ✓ Good (Phase 3) |
| Per-family **capabilities seam** gates sampling params, with self-correcting retry | Providers reject params per model family; one declarative table beats scattered conditionals | ✓ Good (Phase 3) |
| Redact-and-sever on provider construction failure (`raise … from None`, no frame locals) | A traceback through key-handling code is a second, independent secret-leak path | ✓ Good (Phase 3) |
| New deps **lazy-imported**; Textual a core-but-lazy dep | Preserve fast cold-start for `run`/`--plain` | — Pending |
| Reuse existing threaded turn bridge; post Textual messages | Approval + streaming already solved; don't re-derive | — Pending |
| Single declarative `COMMANDS` registry backs dispatch, `/help`, and the palette | One source of truth — help and palette can't drift from real commands | ✓ Good (Phase 2) |
| Enter-routing "Approach B": bind/unbind priority `enter` only while palette open (spike-proven) | Permanent priority `enter` swallows `Input.Submitted`; arrow/escape need `SkipAction` fallthrough too | ✓ Good (Phase 2) |
| Picker callbacks synthesize `/mode`/`/model` lines through `handle_command` (not direct state mutation) | Keeps `_dispatch_line` the single execution path for typed + picker input | ✓ Good (Phase 2) |

## Next milestone candidates

v0.6 made the harness *usable*. The natural v0.7 theme is making it **trustworthy** — the
places where the harness currently reports or defends less than it claims:

- **Populate the pricing table** — the cost figure in the status footer and `/cost` is only as
  honest as `cognitive/pricing.py`
- **Wire egress redact** — the redact mode exists but isn't on the output path
- **Provider-stream error handling + retries/backoff** — a mid-stream failure should degrade,
  not end the turn; rate limits deserve backoff
- **MCP subprocess env scrubbing** — stdio servers currently inherit more environment than the
  sandbox's own tool subprocesses do
- **POSIX env allowlist** — bring the non-Windows sandbox env policy up to the same allowlist
  discipline
- **`web_fetch` private-address guard** — block loopback/link-local/RFC1918 targets (SSRF)
- **Remove the 12-step hard cap** — `[limits] max_steps` should be the only bound
- **Config enums** — mode/router/transport string fields should be enums, validated once
- **Sub-agent usage accounting** — delegated turns should roll their tokens and cost up into the
  session totals

Deferred beyond v0.7: see `docs/BACKLOG.md` § "Review findings 2026-09-19".

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
*Last updated: 2026-09-19 after Phase 5 (Packaging & Hardening) — TUI-06 validated; the v0.6
Interactive milestone is complete (5/5 phases, 10/10 requirements) and released as v0.6.0.*
