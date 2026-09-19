---
phase: 06-trustworthy-harness
subsystem: cognitive/orchestration/guardrails/tools/security
tags: [pricing, cost-cap, retry, resilience, egress, redact, ssrf, sandbox, mcp, config, subagents]
requirements: [REL-01, REL-02, REL-03, REL-04, REL-05, SEC-02, SEC-03, SEC-04]
status: complete
completed: 2026-09-19
---

# Phase 6 — Trustworthy Harness

**Goal:** close the gap between what the harness *reports* and what is true, and between what it
*claims* to defend and what it defends.

**Requirements:** REL-01 (pricing), REL-02 (config validation), REL-03 (loop resilience +
retries), REL-04 (egress redact), REL-05 (sub-agent accounting), SEC-02 (`web_fetch` SSRF),
SEC-03 (sandbox environment + process tree), SEC-04 (MCP environment).

Like Phase 5, this phase was executed as a review-driven pass rather than a numbered plan set:
every item was a finding from the v0.6.0 release review recorded in `PROJECT.md` § "Next
milestone candidates", not new surface area. Nothing here changes the scripting contract —
`run`, `run --json`, and `--plain` are untouched. Work is grouped below by workstream; commits
are listed oldest-first within each group.

---

## Workstream 1 — The cost meter is real (REL-01)

`cognitive/pricing.py` shipped with an empty `PRICES` dict, so `estimate_cost` always returned
`0.0`: `limits.max_cost_usd` was unreachable dead code, and `/cost` and the status footer read
`$0.0000` no matter what a turn spent. The table is now populated in USD per million tokens
(Anthropic ids and rates from the bundled `claude-api` skill's model table, cached 2026-06-24;
OpenAI from developers.openai.com pricing, fetched 2026-09-19), and the three possible outcomes
are kept distinct instead of collapsing onto zero — **priced**, **local** (`Price.source ==
"local"`; Ollama and llama.cpp really are free), and **unknown** (`None`, rendered as
`cost n/a (unpriced model)`). Groq and OpenRouter are deliberately unpriced: OpenRouter ids are
`vendor/model` with per-route pricing that cannot be derived from the id, and unknown beats
wrong. `lookup` tries the full `provider:model` ref, then the bare id, then a *dated-snapshot*
prefix — restricted to a dated suffix on purpose, since a loose longest-prefix rule would price
`gpt-5.6-sol` off the `gpt-5` entry. `[pricing.models]` overrides reach the module-level table
through a `Config` post-validation hook, because providers price usage deep inside a stream with
no access to the resolved config. `Usage.cost_usd` stays a plain float — `types.py` is the
cross-tier lingua franca and was left untouched.

- `7c2efc2` feat(pricing): populate the price table so the cost cap is real
- `fd02c44` fix(ui): give the status line the full provider:model ref for pricing — `format_cost`
  can only tell priced from free-local from unpriced given a full ref, and the plain REPL was
  setting the bare model id, so an Ollama user read "cost n/a" where `$0.0000` is the truth

## Workstream 2 — Config is a contract, not a suggestion (REL-02)

`model.router`, `sandbox.mode`, `guardrails.ingress` and `guardrails.egress` were plain `str`, so
`egress = "redcat"` validated fine and silently turned a safety switch off — the worst available
failure mode for a guardrail. They are `StrEnum`s now (as `ApprovalMode` already was), chosen
specifically over `(str, Enum)` so every existing `== "triage"` / `== "docker"` / `== "off"`
comparison and every f-string rendering keeps working, and `model_dump(mode="json")` still emits
plain strings so `config_writer`'s tomlkit round-trip is unaffected (pinned in both directions by
a regression test). The same commit lands the fields the rest of the milestone reads:
`providers.*.max_retries` (2), `agents.max_steps` (8), `tools.web_allow_private` (false),
`sandbox.env_passthrough` (empty list) — names only, values read from the parent environment at
spawn time, so the "no secrets in config" rule holds — and `limits.tool_timeout_s` (60).

- `7e65fb8` feat(config): make mode fields enums and add the v0.7 shared contract fields
- `ad56066` fix(circuit): treat `max_steps=None` as "use limits.max_steps", not falsy — the
  contract the loop needs as the hard-coded caps come out: `None` means the user's budget *is*
  the budget, an explicit number is clamped with `min` so a sub-agent can tighten but never
  widen it, and an explicit `0` trips immediately instead of silently becoming 40

## Workstream 3 — The loop survives a bad provider (REL-03)

A `ProviderError` — or a raw `httpx.RemoteProtocolError` / `json.JSONDecodeError` from a
truncated SSE or NDJSON line — escaped `run_turn` *after* the user message had been appended: no
abort, no `turn_end`, nothing persisted, so the session was unresumable and the trace showed a
turn that started and never ended. Any exception in the model-call stream now aborts the turn
(ERROR phase, `turn_end status="error"`, persisted) before being re-raised. Underneath that,
`cognitive/retry.py` is the single place that decides whether a failure is worth another attempt:
retryable statuses (429/500/502/503/504) and transport errors, exponential backoff with equal
jitter, `Retry-After` as delta-seconds or HTTP-date (both clamped), and a budget from
`providers.<name>.max_retries`. Two invariants hold it honest — nothing is retried once a delta
has been yielded (a second attempt would duplicate text the user has already seen), and the
Anthropic provider passes `max_retries` to the SDK client rather than wrapping a client that
already retries.

