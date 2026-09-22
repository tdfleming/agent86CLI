---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: Interactive to Release
status: shipped
last_updated: "2026-09-22"
progress:
  total_phases: 9
  completed_phases: 9
  total_plans: 30
  completed_plans: 30
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-21)

**Core value:** A tagged release publishes itself, the trace is safe to leave on forever *and*
safe to hand to someone else, and the promises a script depends on are written down and enforced
— on top of v0.9's "usable for code", v0.8's "the context window and the token budget are spent
well", v0.7's "what the harness reports is true", and v0.6's "run, configure and steer the agent
entirely from the terminal app".
**Current focus:** v1.0 milestone complete (1/1 phase) — released as v1.0.0. The harness is
complete against `docs/ARCHITECTURE.md`.
**Next:** no milestone scoped — a **post-1.0 backlog**, in `docs/BACKLOG.md`. Nearest item is the
`Development Status` classifier flip to `5 - Production/Stable`, due in the first release after
1.0 is live on PyPI. Added 2026-09-22: seven **competitive gaps** (phases 999.1–999.7 in
`ROADMAP.md` § Backlog), ordered `grep`/`glob` → tool hooks → declarative sub-agents → plan-mode
gate, then git awareness / shell network control / injection classifier unordered. None outranks
MCP integration work.

## Milestone

**v1.0 — Release** (agent86 now at v1.0.0)
1 phase | 9 requirements (OBS-01…OBS-04, PKG-01, PKG-02, HARD-01…HARD-03) | 1 phase complete

Previous: **v0.9 — Coding-agent UX** — 1 phase, 8 requirements, complete, released as v0.9.0.
Before that: **v0.8 — Context & cost** — 1 phase, 7 requirements, released as v0.8.0;
**v0.7 — Trustworthy harness** — 1 phase, 8 requirements, released as v0.7.0; and
**v0.6 — Interactive** — 5 phases, 10 requirements, released as v0.6.0.

## Progress

| Phase | Status | Plans | Progress |
|-------|--------|-------|----------|
| 9 — Release | ● | n/a | 100% |

v0.9 (closed): 8 — Coding-Agent UX ● n/a.
v0.8 (closed): 7 — Context & Cost ● n/a.
v0.7 (closed): 6 — Trustworthy Harness ● n/a.
v0.6 (closed): 1 — TUI Skeleton + Live Status ● 5/5 · 2 — Command Palette + Menus ● 4/4 ·
3 — Secrets + Model Config ● 13/13 · 4 — MCP Config UI ● 8/8 · 5 — Packaging & Hardening ● n/a.

## Recent Activity

