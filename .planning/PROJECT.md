# agent86 — Context & Cost Milestone (v0.8)

## What This Is

agent86 is a Python agentic harness on the command line: it connects to remote or local
models (Anthropic, OpenAI, OpenRouter, Groq, Ollama, llama.cpp) and lets them use tools,
skills, and MCP servers. v0.6 made the harness **usable** (a full-screen TUI with menus,
in-CLI configuration, a live status line). v0.7 makes it **trustworthy**: the places where the
harness reported or defended *less than it claimed* — a cost meter backed by an empty price
table, a `redact` mode that only warned, a provider failure that vanished mid-turn, tool and
MCP subprocesses inheriting every key on the machine, a `web_fetch` that would happily read
cloud metadata. v0.8 makes it **deliberate about what it spends**: v0.7 taught the harness to
report its context and cost accurately, and the numbers it then reported were bad — a flat 8000-token
conversation budget on a 200k window, the oldest turns silently forgotten, a stable prompt prefix
re-billed every turn, a long answer cut off mid-sentence, and five file reads taken one at a time.

## Core Value

The context window and the token budget are spent well, not merely measured accurately. The
conversation is budgeted against the model's real window, what no longer fits is summarized rather
than forgotten, a truncated answer continues, independent reads run together, the stable prompt
prefix is cached and priced as cached, and every turn ends with one line saying what it cost.

Carried from v0.7: what the harness reports is true and what it claims to defend, it defends.
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

<!-- v0.8 "Context & cost" — Phase 7. Shipped as v0.8.0 on 2026-09-19. -->

- ✓ **CTX-01**: The conversation is budgeted against the model's **real** context window —
  `capabilities.context_window_for` (a `[model.context_window]` override → the provider where the
  server owns the window → a built-in family table → 8192), minus the system prompt and tool
  schemas, minus `limits.context_reserve_tokens`, minus the output cap; recomputed before every
  request and shared with sub-agents; `limits.max_context_tokens` demoted from *the budget* (a flat
  8000) to an optional hard cap defaulting to `0` = none; `count_tokens` counts tool-call arguments
  and names — Phase 7
- ✓ **CTX-02**: The span that no longer fits is **summarized, not forgotten** —
  `[limits] compaction = "summarize"` writes a GOAL/DECISIONS/FACTS/OPEN digest with the cheap
  route model, merged into the next user message under
  `[Conversation summary — earlier turns compacted]`; tool_call/result pairs are never split, the
  last 6 messages and the current turn are never compacted, the compacted history is persisted for
  resume and the originals archived to episodic memory, and a failure falls back to `drop` rather
  than raising — Phase 7
- ✓ **CTX-03**: A completion that stops for length continues — `stop_reason == "max_tokens"` with
  no tool calls continues up to 3 times per turn, each a full breaker step, stitched into one
  assistant message with a `continuation` event — Phase 7
- ✓ **CTX-04**: A step's read-only tool calls run **in parallel** — approvals resolved
  sequentially first, then reads on a ≤4-worker pool, then side-effecting calls one at a time in
  model order; results observed in call order; `Tool.parallel_safe` opts a tool out (`delegate`
  does); cancellation gives pending calls a `Not executed: cancelled` result;
  `[limits] parallel_tools` — Phase 7
- ✓ **COST-01**: The stable prompt prefix is **cached** — Anthropic `cache_control` breakpoints on
  the last tool and the system block, placed only above that model's minimum cacheable length
  (a per-family table, since the minimum is not monotonic across generations),
  `[providers.<name>] prompt_cache` to disable, and `Usage.cache_read_tokens` /
  `cache_creation_tokens` carrying the breakdown provider-agnostically — Phase 7
- ✓ **COST-02**: Cache traffic is **priced as cache** — reads at 0.1×, 5-minute writes at 1.25×,
  the uncached remainder at the input rate, with per-model overrides and optional explicit
  per-mtok cache rates, so `limits.max_cost_usd` stops being wrong in both directions — Phase 7
- ✓ **COST-03**: Every turn ends with **one line saying what it cost** — `TurnSummary` on
  `state.last_turn` (tokens incl. cache, cost, steps, tool calls, duration, compactions,
  continuations), published at turn start and closed on every exit, rendered identically on the
  TUI, the plain loop and `agent86 run`'s stderr, with an additive `turn` key in `run --json` —
  Phase 7

### Active