- `1d24d31` fix(loop): never leave a turn dangling when a provider stream fails
- `6bddd04` feat(cognitive): retry transient provider failures with backoff
- `3f37105` fix(tools): tell the model its tool-call JSON was malformed — an unparseable argument
  string became an empty object, so the validator answered "field required" and sent the model
  chasing a phantom missing field for several steps; the raw text now rides a sentinel key and
  the orchestrator (and the sub-agent loop) return a precise "invalid JSON in tool arguments"
  error before the registry, the approval gate, or any tool sees it
- `2ea8642` fix(router): invalidate the provider cache when config changes — a new key or
  `base_url` kept hitting the old endpoint for the rest of the session, so the change looked like
  it had silently done nothing

## Workstream 4 — Redact actually redacts (REL-04)

The egress inspection computed a redacted copy and threw it away: the raw text had already been
streamed delta by delta, and the raw text was what got stored in the assistant message and the
episodic outcome. "redact" was, in practice, "warn". In redact mode the step's text deltas — and
the terminal done delta, whose order consumers rely on — are buffered and replayed from the
*inspected* text, so the secret is never shown, never persisted, and never recalled later; a
cancelled turn still gets its buffered partial, redacted. `warn`/`off` keep streaming live.
Tool-call arguments are scanned in both `warn` and `redact`
(`guardrail stage="egress_tool_args"`): a model that reads a key from a file and posts it to a URL
never puts it in its prose. The call is recorded, not blocked — the approval gate is what stops
side effects, and rewriting arguments would hand the tool something the model never asked for.

- `4ac84ce` fix(guardrails): make egress redact mode actually redact

## Workstream 5 — A real step budget, and accountable sub-agents (REL-03, REL-05)

`_MAX_TURN_STEPS = 12` was handed to every turn's `CircuitBreaker`, which takes the *minimum* of
it and `limits.max_steps` — so the configured budget (default 40) never applied and a user who
raised it watched a long task die at 12 anyway. The constant is gone. Sub-agents were the other
unbounded corner: a hard-coded 8 steps, no context trimming, and their tokens billed to nobody.
They now take `agents.max_steps`, run their messages through the parent's `WorkingMemory` with the
system prompt held out of the trim, inherit the parent's compiled system prompt and skills list
(they were previously offered `use_skill` with no skills to call it with), record `model_call`
events tagged with role and depth, and return their `Usage`. `spawn_subagent` accumulates that
usage on the harness and `run_turn` folds it into the step and the breaker's **cost** after each
tool call — cost only, never `record_step`, because a sub-agent is not one of the parent's model
calls and must not shrink the parent's step budget. The `delegate` tool's `str -> str` contract is
unchanged.

- `9fa1519` fix(orchestration): drop the hidden 12-step cap and make sub-agents accountable

## Workstream 6 — Security: what the model's tools can reach (SEC-02, SEC-03, SEC-04)

Four independent holes, all of them "the harness defends less than it claims".

- `8a0d97b` feat(security): SSRF guard, redirect re-vetting and body cap for web_fetch —
  **SEC-02.** A model-chosen URL could read cloud metadata (`169.254.169.254`), the user's own
  Ollama on localhost, or any RFC1918 host, and httpx followed redirects automatically so a public
  host could bounce the fetch into the private network. Every hop is now vetted before a
  connection: `http`/`https` only, all A/AAAA answers resolved and refused when loopback, private,
  link-local, multicast, reserved or unspecified (IPv4-mapped, 6to4 and Teredo unwrapped first),
  redirects followed manually with a bound of 5, the body streamed and stopped at 2 MB *before*
  decoding, and a textual content type required. Refusals are structured `ToolResult` errors
  naming the reason and the `tools.web_allow_private` escape hatch. The tool deliberately stays
  `side_effecting=False` — the guard, not the approval gate, is the mitigation.
- `7b5cb63` fix(sandbox): cross-platform env allowlist, opt-in passthrough, honest tool timeout —
  **SEC-03.** The allowlist was Windows-only, so on macOS/Linux every tool subprocess lost `HOME`,
  `USER`, `LOGNAME`, `SHELL`, `TMPDIR`, `TERM`, the locale and `XDG_*` families and the CA-bundle
  vars, which *breaks* git, pip and npm rather than merely constraining them. Adds the POSIX set
  and the `LC_*`/`XDG_*` prefixes, keeps the Windows set, and honours `sandbox.env_passthrough` —
  with credential-looking names (`*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*API_KEY*`, `*_KEY`) refused
  even when explicitly listed. Also switches the per-tool budget to `limits.tool_timeout_s`
  instead of the old derived value, which silently shortened every tool timeout for anyone who
  lowered their run budget.