- 2026-09-21 — **Phase 9 (Release) complete; v1.0 milestone complete at 1/1 phase and released as
  v1.0.0.** Executed as a review-driven pass (see `phases/09-release/SUMMARY.md` for the
  commit-by-commit breakdown grouped by workstream). **OBS-01/OBS-02 the recorder:** every event
  now passes through `observability/redact.py` before it reaches the file — every string at any
  depth rewritten with the guardrail tier's *own* regexes (imported, never re-spelled) to
  `***REDACTED***`, and the big free-text fields clipped to `max_field_chars` with truncation
  inherited into anything nested inside them, because the model chooses those key names. It never
  raises: a redaction failure degrades to the untouched event, since a trace that drops events is
  worse than a trace with a long line in it. The live file is capped at `max_trace_bytes` and
  rotates *between* events (flush, then rename, retried for the Windows `PermissionError` a tail
  or a scanner causes), and reads stream generation-by-generation so a filtered `-n` means N
  *matching* events. **OBS-03 the exporter:** the tracer used to call `trace.get_tracer`, which
  hands back the no-op global provider unless something else installed one — so with the extra
  installed and the switch on, spans were created and dropped. It now builds its own
  `TracerProvider` (Resource, an exporter chosen by `otel_exporter`, a `BatchSpanProcessor` flushed
  from `Harness.close()`), honours the standard `OTEL_*` env vars with `otel_endpoint` as the
  config override, and deliberately does **not** call `set_tracer_provider`: agent86 is importable
  inside a host that owns its tracing, and stealing the global provider would be a side effect of
  an import. **OBS-04 reading it back:** `trace export` (`-f jsonl|json|otlp-json`, the last
  reconstructing a span tree with derived rather than random span ids) and `trace show` with
  `-k/--kind`, `--since`, token/cost columns and totals, both over one filter-before-limit reader.
  **PKG-01/PKG-02 shipping it:** complete PyPI metadata and a real `LICENSE`, an allowlisted sdist,
  `tests/packaging/` asserting the built wheel behind a `packaging` marker (excluded by default;
  CI's `package` job runs it on Ubuntu *and* Windows), and `release.yml` on `v*` — pre-flight,
  build, `twine check`, packaging tests, trusted publishing through the `pypi` environment, then a
  GitHub Release carrying that version's CHANGELOG section. No token in the repo; `docs/RELEASING.md`
  is the procedure. **HARD-01/02/03 the edges:** the scripting contract stated by tests rather than
  inferred (the five `run --json` keys, stderr-on-failure, declined approvals when piped,
  `--session`, the lazy-import contract and a cold-start budget), subprocess smoke tests for every
  command surface under an empty HOME, error messages that name the fix (including a
  `MemoryStoreError` the harness degrades around instead of refusing to start), a session titled
  from the typed line rather than an inlined `@file` block, and a degradation matrix with one test
  per optional dependency.

- 2026-09-21 — **Phase 8 (Coding-Agent UX) complete; v0.9 milestone complete at 1/1 phase and
  released as v0.9.0.** Executed as a review-driven pass rather than a numbered plan set (see
  `phases/08-coding-agent-ux/SUMMARY.md` for the commit-by-commit breakdown grouped by
  workstream). **UX-01/UX-02 the transcript:** the widget stays a `RichLog` — append-only, cheap
  to stream into, and what every other surface queries as `#transcript` — but the app now keeps an
  ordered list of *entries* beside it, any of which may change how it renders after it was first
  written, replayed into the log on a re-render. A reply streams as plain escaped text and is
  re-rendered once, as a single `rich.markdown.Markdown` document, when it completes; fenced code
  goes through `Syntax(word_wrap=True)`; Markdown never parses console markup, so `[/weird]` can
  neither raise `MarkupError` on the main thread nor vanish into a style tag; a reply with no
  Markdown structure is not re-rendered at all. A tool call became one block — `▸ name(args) →
  summary`, expandable with `Ctrl+O`/`Ctrl+Shift+O` to pretty-JSON arguments and the full result
  capped at 200 lines — fed from the session state through `turn_bridge` rather than from the
  delta lines, which also stopped tool results falling through to `TurnDelta` and reading as model
  speech. Not a Textual `Collapsible`: a `RichLog` renders to strips and cannot host interactive
  children. A failed turn now leads with the exception **type** and a dim
  `see agent86 trace show -s <session>`. **UX-03/UX-04/UX-05 the prompt and sessions:**
  `PromptInput` is a `TextArea` that keeps the `Input` interface, so it swapped in without
  reopening turn handling (Enter submits, Shift+Enter/Ctrl+J newline, Up/Down history from the
  first/last line, Escape clears, 8 rows before scrolling); `PromptHistory` is stdlib-only, follows
  bash's rules, degrades to "this session only" on a bad file, and is shared with the plain loop
  through `[ui] history_file`. `@path` mentions inline a file into the prompt, every path resolved
  through `SandboxPolicy.resolve_within` *before* it is opened and bounded by
  `[tools] mention_max_bytes`, with refusals carried in the prompt as well as shown. Sessions are
  titled from the first user message (once, on the first persist that can name them, asking the
  store first so compaction can't rename a conversation) and reachable via `/sessions`,
  `/resume [id]` on an 8-character prefix, and `SessionPickerModal`. **UX-06/TOOL-01 edits and
  approvals:** `edit_file` became exact-match with `old_string`/`new_string`/`replace_all`,
  refusals that name the match count, BOM and CRLF preserved by decoding and re-encoding in the
  tool, and a unified diff in the result; `Tool.preview` puts that diff (or the whole command,
  capped at 60 lines) in front of the approval on both interactive surfaces, with `ApprovalPreview`
  as a `str` subclass so the `(tool_name, preview) -> bool` contract stayed untouched.
  **SKILL-01 skills:** frontmatter now parses to the Agent Skills convention (a `---` on its own
  line, block scalars, space-delimited `allowed-tools`, PyYAML optional), discovery searches five
  roots first-root-wins with project roots resolved against an explicit workspace, `skill_roots()`
  feeds `default_policy` so bundled resources are readable, and `ToolRegistry.dispatch` **refuses**
  anything outside a non-empty allowlist, with `clear_skill()` lifting the restriction at the end
  of every turn. The scripting contract is untouched: `run`, `run --json` and `--plain` are
  unchanged, and `tui/mentions.py` imports no Textual so the plain loop shares it for free.
  1100 tests collected.

- 2026-09-19 — **Phase 7 (Context & Cost) complete; v0.8 milestone complete at 1/1 phase and
  released as v0.8.0.** Executed as a review-driven pass rather than a numbered plan set (see
  `phases/07-context-and-cost/SUMMARY.md` for the commit-by-commit breakdown grouped by
  workstream). **CTX-01 real window budget:** `WorkingMemory` was constructed with
  `limits.max_context_tokens` — a flat 8000 for every model, which wasted ~96% of a 200k Claude
  window and overspent a 4k local one, and which ignored the system prompt and tool schemas that
  are in every request before any history. New `cognitive/capabilities.context_window_for`
  resolves the window (a `[model.context_window]` override → the provider where the *server* owns
  the window, Ollama's `num_ctx` and llama.cpp's undiscoverable `-c` → a built-in family table,
  Claude 4.x/5.x 200k, `gpt-5` 400k, `gpt-4.1` 1,047,576, `gpt-4o` 128k, o-series 200k, common
  open-weights ids → 8192), and `memory.working.conversation_budget` derives window − (system +
  tool schemas) − `context_reserve_tokens` − the output cap, with the reserve clamped to half the
  window, a floor, and `max_context_tokens` (now `0` = no cap) applied last as an optional hard
  cap. `Harness._context_budget` recomputes it before every request and publishes it on the shared
  `WorkingMemory` so sub-agents trim to the same number; `count_tokens` now counts tool-call
  arguments and names (a step whose payload was one large tool argument measured as zero).
  **CTX-02 compaction:** `[limits] compaction = "summarize"` replaces the oldest prefix with a
  GOAL/DECISIONS/FACTS/OPEN digest written by the cheap route model (else the current provider),
  carried on a USER message headed `[Conversation summary — earlier turns compacted]` and merged
  into the following user turn; tool_call/result pairs are never split, the last 6 messages and
  the current turn are never compacted, it runs at most once per step and never re-entrantly, and
  it never raises — a failed or empty summary falls back to `drop` and records
  `compaction status="failed" fallback="drop"`. The compacted history is persisted immediately so
  a resume sees it, and the originals are archived verbatim to episodic memory
  (`record_compaction`), held out of `recall`. **CTX-03 continuation:** `stop_reason ==
  "max_tokens"` with no tool calls continues up to 3 times per turn, each a full breaker step,
  stitched into one assistant message so neither partials nor the harness's continuation prompts
  enter the history; `continuation` event + `TurnSummary.continuations`. **CTX-04 parallel
  tools:** approvals for the whole step resolved sequentially first on the orchestrator's thread,
  then read-only calls on a `ThreadPoolExecutor(max_workers=min(4, n))`, then side-effecting calls
  one at a time in model order; results observed in call order; `Tool.parallel_safe` opts out
  (`delegate` does, because a nested loop has its own approval prompts); a mid-batch cancel gives
  pending calls a `Not executed: cancelled` result so no `tool_use` is left unanswered;
  `[limits] parallel_tools = false` restores the sequential path. **COST-01 prompt caching:**
  Anthropic `cache_control` on the last tool and the system block (the two stable prefixes),
  placed only above that model's minimum cacheable length — a per-family table, since the minimum
  is *not* monotonic (512 on the newest, 4096 on Opus 4.6/4.5 and Haiku 4.5) — estimated at ~4
  chars/token rather than a `count_tokens` round trip; `[providers.<name>] prompt_cache` disables
  it; `Usage.cache_read_tokens`/`cache_creation_tokens` carry the breakdown, with `input_tokens`
  kept as the whole prompt. **COST-02 cache pricing:** reads at 0.1×, 5-minute writes at 1.25×,
  the remainder at the input rate, per-model overrides and optional explicit per-mtok cache rates.
  **COST-03 per-turn line:** `TurnSummary` on `state.last_turn`, published at turn start and
  closed at every exit, rendered as `— 3 steps · 2 tools · 4.1k in / 612 out (1.9k cached) ·
  $0.0123 · 8.2s` on the TUI, the plain loop and `agent86 run`'s stderr through one formatter,
  with an additive `turn` key in `run --json`. Also: every provider honours `request.max_tokens`
  (OpenAI `max_completion_tokens` with a memoised one-shot fallback to `max_tokens`, Ollama
  `num_predict`, Anthropic defaulting to 8192 up from 4096, local-fronting adapters sending no cap
  unless configured); `types.StopReason` normalizes stop reasons across providers; the footer
  reads `tok <in>/<out> (cached)`, resolves its ctx gauge through the same
  `context_window_for` the budget uses, and sheds segments by priority to stay one row from 80
  columns (never shedding model, cost, mode or phase); `/cost` reports cache reads/writes and
  savings; and harness notices (`[compacted …]`, `[compaction failed …]`, `[continuation k/3]`)
  render dim and apart from model speech. Release: CHANGELOG `[0.8.0] - 2026-09-19`, README status
  block plus a new "Context management" section and an extended "Cost tracking",
  `docs/ARCHITECTURE.md` synced to 0.8.0 (§5 loop, §6 cognitive, §8 memory, §11 config, §15
  "not built" table), `docs/BACKLOG.md` pruned of what shipped, and the version bumped to 0.8.0 in
  `pyproject.toml` and `src/agent86/__init__.py`. 868 tests collected.

- 2026-09-19 — **Phase 6 (Trustworthy Harness) complete; v0.7 milestone complete at 1/1 phase
  and released as v0.7.0.** Executed as a review-driven pass rather than a numbered plan set
  (see `phases/06-trustworthy-harness/SUMMARY.md` for the commit-by-commit breakdown grouped by
  workstream). **REL-01 pricing:** `cognitive/pricing.py`'s `PRICES` dict was empty, so
  `estimate_cost` always returned `0.0` — `limits.max_cost_usd` was unreachable dead code and
  `/cost` read `$0.0000` forever. A built-in USD-per-million-tokens table (Anthropic from the
  Claude API reference, OpenAI from developers.openai.com fetched 2026-09-19) plus
  `[pricing.models]` overrides via a `Config` post-validation hook, full-ref → bare-id →
  dated-snapshot lookup, `ollama`/`llamacpp` priced at a *correct* zero, Groq/OpenRouter
  deliberately unpriced and shown as `cost n/a (unpriced model)`; the plain REPL now sets
  `status.model_ref` so the lookup gets a full ref. **REL-02 config:** the four mode fields are
  `StrEnum`s (a typo like `egress = "redcat"` no longer silently disables a guardrail), plus
  `providers.*.max_retries`, `agents.max_steps`, `tools.web_allow_private`,
  `sandbox.env_passthrough` and `limits.tool_timeout_s`; the circuit breaker reads
  `max_steps=None` by an explicit `is None`. **REL-03 resilience:** a failed or malformed
  provider stream aborts the turn (ERROR phase, `turn_end status="error"`, persisted) and
  surfaces a `ProviderError` instead of leaving an unresumable session; new `cognitive/retry.py`
  retries 429/5xx/transport failures with exponential backoff + equal jitter and `Retry-After`,
  never after the first streamed delta, with Anthropic delegating to the SDK's `max_retries`;
  the hidden `_MAX_TURN_STEPS = 12` is gone so `limits.max_steps` (default 40) is the only
  budget; malformed tool-call JSON returns a precise "invalid JSON in tool arguments" error
  instead of `{}`; the router cache invalidates on `/model`. **REL-04 egress:** redact mode
  buffers and replays the step's deltas from the inspected text, so a secret is never streamed,
  stored, or recalled, and tool-call arguments are scanned (`stage="egress_tool_args"`).
  **REL-05 sub-agents:** bounded by `agents.max_steps`, context-trimmed through the parent's
  working memory, inheriting the compiled system prompt and skills list, recording `model_call`
  events, and folding usage/cost into the parent turn and the cost cap (cost only, never
  `record_step`). **SEC-02/03/04:** the `web_fetch` SSRF guard (scheme check, DNS-resolved
  private/loopback/link-local refusal including IPv4-mapped/6to4/Teredo, manually re-vetted
  redirects capped at 5, a 2 MB pre-decode body cap, content-type check,
  `tools.web_allow_private` escape hatch); a cross-platform sandbox env allowlist with
  `env_passthrough` refusing credential-looking names; process-tree kill on timeout (Windows
  `taskkill /T`, POSIX `killpg`) plus `docker kill` of the named container; and MCP stdio
  servers receiving the scrubbed sandbox env instead of the full host environment (same commit
  fixes the `mcp` 2.0 `input_schema` rename that would have broken mounting against any real
  2.x server, stops approval-gating `readOnlyHint` tools, accumulates failure notes, and makes
  the manager restartable). Also: tool-name collisions are recorded and logged instead of
  silently dropped, and two TUI crashes closed with their mypy type holes. Release: CHANGELOG
  `[0.7.0] - 2026-09-19`, README status block plus new "Cost tracking", "Resilience" and
  "Security model" sections, `docs/ARCHITECTURE.md` synced to 0.7.0 (§§5–7, 9–11 updated and
  the claims the code doesn't back — harness-side rate limits, recursive summarization, the
  tool-emulation shim, `web_search`, pipeline/blackboard topologies — moved to a "not built"
  table in §15), and the version bumped to 0.7.0 in `pyproject.toml` and
  `src/agent86/__init__.py`. 678 tests collected.

- 2026-09-19 — **Phase 5 (Packaging & Hardening) complete; v0.6 milestone complete at 5/5
  phases and released as v0.6.0.** Executed as a review-driven hardening pass rather than a
  numbered plan set (see `phases/05-packaging-hardening/SUMMARY.md` for the commit-by-commit
  breakdown). Hardening: untrusted text is markup-escaped at the transcript boundary and in
  command renderables, so bracketed text no longer raises `MarkupError` and kills the TUI
  mid-turn; `run_tui` takes the already-built `_Repl` so the harness — and every MCP server — is
  constructed exactly once per process; turns are cancellable (Escape / Ctrl+C) and shutdown
  releases pending approvals with a bounded wait so quitting can't hang on a modal nobody will
  answer; the live stream region is capped so a long answer can't push the prompt and status
  footer off a short terminal; the dead prompt_toolkit rich loop and `ui/spinner.py` are gone
  and `[ui]` is honest (`status_line` -> `tui`, `mode_cycle_key` removed); the plain loop
  dispatches through the same `COMMANDS` registry as the TUI; the `CatalogPickerModal` flake and
  the ruff backlog are cleared. Release: CHANGELOG `[0.6.0] - 2026-09-19`, README status block
  and a new "Interactive TUI" section, `docs/ARCHITECTURE.md` synced to 0.6.0 (§4 gains `tui/`,
  `config_writer.py`, `secrets.py`; §11 documents `[ui] tui`, the env->keyring secret flow, and
  config_writer as the only writer; §12 documents the TUI, `--plain`, `/config model`,
  `/config mcp`, and cancellation), version bumped to 0.6.0 in `pyproject.toml` and
  `src/agent86/__init__.py`, `prompt_toolkit` dropped from core deps (last importer removed),
  and `[tool.mypy] python_version` moved to 3.12 to match CI. 532 tests collected. TUI-06
  Complete — all 10 v1 requirements now Complete.

- 2026-08-06 — Plan 04-08 complete (`/config mcp` full-app chain, Wave 4 — final plan, Phase 4
  now feature-complete 8/8, MCP-01 and the SEC-01 `headers.Authorization` write-path both closed):
  `/config mcp` registered in `tui/commands.py`'s `COMMANDS` registry with `needs_choice=
  "config_mcp"` (palette/`/help`/multi-word dispatch, zero per-surface wiring, mirrors
  `/config model`). `Agent86App` gains the full add/edit chain — `MCPManagerModal` →
  `MCPServerFormModal` → every unresolved `${VAR}` resolved one at a time through the existing
  masked `KeyEntryModal` (never a second masked field) → `MCPTestModal` on
  `Harness.ensure_mcp()`'s live manager → `SaveDiffModal` (headers/env written as individual TOML
  key paths, not whole dicts, so config_writer's forbidden-leaf-key guard actually inspects
  `headers.Authorization`) → `apply_edit` → `Harness.add_mcp_server` mounting the tested server's
  tools live. A cancelled add stops the server the test already started (D-13); a config write
  that succeeds while the live mount fails reports both without rolling back (D-16). Remove and
  enable/disable reuse the identical diff-and-confirm gate — no silent write, no extra "are you
  sure" dialog — and re-enabling a disabled server re-runs the connection test before mounting.
  Removed both plan-04-08-owned `xfail` markers from `tests/tui/test_mcp_manager.py`; added a
  `_FakeMCPManager` and full-app Pilot tests for the add chain, `${VAR}` key-entry chaining, both
  cancel paths, live mount, the override/mount-failure-reports-both path, per-key header/env TOML
  paths, and remove/disable/enable-with-test/no-op-remove. One test-only deviation: headless
  Pilot tests against the real `Agent86App` needed `run_test(size=(100, 50))` (default 80x24
  clips the MCP form below its Continue button) and a `pilot.pause`-based settle helper instead of
  a bare `asyncio.sleep` poll (buttons' `display` flag could flip `True` moments before their
  `Button` children finished mounting under `call_from_thread`) — 25+ consecutive runs green
  after the fix. Full suite green: 438 passed, 0 xfailed, 0 failed (the pre-existing, documented
  `CatalogPickerModal`/`#catalog-filter` flake from `deferred-items.md` appeared once per its two
  known forms across two full runs and cleared on immediate rerun both times — unrelated to this
  plan's files).

- 2026-08-06 — Plan 04-07 complete (MCP pre-save connection test modal, parallel Wave 3):
  `src/agent86/tui/screens/mcp_test.py` adds `MCPTestOutcome`/`MCPTestModal` — the MCP twin of
  `connection_test.py` (D-20): a 30s worker-thread test (raised from 15s because a first-run
  stdio server may `npx`-download its package) that starts a server for real on the caller's
  *live* `MCPManager` via `start_server(name, cfg, timeout=30.0, overrides=...)`, enumerates its
  tools, and requires an explicit Continue before the flow reaches the diff (D-19) rather than
  auto-dismissing on success. A real failure shows the verbatim (redacted, SEC-01) error and
  offers a labelled "Save anyway" override (D-13); timeout/cancel/escape all resolve explicitly
  and never hang. Removed the Wave 0 module-level `xfail` from `tests/tui/test_mcp_test_modal.py`
  — all 6 tests pass unmarked. Fixed a pre-existing scaffold bug flagged in the plan's own
  context: `Static.renderable` doesn't exist on the installed Textual 8.2.8 (`.render()` does,
  matching `test_save_diff.py`'s pattern). Full suite green: 418 passed, 2 xfailed (04-08-owned,
  untouched), 0 failed.

- 2026-08-06 — Plan 04-06 complete (Harness live mount/unmount seam, parallel Wave 3):
  `src/agent86/orchestration/loop.py` adds `Harness.ensure_mcp()` (returns the live `MCPManager`,
  creating an empty one when the session started with none, idempotent, never touching the
  registry), `add_mcp_server(name, cfg)` (mounts an already-connected server's tools — never
  opens a transport itself — into the live registry, returning `(mounted, collisions)` with
  name collisions reported rather than swallowed, D-24), and `remove_mcp_server(name)`
  (unregisters a server's tools, stops its session, drops it from `manager.servers`; a no-op for
  an unknown name or absent manager). Neither new method rebuilds `self.registry` or reads
  `self.config.mcp_servers` after construction (RESEARCH Pitfall 3) — `self.mcp.servers` and
  `self.registry` are the only live truth, matching the discipline `set_model()` already used.
  D-15 needed no code: `_build_request` already reads `self.registry.specs()` fresh every turn,
  so a mount/unmount takes effect on the very next turn. 15 new unit tests in
  `tests/unit/test_loop.py` (manager creation/idempotency, mount, collision reporting, config
  recording, transport-free mounting via a monkeypatched `_open_transport`, and unmount/no-op
  paths) using a lightweight fake `MCPManager`/`Tool` pair, no real transport. Full suite green:
  418 passed, 2 xfailed (04-08-owned, untouched), 0 failed.

- 2026-08-06 — Plan 04-04 complete (task-per-server MCPManager lifecycle, parallel Wave 2 —
  the single load-bearing piece of engineering in this phase, D-23): `MCPManager` rewritten
  from one shared `AsyncExitStack` to one persistent `asyncio.Task` per server, each owning its
  own stack via `start_server`/`stop_server`/`tools_for`/`_ensure_loop`/`_launch`/`_serve` —
  anyio binds a transport's cancel scope to the task that entered it, so parking on a per-server
  `close_event` and letting `async with` unwind in place (rather than closing a shared stack from
  a different task) is what makes independent per-server teardown legal. Verified for real
  against two live stdio `FastMCP` servers: `test_independent_teardown_leaves_other_server_intact`
  passes with no "cancel scope"/"different task" `RuntimeError`, the surviving server keeps
  answering `call_tool`, and calling the stopped server correctly raises. Added
  `_resolve_server_secrets`/`unresolved_var_refs` for connect-time `${VAR}` expansion in
  args/env/url/headers (never `command`) via plan 04-02's `expand_var_refs` (D-17/D-25), and
  filtered `cfg.enabled=false` servers inside `build_mcp` rather than `MCPManager` (D-09).
  One deviation: `ClientSession` is now looked up through a small `_get_client_session()`
  indirection (module globals first, real `from mcp import ClientSession` fallback) instead of
  the plan's literal function-local import, because the real `mcp` package is installed in this
  environment and the Wave 0 fake-session scaffold monkeypatches `mcp_client.ClientSession` —
  without the indirection the test would silently exercise the real SDK against fake streams
  instead of the intended fake. Removed `xfail` from 3 unit scaffolds, 2 `build_mcp` filter
  scaffolds, and 5 real-stdio integration scaffolds. Full suite green: 402 passed, 8 xfailed
  (unrelated, later-plan scaffolds), 0 failed.

- 2026-08-06 — Plan 04-02 complete (secret references + config deletion, parallel Wave 1):
  `agent86/secrets.py` adds `find_var_refs`/`expand_var_refs`/`MissingSecretRef` — MCP server
  configs reference secrets as `${VAR}`, resolved env-first-then-keyring by reusing
  `resolve_api_key(name, name)` verbatim (no second precedence implementation); an unresolved
  reference raises `MissingSecretRef` carrying `.var_name`. `agent86/config_writer.py` adds a
  `DELETE` sentinel so `plan_edit` can remove a whole `[mcp.servers.NAME]` table in the same
  changes list as an ordinary set (one function, one diff, no `plan_delete`/`deletions=`);
  `_FORBIDDEN_LEAF_KEYS` gains `"authorization"` (closing the SEC-01 hole in MCP
  `headers.Authorization`) paired with a `_is_var_ref` exception so the `${VAR}` form saves while
  a literal — even with a decoy `${notreal}` appended — is refused. Found and fixed a tomlkit
  quirk while making the delete scaffold pass for real: a hand-written comment between two table
  headers parses as trailing content of the *preceding* table, so a naive delete silently dropped
  a surviving sibling's comment; `_apply_delete` now pops that trailing trivia and re-homes it on
  the parent container. Removed `xfail` from the 6 var_ref scaffolds in `test_secrets.py` and the
  7 delete/forbidden_var_ref scaffolds in `test_config_writer.py`. Full suite green: 370 passed,
  35 xfailed (unrelated, later-plan scaffolds), 0 failed.

- 2026-08-06 — Plan 04-03 complete (MCP schema/registry seams, parallel Wave 1): `MCPServerConfig`
  gains `enabled: bool = True` (D-09), TOML round-trippable via the existing `[mcp.servers.NAME]`
  normalize path, with `_resolve_transport` unchanged. `agent86 mcp list` gained an `Enabled`
  column (`Name | Transport | Enabled | Endpoint`) — no new Typer subcommand. `ToolRegistry` gains
  `unregister(name) -> bool` (D-14), popping a tool by name so a removed/disabled MCP server's
  tools stop being callable immediately; `register`/`default_registry`'s bulk-mount duplicate-
  swallow left byte-identical (explicit collision surfacing deferred to plan 04-06, D-24). Removed
  `xfail` from the 4 Wave 0 scaffolds owned by this plan across `test_config.py`/`test_mcp.py`;
  the 4 `build_mcp`/`start_server`/`stop_server` scaffolds owned by plan 04-04 remain xfail-marked
  and untouched. Full suite green: 363 passed, 40 xfailed, 2 xpassed, 0 failed.

- 2026-08-06 — Plan 04-05 complete (MCP manager list + form modals, parallel Wave 2):
  `agent86/tui/screens/mcp_manager.py` created — `mcp_server_rows(cfg)` (pure, D-08: never spawns
  a subprocess or opens a transport; endpoint rendering byte-identical to `agent86 mcp list`),
  `parse_server_json` (accepts both the bare and `{"mcpServers"/"servers": {...}}` README JSON
  shapes, D-02; wrapped name wins over `name_hint`), `build_manual_config` (shlex-splits a
  command line into command+args, D-03; only honours an explicit transport when `url` is set,
  D-06), `parse_kv_list` (env/headers parsing, `${VAR}` passthrough for D-17). `MCPManagerModal`
  lists every server plus two peer "add" options (D-01) and dispatches edit/remove/toggle via
  Enter/`d`/`t`. `MCPServerFormModal` serves add-json/add-manual/edit from one form (D-07),
  re-validating on every keystroke and rendering the config validator's own message verbatim
  inline while disabling Continue (D-05), and blocking a name collision (D-04). Removed the Wave 0
  module-level `xfail` from `tests/tui/test_mcp_manager.py`; only the two 04-08-owned full-app
  chain tests remain explicitly `xfail`-marked. Fixed a genuine scaffold bug along the way —
  `Static.renderable` doesn't exist on the installed Textual 8.2.8 (`.render()` does, matching
  `test_save_diff.py`'s existing pattern). `pytest tests/tui/test_mcp_manager.py -q`: 17 passed,
  2 xfailed. `pytest tests/tui/ -q`: 109 passed, 8 xfailed, 0 failed. A pre-existing,
  test-order-dependent `CatalogPickerModal`/`#catalog-filter` flake (unrelated to this plan's
  files, first seen during 04-02) still reproduces in a full-suite run; logged in
  `deferred-items.md`, not fixed here (scope boundary).

- 2026-08-06 — Quick task 260805-xbw complete: `Harness._observe` (`orchestration/loop.py`)
  no longer collapses a failed tool result to the bare string `"error"`. `python_exec`/
  `run_command` report failure with `ok=False`, `error=None`, and the full
  `exit code / stdout / stderr` traceback in `content` — previously discarded, leaving the
  model blind to its own bugs and misattributing failures to a flaky sandbox. `_observe` now
  resolves the failure body from `content` (falling back to `error`, joining both when both
  are present), then runs the same guardrail scan/`UNTRUSTED_BANNER` wrap the success path
  already used — one scan site, not two. `_summarize` (the human-facing status line) was
  already correct and left untouched. `_BASE_IDENTITY` (`cognitive/prompt.py`) gained a
  `Debugging:` section instructing the model to print `traceback.format_exc()`, inspect data
  shape (`.keys()`/`type()`/`len()`) before indexing, and treat attempt-to-attempt differences
  as a clue about its own code, not environment flakiness. RED evidence recorded before the
  fix: 8/12 new tests failed pre-fix (the intended set), 4/12 passed pre-fix (pins on already-
  correct behavior). Full suite green: 353 passed (341 baseline + 12 new), 0 failed.

- 2026-08-06 — Plan 03-10 complete (UAT gaps 1 and 4 closure, parallel gap-closure wave):
  `KeyEntryModal.on_input_submitted` and `CatalogPickerModal.on_input_submitted` now call
  `event.stop()` as their first statement, and `Agent86App.on_input_submitted` now ignores
  every `Input` except `#prompt` — three defense-in-depth fixes closing UAT gap 1 (blocker,
  SEC-01/D-10): a typed API key was being echoed into the transcript and dispatched to the
  model as a real turn. `Agent86App._on_catalog_picked` now passes the `UNRESOLVED` sentinel
  (imported from `agent86.cognitive.base`) instead of the stale `None` left by the previous
  test's `finally` block whenever no key was typed this pass; `ConnectionTestModal.__init__`
  widens `api_key` to `Any = UNRESOLVED` to match — closing UAT gap 4 (blocker, MODEL-01): a
  keyring-stored key now resolves on the second and every subsequent connection test in a
  session, not just the first. Added `tests/tui/test_secret_leak.py` (6 new Pilot regression
  tests), confirmed 4/6 fail against the pre-fix source and all 6 pass post-fix. Full suite
  green: 331 passed, 0 failed.

- 2026-08-06 — Plan 03-11 complete (UAT gap 2 closure, parallel gap-closure wave): closes the
  second, independent secret-leak path found during UAT — a startup crash rendering a live
  `sk-ant-...` key in the `locals` panels of four traceback frames. `agent86.cli`'s `typer.Typer`
  now sets `pretty_exceptions_show_locals=False` (Rich never renders frame locals, on any code
  path). `agent86.secrets.redact()` added — strips explicit secrets and key-shaped tokens
  (`sk-`/`gsk_`/`xai-`/`AIza` prefixes) from any human-visible string. `cognitive/base.py`'s
  `provider_for_ref` refactored: the dispatch chain moved verbatim into a private
  `_build_provider()`, guarded by a wrapper that converts any non-`ProviderError` exception into
  a `ProviderError` with a redacted message and a severed `__cause__` chain (`from None`) —
  deliberate `ProviderError`s (missing key, missing SDK, unknown provider) pass through
  unchanged. 10 new regression tests in `tests/unit/test_secret_traceback.py`; 2 confirmed to
  fail against the pre-fix source via a `git stash` round-trip. Full suite green: 331 passed
  (grown from 275/311 as sibling gap-closure plans 03-10..03-13 landed concurrently in the same
  parallel wave). SEC-01/D-10 traceback leak closed.

- 2026-08-06 — Plan 03-12 complete (UAT gap 5 closure, blocker, parallel gap-closure wave):
  `agent86.cognitive.capabilities` adds a single per-model capability seam
  (`supports_sampling_params`/`apply_sampling_params`/`mark_sampling_unsupported`/
  `is_sampling_rejection`) recording that Anthropic removed `temperature`/`top_p`/`top_k` on
  Claude Opus 5, Opus 4.8, Opus 4.7, Sonnet 5 and Fable 5 — sending any of them 400s, with no
  replacement value, so they must be omitted entirely. `AnthropicProvider.stream` now gates
  through this seam (the gate is on the model, never on the value, since
  `CompletionRequest.temperature` defaults to `0.0`) and self-corrects: a real rejection from a
  model not yet in the hardcoded list is learned via `mark_sampling_unsupported` and retried
  once before any text is emitted. `complete()` stays inherited from `ModelProvider`, so the
  connection-test path used by `/config model` is fixed by the same change.
  `OpenAIProvider.stream` routed through the identical seam — byte-identical behaviour for
  OpenAI/Groq/OpenRouter today (no OpenAI-family model is affected), correct omission for free
  if a gateway proxies an Anthropic model through an OpenAI-compatible endpoint. 43 new tests
  (`test_capabilities.py` + `test_sampling_params.py`); existing `test_openai_provider.py` left
  byte-unmodified. Full suite green: 331 passed, 0 failed. ROADMAP success criterion 4
  ("switching the active model takes effect for the next turn") now holds in practice for the
  default `anthropic:claude-opus-5` selection. MODEL-01 gap closed.

- 2026-08-06 — Plan 03-13 complete (UAT gap 3 closure, blocker, gap-closure wave — Phase 3 now
  fully closed, all 6 UAT gaps resolved): `AnthropicProvider.__init__` gains an SDK-version guard
  — `_MIN_ANTHROPIC_VERSION = (0, 40)` and a tolerant `_version_tuple` parser (stops at the first
  non-numeric character per dot-segment, so pre-release suffixes never block startup) — that
  raises `ProviderError` naming the version found, the version needed, and the exact
  `pip install -U "anthropic>=0.40"` upgrade command, mirroring the existing missing-package
  `ImportError` path exactly in tone and type. The guard fires before `anthropic.Anthropic(...)`
  is ever constructed, so a stale SDK below the floor (versions < 0.28 pass `proxies=` to
  `httpx.Client`, which httpx removed in 0.28) never reaches the opaque
  `Client.__init__() got an unexpected keyword argument 'proxies'` `TypeError` that dumped a
  traceback and leaked the key at startup (root cause of UAT gaps 2 and 3 together). Because the
  guard raises `ProviderError`, it passes through plan 03-11's catch-all and `run_repl`'s existing
  `except ProviderError` branch untouched — no changes needed to `cognitive/base.py` or
  `ui/repl.py`. 10 new regression tests in `tests/unit/test_anthropic_sdk_guard.py`: 6 unit tests
  on the guard itself (stale version raises with exact wording, zero-client-construction proof,
  real 0.120.2 constructs normally, missing/unparseable version doesn't block startup, missing-
  package path unchanged), 4 end-to-end through `run_repl` (an opaque `TypeError` and a genuine
  stale-SDK `ProviderError` both print "Cannot start:" with no traceback and no leaked key).
  `pyproject.toml`'s `anthropic>=0.40` floor left untouched (verified via empty `git diff --stat`)
  — no dependency pin was part of this deliverable, per the plan's explicit instruction that the
  environment (already at anthropic 0.120.2) was not the fix. Full suite green: 341 passed
  (up from 331), 0 failed, across two consecutive reruns.

- 2026-08-06 — Plan 03-09 complete (full-app chain + live-catalog /model picker, Wave 3 — final
  plan, Phase 3 now feature-complete 9/9): `agent86/tui/messages.py` adds `CatalogReady`.
  `Agent86App` gains a per-session `_catalog_cache`, `_request_catalog`/`_fetch_catalog`
  (`@work(thread=True)`, cache populated only in `on_catalog_ready` on the UI thread — RESEARCH
  Open Question 3 resolved: the cache lives on the App, not `_Repl`/`Harness`), and the full
  `/config model` chain: `ProviderManagerModal` → `KeyEntryModal` (only if no key) → catalog fetch
  → `CatalogPickerModal` → `ConnectionTestModal` → on pass/override, `store_api_key` fires exactly
  once (D-14), the model switch applies immediately via `_dispatch_line("/model <ref>")`, then
  `SaveDiffModal` → `apply_edit` on confirm. `_dispatch_line` now routes any bare (argument-less)
  `needs_choice` command typed directly — not just palette-picked — through `_run_or_chain`, since
  the Wave-0 chain tests type `"/config model"` straight into the prompt and press Enter.
  `model_choices(cfg, extra=...)` enriches the `/model` picker with the live catalog, closing
  Phase 2's deferred D-12; `/model` stays switch-only (D-15). Removed the 3 remaining chain-wiring
  `xfail` markers from `tests/tui/test_provider_manager.py` (filling in
  `test_save_anyway_override`'s exact key-press choreography with network-safe mocks for
  `catalog.fetch_catalog`/`connection_test.provider_for_ref`); added 3 catalog-cache tests, 3
  `/model`-picker cache tests, and an escape/`SkipAction` regression test to `test_app.py`, plus 3
  `model_choices(extra=...)` tests to `test_pickers.py`. Full suite green: **275 passed, 0
  xfailed, 0 xpassed, 0 failed** (up from 262/2/1/0). `deferred-items.md` removed (its logged
  failures were transient parallel-wave artifacts, already resolved). Manual Windows Terminal
  verification (real keyring round-trip, real comment-preserving save, live OpenRouter/Groq
  catalog schema check) per `03-VALIDATION.md` remains outstanding before the phase is declared
  fully done end-to-end, but all automated success criteria are met.

- 2026-08-05 — Plan 03-06 complete (key-entry + connection-test modals, parallel Wave 2):
  `src/agent86/tui/screens/key_entry.py` adds `KeyEntryModal(ModalScreen[str | None])` — masked
  (`password=True`) key capture, explicit dismiss on submit/empty/escape, distinct
  "OS keyring unavailable" messaging (SEC-01, D-08/D-09/D-10). `src/agent86/tui/screens/
  connection_test.py` adds `ConnectionTestModal(ModalScreen[TestOutcome])` — a worker-thread
  (`@work(thread=True)`) real 1-token completion test via `provider_for_ref(ref, cfg, api_key=...)`,
  a hard 15s timeout that auto-resolves without waiting on a button, and a "Save anyway" override
  on real provider errors; the tested key is never written to the keyring by this module (MODEL-01,
  D-11..D-14). Deleted the shared Wave 0 xfail marker from `tests/tui/test_connection_test.py` and
  added 5 new `KeyEntryModal` tests; all 10 tests in the file pass. Full suite green: 262 passed,
  2 xfailed (unrelated), 1 xpassed (unrelated), 0 failed. Note: due to a parallel-executor commit
  race, `connection_test.py` landed inside plan 03-08's commit (`689f0da`) rather than its own —
  content verified correct and complete; see 03-06-SUMMARY.md for detail.

- 2026-08-06 — Plan 03-08 complete (provider manager + catalog picker, parallel Wave 2):
  `agent86/tui/screens/provider_manager.py` adds `ProviderRow`/`provider_rows(cfg)`/
  `ProviderManagerModal`/`CatalogPickerModal`. `provider_rows` lists every configured provider
  in config order with an accurate, secret-free key status (`key ok`/`no key`/`local, no key
  needed`), sourced from `resolve_api_key` so it matches exactly what a real turn would resolve
  (D-05/D-09/D-10). `ProviderManagerModal` (OptionList) dismisses with the selected `ProviderRow`
  or `None` on Escape. `CatalogPickerModal` narrows a catalog by typing (case-insensitive
  substring on ref/label, mirroring Phase 2's `_sync_palette` filter-and-reset-highlighted
  pattern, D-03) and its filter Input doubles as the D-01 free-text fallback when the catalog is
  empty or nothing matches — never a dead end. A `_catalog_ref`/`_freetext_ref` split avoids
  double-prefixing Ollama model names that already contain a colon (e.g. `llama3.1:8b`). Wave 0
  module-level xfail removed; per-function xfail kept on exactly the 3 tests plan 03-09 owns
  (full-app chain wiring). Full suite green: 262 passed, 2 xfailed, 1 xpassed (harmless early
  pass of a 03-09-owned test), 0 failed. MODEL-01 requirement's provider-list/catalog-picker
  surfaces complete.

- 2026-08-06 — Plan 03-05 complete (command-surface + keyring visibility, parallel Wave 2):
  `/config model` registered in `tui/commands.py`'s `COMMANDS` registry with
  `needs_choice="config_model"`, discoverable via `/help` and the `/` palette with zero
  per-surface wiring (MODEL-01). `find_command_for_line` added for longest-name-first multi-word
  dispatch so `/config model` wins over `/config` while `/models` still beats the `/model` prefix
  and `/model <arg>`/`/quit`/`/exit` are unchanged; `handle_command` rewritten to use it,
  `find_command` (palette's exact-name lookup) untouched. `_key_source` helper (env → keyring →
  none → n/a) added to both `tui/commands.py` and `cli.py`; the TUI `/models` table and `agent86
  config` (bare — wired via a new `config_app` callback to the existing `_list_models`, since that
  table lived under `agent86 models` rather than a pre-existing `agent86 config` default action)
  both now show a `Key` column and an `OS keyring: available/unavailable` line, no secret ever
  rendered (D-09/D-10, SEC-01). 8 new regression tests added; full suite green: 262 passed,
  2 xfailed, 1 xpassed, 0 failed.

- 2026-08-06 — Plan 03-07 complete (save-diff modal, parallel Wave 2): `agent86/tui/screens/
  save_diff.py` adds `SaveDiffModal(ModalScreen[ConfigEdit | None])` — the D-16/D-17 trust-building
  step. On mount and on every scope change it calls `config_writer.plan_edit(scope, changes)`
  (pure, no disk I/O) and renders the unified diff plus target path; `#scope-user` is pre-selected,
  `#scope-project` is one arrow key away and recomputes the diff. `#save-confirm` dismisses with
  the live `ConfigEdit`; `#save-cancel`/Escape dismiss with `None`; a `ConfigWriteError`/`ValueError`
  (malformed existing file, forbidden secret key) renders the error text and disables
  `#save-confirm` instead of crashing. The modal never calls `apply_edit` itself — the caller
  applies the returned `ConfigEdit` on confirm. Deleted the Wave 0 xfail marker from
  `tests/tui/test_save_diff.py`; added 2 integration tests proving the previewed diff is
  byte-identical to what gets written and that all four hand-written comments in
  `tests/fixtures/config_with_comments.toml` survive a real preview-then-apply round trip.
  `pytest tests/tui/test_save_diff.py -q` — 6 passed, 0 xfailed. MODEL-02 requirement complete.

- 2026-08-06 — Plan 03-02 complete (secrets seam, parallel Wave 1): `agent86/secrets.py` created
  with `resolve_api_key`/`keyring_available`/`has_stored_key`/`store_api_key`/`clear_api_key` —
  env var wins, falls back to OS keyring, never raises (silent degrade when keyring absent/broken),
  keyring imported lazily inside every function body. `provider_for_ref` in `cognitive/base.py`
  now resolves the key once via `resolve_api_key(ref.provider, pconf.api_key_env)` — keyed on the
  config section name so a custom `[providers.myvllm]` block gets its own keyring slot — and
  injects it into every provider construction path via an `UNRESOLVED` sentinel (direct
  construction, as existing tests do, still self-resolves). Both `os.getenv` seams in
  `anthropic_provider.py`/`openai_provider.py` removed; `llamacpp_provider.py` forwards the key.
  Original `ProviderError` wording preserved verbatim with only an appended clause. Deleted the
  Wave 0 xfail markers from `tests/unit/test_secrets.py` (7 tests) and
  `tests/unit/test_providers_key_seam.py` (6 tests); all now pass. Full suite green: 229 passed,
  16 xfailed, 1 xpassed (unrelated), 0 failed. SEC-01 requirement complete.

- 2026-08-06 — Plan 03-04 complete (catalog fetch + normalization, parallel Wave 1):
  `agent86/cognitive/catalog.py` adds `fetch_catalog`/`fetch_openai_compatible`/`fetch_anthropic`/
  `fetch_ollama`/`CatalogUnavailable`, normalizing all five distinct provider models-endpoint
  response shapes (OpenAI, Groq, OpenRouter, Anthropic, Ollama) into a common `(ref, label)` list
  (MODEL-01, D-01/D-02: the live endpoint is the only source of truth, nothing hardcoded).
  Anthropic uses `x-api-key` + `anthropic-version: 2023-06-01`, never `Authorization: Bearer`
  (RESEARCH Pitfall 4). Any fetch failure, or a provider with no listing endpoint (llama.cpp),
  raises `CatalogUnavailable` so the caller falls back to free-text `provider:model` entry — never
  a dead end. Deleted the Wave 0 xfail marker from `tests/unit/test_catalog.py`; all 9 tests pass
  for real. Live-verified the OpenRouter schema against `GET https://openrouter.ai/api/v1/models`
  (matches the fixture exactly); Groq's schema stays unverified (no API key available) and is
  recorded as an open item for a future manual pass. Full suite green: 229 passed, 16 xfailed,
  1 xpassed, 0 failed.

- 2026-08-06 — Plan 03-03 complete (config write-back, parallel Wave 1): `agent86/config_writer.py`
  adds `plan_edit`/`apply_edit` — a two-step tomlkit round-trip write-back (D-17) that preserves
  every comment/blank line in a hand-edited `config.toml`, targets user scope by default with
  project scope selectable via `scope_path`, and produces a `difflib.unified_diff` preview before
  anything is written. Any leaf key in `{api_key, apikey, key, token, secret, password}` raises
  `ValueError` before text is generated, so no plaintext secret can reach disk through this module
  (SEC-01). Writes are atomic (`tempfile.mkstemp` + `os.replace`), so a crash mid-write cannot
  truncate an existing config; malformed existing TOML raises `ConfigWriteError`. `tomlkit` stays
  lazily imported (guarded by `tests/tui/test_lazy_import.py`, still 2 passing). Deleted the Wave 0
  xfail marker from `tests/unit/test_config_writer.py`; all 6 original + 3 new hardening tests pass.
  Full suite green: 229 passed, 16 xfailed, 1 xpassed, 0 failed.

- 2026-08-05 — Plan 03-01 complete (Wave 0 scaffolds, 1/9 plans in Phase 3): `keyring>=25.0` and
  `tomlkit>=0.13` added as core-but-lazy dependencies (installed, confirmed absent from
  `sys.modules` after `import agent86.cli`); 4 backend xfail-scaffolded unit-test modules
  (`test_secrets`, `test_config_writer`, `test_catalog`, `test_providers_key_seam`) and 3 TUI
  xfail-scaffolded Pilot modules (`test_provider_manager`, `test_connection_test`, `test_save_diff`)
  written against the exact interfaces plans 03-02..03-09 must implement, plus 6 fixture files
  (hand-commented TOML + 5 catalog JSON payloads). Work was committed in a prior session
  (2814da7/aaa0649/875015e, 2026-07-21); this session verified every acceptance criterion still
  holds and produced the SUMMARY.md that was never created. Full suite green: 198 passed,
  42 xfailed, 3 xpassed, 0 failed.

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

| # | Description | Date | Commit | Status | Directory |
|---|-------------|------|--------|--------|-----------|
| 260720-1jw | Fix TUI /models rendering bug — wrap tables in a Group | 2026-07-20 | 47da657 | | [260720-1jw-fix-tui-models-rendering-bug-wrap-tables](./quick/260720-1jw-fix-tui-models-rendering-bug-wrap-tables/) |
| 260720-1rs | Fix TUI shift+tab not cycling approval mode — priority binding | 2026-07-20 | 2050765 | | [260720-1rs-fix-tui-shift-tab-not-cycling-approval-m](./quick/260720-1rs-fix-tui-shift-tab-not-cycling-approval-m/) |
| 260805-xbw | Surface failed tool tracebacks to the model — fix _observe + debugging-discipline prompt | 2026-08-06 | a092502 | | [260805-xbw-surface-failed-tool-tracebacks-to-the-mo](./quick/260805-xbw-surface-failed-tool-tracebacks-to-the-mo/) |
| 260813-adr | Make /model catalog picker insert the active provider prefix | 2026-08-13 | 2a63ada | | [260813-adr-make-model-catalog-picker-insert-the-act](./quick/260813-adr-make-model-catalog-picker-insert-the-act/) |
| 260813-atc | Catalog-validated provider fallback for /model bare-ref typing | 2026-08-13 | 300c215 | Verified | [260813-atc-catalog-validated-provider-fallback-for-](./quick/260813-atc-catalog-validated-provider-fallback-for-/) |
| 260813-jfk | Configurable HTTP timeouts for streaming — bound the two unbounded httpx.stream reads | 2026-08-13 | c600987 | Verified | [260813-jfk-configurable-http-timeouts-for-streaming](./quick/260813-jfk-configurable-http-timeouts-for-streaming/) |

- 2026-08-13 — Quick task 260813-adr complete: fixed the TUI `/model` catalog picker dispatching a
  broken ref for every provider (reported via the Ollama entry `nemotron-3.5-lightning:latest`
  producing "Unknown provider 'nemotron-3.5-lightning'"). Root cause: `fetch_catalog` returns bare
  model ids by contract, but `Agent86App._open_model_picker` passed them straight into
  `model_choices` unprefixed, so `ModelRef.parse`'s first-colon split mis-parsed any colon-bearing
  Ollama id and rejected any colon-free id (e.g. openai `gpt-4o`) outright. Added a pure
  `prefix_catalog_refs(provider, entries)` helper in `model_picker.py` (mirroring
  `CatalogPickerModal._catalog_ref`, exact-prefix double-prefix guard) and wired it into
  `_open_model_picker` before `model_choices`, covering both the session-cache and fresh-fetch
  paths. `cognitive/catalog.py` left unmodified. 6 new regression tests (5 pure + 1 end-to-end
  Pilot), confirmed RED against the pre-fix source before finalizing. Full suite green: 436 passed,
  6 skipped, 1 known pre-existing unrelated failure (`test_build_embedder_falls_back_without_torch`).

- 2026-08-13 — Quick task 260813-atc complete: closed the companion *typed* `/model <bare-ref>`
  path that 260813-adr's picker fix didn't cover — `/model nemotron-3.5-lightning:latest` still
  errored with "Unknown provider 'nemotron-3.5-lightning'" when typed directly, since
  `ModelRef.parse` splits on the first colon and Ollama ids carry their own `:tag`. Added a pure
  `catalog_has_ref(ref, entries)` bare-id membership helper (`model_picker.py`, alongside
  `prefix_catalog_refs`) and wired a catalog-validated fallback into `Agent86App._dispatch_model`:
  the strict `/model` path runs first (zero duplication of `commands.py`'s dispatch logic,
  detected via `harness.provider` identity), and only a failure shaped like the first-colon-split
  ambiguity (`_is_bare_ref_candidate`) — never a known provider's build/auth failure — falls
  through to a catalog lookup of the active provider. A hit retries as `<provider>:<ref>` and
  echoes `resolved to ...`; a miss surfaces the existing strict error byte-unchanged, preserving
  typo detection as the feature. Cold-cache dispatches queue as `_pending_model` triples
  `(arg, strict_error, provider)` — provider captured per entry, not a single slot — with
  `_model_fetch_inflight` gating exactly one fetch per provider per burst; `on_catalog_ready`'s
  new `model_fallback` branch resolves only same-provider entries and re-queues the rest, so an
  entry is validated only against the catalog of the provider active when *it* was dispatched,
  even across an intervening successful `/model` switch to another provider. `tui/commands.py`,
  `ui/repl.py`, `types.py`, and `cognitive/catalog.py` left unmodified — the fallback is
  TUI-app-layer only, keeping `--plain`/`run --json` strict. 17 new regression tests (6 pure
  `catalog_has_ref` cases + 10 Pilot cases + 1 plain-adapter pin), including the
  overlapping-same-provider and cross-provider-stranding sequences from the plan's locked
  decisions, both driven by hard-timeout blocking fakes so a routing regression fails the suite
  rather than hanging it. RED proof confirmed against the pre-Task-2 source. Full suite green:
  454 passed, 6 skipped, 1 known pre-existing unrelated failure
  (`test_build_embedder_falls_back_without_torch`).

- 2026-08-13 — Quick task 260813-jfk complete: fixed the real 20+ minute hang diagnosed via
  py-spy at `ollama_provider.py:108` — `httpx.stream(..., timeout=None)` at both
  `ollama_provider.py:101` and `openai_provider.py:142` meant "no timeout at all," so a server
  that accepted a connection and then stopped sending (Ollama's keep-alive expiring mid-teardown
  without closing the socket) blocked the turn worker's `recv()` forever. `ProviderConfig` gains
  per-provider `connect_timeout_s` (10.0, matches `catalog.py`'s existing constant) and
  `read_timeout_s` (300.0, sized for time-to-first-token on slow local hardware — ~4.4x the
  incident's own preceding legitimate request). New `cognitive/http_timeouts.py` owns the
  `ProviderConfig -> httpx.Timeout` conversion (always split — connect/read/write/pool, never a
  scalar or a total-request deadline, since httpx's `read` is the max GAP between chunks, not the
  total generation time) and the `httpx.TimeoutException -> ProviderError` message, shared by both
  providers so they cannot drift. Both call sites now pass a config-derived `httpx.Timeout`; a new
  `except httpx.TimeoutException` clause was appended after each provider's existing
  `except httpx.ConnectError` (disjoint sibling exception types, so the pinned Ollama
  "Cannot reach Ollama..." wording stays byte-unchanged). Found and fixed along the way:
  `LlamaCppProvider`'s default-base-url substitution was reconstructing a bare `ProviderConfig`
  that silently dropped every field except `base_url`/`api_key_env` — now
  `config.model_copy(update={"base_url": ...})`, preserving the caller's timeout fields (and any
  future ones). Anthropic (D-3, SDK's own ~600s default already bounds it) and
  `tools/mcp_client.py` (D-4, already bounded by httpx's 5s default) deliberately unchanged, with
  comments recording why. Proved the core guarantee against a REAL loopback HTTP/1.0 socket (not a
  fake, which would be circular): a stalled stream raises `ProviderError` in well under its
  configured budget for both Ollama NDJSON and OpenAI SSE, and — the key semantic, parametrized
  over both wire formats — a slow-but-progressing stream whose TOTAL duration (~1.5s) exceeds the
  read timeout (0.6s) still succeeds with full untruncated text, via an explicit
  `elapsed > read_timeout_s` assertion. Every provider call ran through a hard
  `ThreadPoolExecutor` + `future.result(timeout=...)` budget so a regression would fail the suite
  rather than hang it; no `pytest-timeout`/`py-spy` dependency added. Full suite green: 479 passed
  (up from 454), 6 skipped, 1 known pre-existing unrelated failure
  (`test_build_embedder_falls_back_without_torch`). Ruff introduces zero new errors (verified via
  a `git worktree` diff against the pre-task baseline).

## Next Step

The v1.0 "Release" milestone is complete and shipped as **v1.0.0** — 1/1 phase, 9/9 requirements
(OBS-01…OBS-04, PKG-01, PKG-02, HARD-01…HARD-03) Complete. Every v1.0 candidate recorded at the
close of v0.9 shipped, and `docs/ARCHITECTURE.md` §15 no longer lists anything the contract
specifies as built.

**The orchestrator tags the release**: `python scripts/check_release.py --tag v1.0.0` passes, and
the tag push is what runs `release.yml` (pre-flight → build → `twine check` → packaging tests →
trusted publishing → GitHub Release). Procedure and one-time trusted-publisher setup:
`docs/RELEASING.md`. Nothing in this repository is tagged or pushed by the docs pass.

**No next milestone is scoped** — v1.0 closed the programme, and what follows is a backlog rather
than a plan. Nearest item: flip `Development Status` from `4 - Beta` to `5 - Production/Stable` in
the first release *after* 1.0 is live on PyPI, since the classifier is a claim about a published
artifact.

Outstanding (non-blocking): what v0.9 opened, now in `docs/BACKLOG.md` § TUI / § "Skills & tools" —
click-to-toggle tool blocks (needs a widget-based transcript, since a `RichLog` can't host
children), history *navigation* in the plain loop (needs `readline`), and the sandbox jail's
missing read/write split, which makes a skill root granted for *reading* writable too. Plus the
v0.7 review leftovers in `docs/BACKLOG.md` § "v0.7 review leftovers" (`web_fetch` approval gating,
a `/cost` breakdown by turn, `test_mcp_live`) and the older deferred list in the same file. Still
carried from v0.6: manual Windows Terminal verification per `03-VALIDATION.md` §Manual-Only
(real keyring round-trip, real `config.toml` comment preservation, live OpenRouter/Groq catalog
schema check, a real turn against a cloud model) and of the full `/config mcp` flow against a
real MCP server.