<!-- This milestone. Hypotheses until shipped. -->

_None — all 10 v0.6, all 8 v0.7 and all 7 v0.8 requirements validated; v0.8 shipped as v0.8.0
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
| The context window is resolved by a **capabilities seam**, not by the provider adapters | One lookup the loop, the budget and the ctx gauge all ask; two tables is how the gauge came to lie | ✓ Good (Phase 7) |
| For Ollama/llama.cpp the **provider** owns the window, not the model name | The server serves `num_ctx` / was launched with `-c`; guessing 131k from `llama3.1` hands the budget a number the server truncates | ✓ Good (Phase 7) |
| `max_context_tokens` demoted to an optional hard cap (`0` = none) rather than removed | An explicitly chosen budget is a legitimate preference; it just must not *be* the default budget | ✓ Good (Phase 7) |
| The summary rides on a **USER** message, not a new `Role` | Nothing for four provider adapters to learn; merged into the next user turn because consecutive user messages are a shape some providers reject | ✓ Good (Phase 7) |
| Compaction **never raises** — it falls back to the old drop | Losing the digest is a degradation; losing the turn is a failure | ✓ Good (Phase 7) |
| Approvals resolved sequentially *before* any parallel dispatch | The gate may prompt a human and must be asked exactly once per call; two prompts racing for one terminal is not untanglable | ✓ Good (Phase 7) |
| Reads in parallel, writes strictly sequential and in model order | Two writes could interleave edits to one file, and a write racing a read hands the model a half-written one; determinism is worth the latency | ✓ Good (Phase 7) |
| Results observed in **call** order regardless of completion order | The `TOOL` messages must line up with the assistant's `tool_calls` for every provider | ✓ Good (Phase 7) |
| Continuation is a **step the circuit breaker counts**, not a retry | A truncated answer that continues 3× really is 4 model calls, and the budget must see them | ✓ Good (Phase 7) |
| Cache-breakpoint eligibility estimated at ~4 chars/token, not via `count_tokens` | A round trip per turn to decide something whose only cost when wrong is an ignored marker | ✓ Good (Phase 7) |
| `Usage.input_tokens` is the whole prompt; cache fields are a breakdown *of* it | Anthropic reports the uncached remainder; left as-is, a well-cached turn would look like it barely used context | ✓ Good (Phase 7) |
| `TurnSummary` lives in `orchestration/state.py`, not `types.py` | It is an orchestration record, not part of the provider-agnostic lingua franca | ✓ Good (Phase 7) |
| `TurnSummary` published at turn **start**, duration stamped at every exit | A UI can watch it fill, and a turn that failed halfway still spent tokens | ✓ Good (Phase 7) |
| The footer sheds whole segments by priority; model/cost/mode/phase are never shed | They say what is running, what it costs, and whether it can act without asking — the quiet omission v0.7 exists to remove | ✓ Good (Phase 7) |

## Next milestone candidates

Every v0.8 candidate shipped. v0.6 made the harness usable, v0.7 made it honest, v0.8 made it
frugal; the natural **v0.9** theme is **coding-agent UX** — the transcript and the prompt doing
for a coding session what the TUI already does for a chat session:

- **Markdown rendering in the transcript** — model output is written as escaped plain text; code
  fences, lists, and tables deserve real rendering
- **Diff preview in the approval modal** — approving a `write_file`/`edit_file` should show the
  diff being approved, not just the tool name and arguments
- **Prompt history and multi-line input** — up-arrow recall and a soft-wrap composer
- **`@file` mentions** — path autocomplete in the prompt that inlines a file's content
- **Session picker** — sessions persist and resume, but only by id on the command line
- **Tool-call collapsing** — long tool observations folded to an expandable one-line summary
- **Agent Skills convention + `allowed-tools` enforcement** — a skill's declared tool allowlist is
  documentation today, not a gate

Then **v1.0** as the release milestone: an OTel exporter actually wired up, flight-recorder
redaction and rotation, and a PyPI publish workflow.

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
*Last updated: 2026-09-19 after Phase 7 (Context & Cost) — CTX-01…CTX-04 and COST-01…COST-03
validated; the v0.8 Context & Cost milestone is complete (1/1 phase, 7/7 requirements) and
released as v0.8.0. The v0.7 Trustworthy milestone closed at 1/1 phase and 8/8 requirements; the
v0.6 Interactive milestone at 5/5 phases and 10/10 requirements.*