- `6479ad0` fix(sandbox): kill the whole process tree and the container on timeout — **SEC-03.**
  A timed-out tool only lost its direct child; `npm test` or any command that spawns workers left
  them running, holding ports and pipes. Commands now start in their own process group
  (`CREATE_NEW_PROCESS_GROUP` / `start_new_session`) and the group is killed (`taskkill /T /F` or
  `killpg`) with a bounded pipe drain. Docker had the same hole a level up — killing the
  `docker run` client leaves the container alive and `--rm` never fires — so each run gets a
  unique `--name agent86-<uuid>` and a timeout follows up with `docker kill`. stdin is closed
  (EOF) rather than inherited, so a command that reads stdin fails fast.
- `a17a484` fix(mcp): scrub the environment handed to stdio servers, and accumulate notes —
  **SEC-04.** A stdio server that declared any env var received the whole host environment (every
  API key on the machine) merged with its own `env`, handed to a third-party subprocess. It now
  gets `SandboxPolicy.scrubbed_env()` with the server's own `env` layered on top. The same commit
  fixes the `mcp` 2.0 `inputSchema` to `input_schema` rename (the old attribute would have raised
  `AttributeError` at mount time against any real 2.x server), stops approval-gating tools
  annotated `readOnlyHint`, accumulates `start()` notes so every failing server is reported rather
  than only the last, resets state in `close()` so a later `start()` actually reconnects, and
  builds the streamable-HTTP client with the SDK's own `create_mcp_http_client`.

## Workstream 7 — Tool registry visibility

- `15d62b4` feat(tools): record and log tool-name collisions at startup — a tool whose name was
  already taken was dropped by a bare `except ValueError: pass`, so a user whose two MCP servers
  expose the same name (or whose server shadows a built-in) just saw a tool that never worked.
  Bulk registration keeps the first, appends the loser to `registry.collisions`, and warns
  through the module logger (naming the 64-character truncation when the clash is a truncation
  artefact). The strict `register()` still raises, so `add_mcp_server` keeps reporting collisions
  on an explicit add.

## Workstream 8 — TUI type holes with real crashes behind them

- `3b75b24` fix(tui): close six mypy type holes in the TUI app shell — one of them was a genuine
  crash: a key-entry modal that resolved with no pending provider row raised `AttributeError`.
  Modal dismissal callbacks now accept `None`, so a cancel reads as a cancel.
- `9a5aa0e` test(tui): cover the no-pending-row and None-dismissal guards — three Pilot tests for
  the crash-shaped half: a key entered with no row in flight is discarded (never tested, never
  echoed to the transcript), and `_on_test_done(None)` / `_on_mcp_test_done(None)` push no
  `SaveDiffModal` and clear the in-memory secret rather than storing it.

---

## Carried in from the v0.6.0 release tail

Landed after the `0.6.0` bump (`ae00e8e`) and before this phase's work, and ships in v0.7.0:

- `b230909` docs(claude-md): prompt_toolkit is no longer part of the stack — the stack table
  still listed a dependency the 0.6.0 bump had dropped.

`fd02c44` (the status line's `model_ref`) is also a v0.6.0 follow-up, but it belongs to
Workstream 1 above: it is what makes the new price table visible to an Ollama user.

---

## Success criteria

1. **The cost meter is real.** `limits.max_cost_usd` trips on actual spend; priced models show
   dollars, local models show a *correct* `$0.0000`, unpriced models show
   `cost n/a (unpriced model)`; `[pricing.models]` overrides the built-in table. Met.
2. **Config validates.** A typo in any of the four mode fields raises a `ValidationError` naming
   the allowed values; the five new fields resolve with their defaults and survive the
   `config_writer` round-trip. Met.
3. **The loop is resilient.** Transient provider failures retry with backoff and `Retry-After`;
   nothing is retried after the first streamed delta; a non-retryable failure aborts the turn
   with `turn_end status="error"` persisted and a `ProviderError` surfaced; `limits.max_steps`
   is the only step budget. Met.
4. **Redact redacts.** Streamed text, the stored assistant message, and the episodic outcome all
   carry the inspected text; tool-call arguments are scanned as `egress_tool_args`. Met.
5. **Sub-agents are accountable.** Bounded by `agents.max_steps`, context-trimmed, and their
   usage and cost folded into the parent turn and the cost cap. Met.
6. **The security holes are closed.** `web_fetch` refuses private targets on every hop; tool and
   MCP subprocesses get a curated environment; a timed-out command takes its process tree and its
   container with it. Met.

**REL-01 · REL-02 · REL-03 · REL-04 · REL-05 · SEC-02 · SEC-03 · SEC-04: Complete.**
Phase 6 complete — the v0.7 Trustworthy milestone is feature-complete at 1/1 phase.

Known leftovers, none of them blocking, are in `docs/BACKLOG.md` § "v0.7 review leftovers".
