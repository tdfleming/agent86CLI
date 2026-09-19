# agent86 — Trustworthy Milestone (v0.7)

## What This Is

agent86 is a Python agentic harness on the command line: it connects to remote or local
models (Anthropic, OpenAI, OpenRouter, Groq, Ollama, llama.cpp) and lets them use tools,
skills, and MCP servers. v0.6 made the harness **usable** (a full-screen TUI with menus,
in-CLI configuration, a live status line). v0.7 makes it **trustworthy**: the places where the
harness reported or defended *less than it claimed* — a cost meter backed by an empty price
table, a `redact` mode that only warned, a provider failure that vanished mid-turn, tool and
MCP subprocesses inheriting every key on the machine, a `web_fetch` that would happily read
cloud metadata.

## Core Value

What the harness reports is true and what it claims to defend, it defends. The cost meter is
real enough to trip a cap (and says `n/a` when it doesn't know), a transient provider failure
retries instead of ending the turn, a failed turn ends cleanly and resumably, and the model's
tools cannot reach the private network or the user's secrets.

Carried from v0.6: the user can run, configure, and steer the agent entirely from within an
interactive terminal app — switching models, wiring up MCP servers, and watching live progress —
without hand-editing TOML or restarting.

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

<!-- v0.7 "Trustworthy harness" — Phase 6. Shipped as v0.7.0 on 2026-09-19. -->

- ✓ **REL-01**: The cost meter is real — a built-in USD price table (Anthropic, OpenAI) plus
  `[pricing.models]` overrides, full-ref → bare-id → dated-snapshot lookup, local providers
  priced at a *correct* zero, unpriced models shown as `cost n/a (unpriced model)` rather than
  `$0.0000`, and `limits.max_cost_usd` consequently able to trip — Phase 6
- ✓ **REL-02**: Config mode fields are validated enums (`model.router`, `sandbox.mode`,
  `guardrails.ingress`, `guardrails.egress`) so a typo fails loudly instead of silently
  disabling a guardrail; the v0.7 shared contract fields land with them
  (`providers.*.max_retries`, `agents.max_steps`, `tools.web_allow_private`,
  `sandbox.env_passthrough`, `limits.tool_timeout_s`) — Phase 6
- ✓ **REL-03**: The loop survives a provider failure — a failed or malformed stream aborts the
  turn (ERROR phase, `turn_end status="error"`, persisted) and surfaces a `ProviderError`
  instead of leaving an unresumable session; transient failures retry first via
  `cognitive/retry.py` (backoff + jitter, `Retry-After`, never after the first streamed delta);
  and `limits.max_steps` is the only step budget — Phase 6
- ✓ **REL-04**: `guardrails.egress = "redact"` redacts what is streamed *and* what is stored,
  and tool-call arguments are scanned (`guardrail stage="egress_tool_args"`) — Phase 6
- ✓ **REL-05**: Sub-agents are bounded and accounted for — `agents.max_steps`, context trimming
  through the parent's working memory, inherited system prompt and skills list, `model_call`
  events, and usage/cost folded into the parent turn and the cost cap — Phase 6
- ✓ **SEC-02**: `web_fetch` cannot be used as an SSRF pivot — scheme restriction, DNS-resolved
  refusal of loopback/private/link-local/reserved addresses (IPv4-mapped, 6to4, Teredo
  unwrapped), manually followed and re-vetted redirects capped at 5 hops, a 2 MB body cap
  before decoding, a content-type check, and the `tools.web_allow_private` escape hatch —
  Phase 6
- ✓ **SEC-03**: The sandbox environment allowlist is cross-platform (POSIX set alongside the
  Windows one, `LC_*`/`XDG_*` families, CA-bundle vars), `sandbox.env_passthrough` extends it by
  name only, credential-looking names are refused even when named, and a timed-out command's
  whole process tree — and its Docker container — is killed — Phase 6
- ✓ **SEC-04**: MCP stdio subprocesses get the scrubbed sandbox environment plus their own
  declared `env`, instead of the full host environment — Phase 6

### Active

<!-- This milestone. Hypotheses until shipped. -->

_None — all 10 v0.6 requirements and all 8 v0.7 requirements validated; v0.7 shipped as v0.7.0
on 2026-09-19._

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
  Rich, Typer, Pydantic v2 (prompt_toolkit was dropped in v0.6.0; the plain loop uses stdlib
  `input()`).
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
| Three pricing outcomes (priced / local / **unknown**) instead of collapsing onto `0.0` | A cost meter that shows a paid call as free is worse than one that admits it doesn't know; `n/a` is honest, `$0.0000` is a lie | ✓ Good (Phase 6) |
| Groq and OpenRouter deliberately left unpriced | OpenRouter ids are `vendor/model` with per-route pricing not derivable from the id; unknown beats wrong | ✓ Good (Phase 6) |
| Dated-snapshot prefix matching only, never longest-prefix | A loose rule would price `gpt-5.6-sol` off the `gpt-5` entry | ✓ Good (Phase 6) |
| `StrEnum` for the mode fields, not `(str, Enum)` | Every existing `== "triage"` comparison and f-string rendering keeps working; `model_dump(mode="json")` stays a plain string so the tomlkit round-trip is unaffected | ✓ Good (Phase 6) |
| Never retry once a delta has been streamed | A second attempt would duplicate text the user has already read; surface a `ProviderError` instead | ✓ Good (Phase 6) |
| Anthropic retries via the SDK's own `max_retries`, not a wrapper | Don't stack a retry loop on a client that already retries | ✓ Good (Phase 6) |
| Egress scans tool-call arguments but never rewrites them | The approval gate stops side effects; rewriting would hand the tool something the model never asked for | ✓ Good (Phase 6) |
| Sub-agent usage folds into the parent's **cost**, never `record_step` | A sub-agent is not one of the parent's model calls and must not shrink its step budget | ✓ Good (Phase 6) |
| `env_passthrough` refuses credential-looking names even when explicitly listed | An allowlist entry must not become a way to hand tool subprocesses the key that pays for the model | ✓ Good (Phase 6) |
| `web_fetch` keeps `side_effecting = False`; the SSRF guard is the mitigation | A read is a read; approval-gating every fetch would train users to approve blindly | ✓ Good (Phase 6) |

## Next milestone candidates

Every v0.7 candidate shipped. v0.6 made the harness usable and v0.7 made it honest; the natural
**v0.8** theme is **context & cost** — spending the context window and the token budget well,
rather than merely reporting them accurately:

- **Context compaction / summarization** — working memory trims by sliding window; a long
  session should summarize the dropped span instead of forgetting it outright
- **Prompt caching** — the Anthropic provider marks no cache breakpoints, so a stable system
  prompt + tool-schema block is re-billed every turn
- **Parallel tool calls** — a turn's independent tool calls execute one at a time
- **`max_tokens` continuation** — a response truncated at the output cap just ends; detect the
  stop reason and continue
- **Per-turn cost in the footer and `/cost`** — the session total is there; the turn's own spend
  is the number a user watches while deciding whether to interrupt

Deferred further: see `docs/BACKLOG.md` § "Review findings 2026-09-19" (TUI, skills,
observability, release) and § "v0.7 review leftovers".

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
*Last updated: 2026-09-19 after Phase 6 (Trustworthy Harness) — REL-01…REL-05 and SEC-02…SEC-04
validated; the v0.7 Trustworthy milestone is complete (1/1 phase, 8/8 requirements) and released
as v0.7.0. The v0.6 Interactive milestone closed at 5/5 phases and 10/10 requirements.*
