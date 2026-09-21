# agent86 — Architecture & Specification

> An agentic harness on the command line. A Python CLI that connects to remote or
> local models and lets them use tools and skills — built as a faithful, runnable
> implementation of the five-tier architecture and four pillars described in
> *The Agentic Harness* (Tony Fleming, 2026).

**Status:** Implemented (Phases 1–9 complete), then extended through v1.0.0. This document is
the contract the code was built against; the build followed §14 phase-by-phase, each phase
verified with tests and a live run against a local model. Post-v0.1 releases added an
interactive REPL with a persistent status line and live approval-mode and model switching
(v0.2, v0.4); memory management via `memory prune`/`forget` plus automatic log retention
(v0.3, v0.4); first-class OpenAI-compatible cloud providers — OpenRouter, Groq, and any
configured `base_url` endpoint (v0.4); MCP over SSE and streamable HTTP (v0.5); a
full-screen Textual TUI as the default interactive UI, with in-app model/provider and MCP
configuration, keyring-backed secrets, and cancellable turns (v0.6); and the "trustworthy"
pass — a real price table behind the cost cap, provider retries with backoff, a clean error
path for a failed stream, egress redaction on the output path, sub-agent accounting, and the
`web_fetch` / sandbox-environment / MCP-environment / process-tree security fixes (v0.7); and
the "context & cost" pass — the conversation budgeted against the model's real context window,
summarizing compaction of the oldest span, `max_tokens` continuation, parallel read-only tool
calls, Anthropic prompt caching with cache-aware pricing, a normalized `StopReason`, and a
per-turn cost read-out on every surface (v0.8); and the "coding-agent UX" pass — a Markdown
transcript with collapsible tool-call blocks, a multi-line prompt with persistent history and
`@file` mentions, named sessions with a listing and a picker, exact-match `edit_file` with unified
diffs, `Tool.preview` behind every approval, and the Agent Skills convention with `allowed-tools`
enforced as a gate (v0.9); and the "release" pass — a redacted and rotated flight recorder, a real
OpenTelemetry exporter behind a provider of the harness's own, `trace export` (including a
reconstructed OTLP span tree), PyPI packaging with a tag-driven publish workflow, and the
scripting contract pinned by tests (v1.0).
**Version:** 1.0.0 — **the contract below is fully implemented.** §15's "described above,
deliberately not built" table no longer holds anything this document specifies as built.

---

## 1. Guiding principle — Separation of Concerns

The book's foundational rule drives every decision here:

> **The Cognitive Core must never have direct access to external systems, databases, or
> user interfaces. All interactions between the model and the outside world must be
> mediated, validated, and executed by the deterministic harness runtime.**

Two domains, never blurred:

| Domain | Nature | Responsibility |
|---|---|---|
| **Probabilistic** (Cognitive Core) | Non-deterministic, stateless, natural language | *Proposes* the next step |
| **Deterministic** (Harness) | Typed, stateful, structured | *Validates, executes, persists* |

A model's output is an **untrusted request**, not an authoritative command. The harness is
the motherboard + OS; the model is the CPU.

---

## 2. Locked decisions

| Dimension | Decision | Rationale |
|---|---|---|
| Language / tooling | Python 3.11+, `uv`, `pyproject.toml`, `src/` layout | Best AI+local-model ecosystem; matches book's Python samples |
| Entry point | `agent86` console script | — |
| Model backends (Tier 3) | Anthropic · OpenAI-compatible · Ollama · llama.cpp/LM Studio | Remote + local, one adapter interface |
| Scope | Full five-tier reference harness | All tiers + four pillars |
| Tools & skills (Pillar 3) | Built-in tools + MCP client + markdown skills | Familiar + interoperable + extensible |
| Interface | Interactive REPL **and** one-shot | `agent86` (REPL) + `agent86 run "goal"` |
| Sandbox (Tier 4) | Layered: restricted subprocess, Docker opt-in | Pragmatic on Windows-primary |
| Memory (Pillar 2) | SQLite + `sqlite-vec`, local `sentence-transformers` embeddings | Local-first, single-file, offline |
| Guardrails / advanced | HITL approvals · OpenTelemetry · dynamic model routing · multi-agent | Full Tier-5 + orchestration |

---

## 3. The mapping — book concepts → code

### 3.1 Five Tiers

```
┌─────────────────────────────────────────────────────────────────────┐
│  Tier 1  GATEWAY / INGRESS      gateway/     session init, identity, │
│                                               input sanitization      │
├─────────────────────────────────────────────────────────────────────┤
│  Tier 2  ORCHESTRATION & STATE  orchestration/  ReAct loop, FSM,     │
│          (Pillar 1)                             routing, circuit      │
│                                                 breakers              │
├─────────────────────────────────────────────────────────────────────┤
│  Tier 3  COGNITIVE              cognitive/    provider adapters,      │
│                                               prompt compilation,     │
│                                               token budgeting         │
├─────────────────────────────────────────────────────────────────────┤
│  Tier 4  TOOL & EXECUTION       tools/        built-ins, MCP client,  │
│          (Pillar 3)                           sandbox executors       │
├─────────────────────────────────────────────────────────────────────┤
│  Tier 5  GUARDRAILS &           guardrails/   ingress/egress/policy   │
│          OBSERVABILITY          observability/ OTel + flight recorder │
└─────────────────────────────────────────────────────────────────────┘
```

> **Note on Tier 1.** In this implementation the Gateway tier is deliberately thin: the
> `gateway/` package is a namespace, and its responsibilities are folded into the surrounding
> code — session lifecycle in `orchestration/state.py` + `loop.py`, and input sanitization in
> `cli.py` + `guardrails/ingress.py`. For a single-user CLI there was no separate gateway to
> build; the concern still exists, just not as its own module.

### 3.2 Four Pillars

| Pillar | Book role | Module(s) |
|---|---|---|
| **1 — Orchestration** (nervous system) | Drives the execution loop, state transitions, recovery/retry limits | `orchestration/` |
| **2 — Memory** (temporal anchor) | Working / episodic / semantic memory | `memory/` |
| **3 — Tool Interfaces** (actuators) | Schema enforcement + sandbox isolation | `tools/` |
| **4 — Evaluation & Guardrails** (immune system) | Ingress/egress/operational guardrails | `guardrails/` |

---

## 4. Package layout

```
agent86CLI/
├── pyproject.toml                 # uv / PEP 621, console entry: agent86
├── README.md
├── docs/
│   └── ARCHITECTURE.md            # this file
├── src/agent86/
│   ├── __init__.py
│   ├── __main__.py                # python -m agent86
│   ├── cli.py                     # Typer app: interactive entry + `run` one-shot
│   ├── config.py                  # layered config (defaults→file→env→flags) — READ ONLY
│   ├── config_writer.py           # the only TOML writer: tomlkit round-trip, diff, atomic write
│   ├── secrets.py                 # env→keyring key resolution, ${VAR} refs, redaction
│   ├── types.py                   # shared dataclasses/Pydantic: Message, Step, ToolCall, ToolResult
│   │
│   ├── gateway/                   # ── Tier 1 (thin) ──
│   │   └── __init__.py            #   session lifecycle folded into orchestration/state.py + loop.py;
│   │                             #   input sanitization lives in cli.py/tui/ + guardrails/ingress.py
│   │
│   ├── orchestration/             # ── Tier 2 / Pillar 1 ──
│   │   ├── loop.py                #   ReAct execution loop (perceive→reason→act→observe)
│   │   ├── state.py               #   AgentState FSM (INIT→PLAN→EXECUTE→VERIFY→DONE), persistence
│   │   ├── router.py              #   dynamic model routing (triage: cheap/local vs frontier)
│   │   └── circuit.py             #   cost-cap / step-cap / wall-clock circuit breakers
│   │
│   ├── cognitive/                 # ── Tier 3 ──
│   │   ├── base.py                #   ModelProvider ABC + unified Message/ToolSpec/Completion
│   │   ├── anthropic_provider.py  #   Claude Messages API (native tool use, streaming, caching)
│   │   ├── openai_provider.py     #   OpenAI + any OpenAI-compatible base_url
│   │   ├── ollama_provider.py     #   local Ollama HTTP API
│   │   ├── llamacpp_provider.py   #   llama.cpp server / LM Studio local server
│   │   ├── prompt.py              #   prompt compilation (system + skills + history + schema)
│   │   ├── retry.py               #   transient-failure policy: backoff + jitter, Retry-After
│   │   └── pricing.py             #   per-model price table → usage cost (priced/local/unknown)
│   │
│   ├── tools/                     # ── Tier 4 / Pillar 3 ──
│   │   ├── base.py                #   Tool ABC, JSON-Schema spec, ToolResult
│   │   ├── registry.py            #   registration, schema export, dispatch, per-tool policy
│   │   ├── mcp_client.py          #   MCP client — mounts external MCP-server tools
│   │   ├── builtin/
│   │   │   ├── shell.py           #   run_command (sandboxed)
│   │   │   ├── files.py           #   read_file / write_file / edit_file / list_dir (path-jailed)
│   │   │   ├── web.py             #   web_fetch (policy-compliant User-Agent)
│   │   │   ├── python_exec.py     #   python interpreter tool (sandboxed)
│   │   │   ├── memory.py          #   remember / recall (semantic memory)
│   │   │   ├── delegate.py        #   delegate(role, task) — sub-agent spawning
│   │   │   └── skills_tool.py     #   use_skill — load a skill's full instructions
│   │   └── sandbox/
│   │       ├── policy.py          #   allow/deny paths, network, env scrub, timeouts, limits
│   │       ├── executor.py        #   executor selection + shared execution result
│   │       ├── subprocess_exec.py #   default restricted-subprocess executor
│   │       └── docker_exec.py     #   opt-in Docker container executor
│   │
│   ├── skills/                    # ── Skills (progressive disclosure) ──
│   │   ├── loader.py              #   discover skill folders, parse frontmatter, load on demand
│   │   └── models.py              #   Skill dataclass (name, description, instructions, resources)
│   │
│   ├── memory/                    # ── Pillar 2 ──
│   │   ├── store.py               #   MemoryStore: SQLite schema + optional sqlite-vec, retention
│   │   ├── system.py              #   assembles the store + episodic/semantic facets from config
│   │   ├── working.py             #   working memory (context window) manager
│   │   ├── episodic.py            #   episodic traces — "flight data recorder" of past runs
│   │   ├── semantic.py            #   semantic memory / RAG retrieval
│   │   └── embeddings.py          #   Embedder ABC + sentence-transformers default (+ hash fallback)
│   │
│   ├── guardrails/                # ── Tier 5 / Pillar 4 ──
│   │   ├── ingress.py             #   prompt-injection & PII/jailbreak scan
│   │   ├── egress.py              #   secret/PII leak scan, output schema validation
│   │   ├── scanners.py            #   shared regex scanners (injection / secrets / PII)
│   │   └── policy.py              #   operational policy + HITL approval gate
│   │
│   ├── observability/             # ── Tier 5 ──
│   │   ├── tracing.py             #   OpenTelemetry spans (per step / tool / model call)
│   │   └── recorder.py            #   local JSONL trace (append-only audit trail)
│   │
│   ├── agents/                    # ── Multi-agent (MAS) ──
│   │   ├── subagent.py            #   SubAgent = harness instance with a role + toolset
│   │   ├── envelope.py            #   structured agent message envelope
│   │   ├── broker.py              #   in-process message bus
│   │   └── orchestrator.py        #   supervisor orchestrator — sub-agent fan-out
│   │
│   ├── tui/                       # ── Interactive UI (Textual — lazy-imported) ──
│   │   ├── app.py                 #   Agent86App: transcript, prompt, palette, key bindings,
│   │   │                          #   worker turns, cancellation, /config chains
│   │   ├── commands.py            #   the one declarative COMMANDS registry (dispatch + /help
│   │   │                          #   + palette), shared with the plain loop
│   │   ├── messages.py            #   Textual messages posted from the turn worker
│   │   ├── turn_bridge.py         #   sync threaded harness generator → async Textual messages
│   │   ├── widgets/
│   │   │   └── status_footer.py   #   live footer: model / ctx% / tokens / cost / phase
│   │   └── screens/
│   │       ├── approval.py        #   tool-approval modal (replaces the inline y/N)
│   │       ├── mode_picker.py     #   arrow-key approval-mode picker
│   │       ├── model_picker.py    #   arrow-key / type-to-filter model + catalog picker
│   │       ├── provider_manager.py#   /config model: list, add, edit providers
│   │       ├── key_entry.py       #   masked API-key / ${VAR} entry (never echoed)
│   │       ├── connection_test.py #   live provider connection test (worker + timeout)
│   │       ├── mcp_manager.py     #   /config mcp: server list + add/edit form
│   │       ├── mcp_test.py        #   MCP connection test with tool enumeration
│   │       └── save_diff.py       #   scope radio + TOML diff preview before any write
│   │
│   └── ui/
│       ├── repl.py                #   harness construction, TUI/plain routing, plain input() loop
│       └── status.py              #   status-line model (context %, tokens, cost, modes)
│
└── tests/
    ├── unit/                      # prompt templates, schema validators, state transitions
    ├── integration/               # simulated-world trajectory tests
    └── tui/                       # headless Textual `Pilot` tests of the screens and flows
```

---

## 5. The execution loop (Tier 2, the heart)

Based on the book's **ReAct** pattern with harness-enforced state transitions and error
correction at every step boundary (the book's key insight: *state drift is mathematical —
a 95%-accurate model fails 64% of the time over 20 steps; the harness corrects each step*).

```
load session state  ─────────────────────────────┐
        │                                         │
        ▼                                         │
[INGRESS GUARDRAIL]  scan user input              │
        │                                         │
        ▼                                         │
[ROUTER]  pick model by complexity/cost           │
        │                                         │
        ▼                                         │
[CONTEXT BUDGET]  real window − system prompt      │  ReAct
   − tool schemas − reserve − the output cap;      │  loop
   compact the oldest span if still over           │  (until DONE or
        │                                         │   circuit trips)
        ▼                                         │
[PROMPT COMPILE]  system + skills + history        │
   + tool schemas + budget-trimmed context         │
        │                                         │
        ▼                                         │
[COGNITIVE]  model proposes: text | tool_call(s)   │
   stopped at the output cap? continue, ≤3 times   │
        │                                         │
        ▼                                         │
[EGRESS GUARDRAIL]  validate proposal / schema     │
        │                                         │
   has tool call? ──no──► emit answer ─► VERIFY ──►┘ done
        │yes                                       │
        ▼                                         │
[POLICY / HITL]  approve every call up front       │
        │                                         │
        ▼                                         │
[SANDBOX]  reads in parallel (≤4), then writes     │
   in order (subprocess | docker | mcp)            │
        │                                         │
        ▼                                         │
[OBSERVE]  append ToolResults in CALL order,       │
   persist state, record trace, update counters ──┘
```

Every arrow crosses the deterministic harness. The model only ever sits in the `[COGNITIVE]`
box; it never touches the sandbox, the DB, or the terminal directly.

**Circuit breakers** (Tier 2 / `circuit.py`): abort the loop when any of
`max_steps`, `max_cost_usd`, `max_wall_clock_s`, or `max_consecutive_errors` is exceeded —
the antidote to the "naive ReAct infinite loop" failure mode. **`[limits] max_steps` is the
only step budget** — there is no hidden per-turn ceiling underneath it. A caller may pass an
explicit cap (a sub-agent passes `[agents] max_steps`), which is clamped with `min` so a
delegated task can *tighten* the bound but never widen it; `None` means "the configured budget
is the budget", resolved by an explicit `is None` check so an explicit `0` trips immediately
instead of being read as "unset".

**The context budget is recomputed before every request**, not once per session:
`Harness._context_budget` asks `capabilities.context_window_for` for the model's real window and
subtracts the compiled system prompt, the tool schemas, `limits.context_reserve_tokens`, and the
output cap the call will ask for (§8 for the derivation, §11 for the fields). Skills, MCP servers
and the episodic recall note all change the overhead mid-session, so a figure computed at startup
would be wrong by the second step. The result is published on the shared `WorkingMemory`, so
sub-agents trim to the same number.

**Compaction is a hook on that budget, before the request is built** — the model call must see the
compacted history, not a copy trimmed afterwards. It runs at most once per step, never
re-entrantly, and never raises: a failed summary degrades to the pre-v0.8 drop. See §8.

**Parallel tool dispatch.** A step's tool calls execute under one rule, deliberately the simplest
one that is safe:

1. **Approvals for the whole step are resolved first, sequentially, on the orchestrator's thread.**
   The gate may prompt a human, and it must be asked exactly once per call.
2. **Read-only calls then run concurrently** in a `ThreadPoolExecutor(max_workers=min(4, n))`.
3. **Side-effecting calls run afterwards, one at a time, in the order the model asked for them.**
   Two writes racing could interleave edits to one file, and a write racing a read could hand the
   model a half-written file; ordering them buys determinism for a little latency.

Results are observed in **call** order regardless of completion order, so the `TOOL` messages line
up with the assistant's `tool_calls` for every provider, and the `[tool] name(...)` start lines are
emitted for the whole batch up front rather than claiming an ordering that isn't real. A cancel
landing mid-batch skips the calls that have not started and gives them a `Not executed: cancelled`
result, so the history never keeps a `tool_use` that no `tool_result` answers. `Tool.parallel_safe`
(default `True`) is the per-tool opt-out — `delegate` sets it, because a nested agent loop has
approval prompts of its own and two racing for one terminal is not something the gate can untangle.
A single-call step and `[limits] parallel_tools = false` take the unchanged sequential path. What a
concurrent read touches is safe by construction: `ToolContext` is read-only for every built-in, the
sandbox executor holds no per-call state, and `MCPManager.call_tool` marshals onto its own
background loop.

**Continuation is a step, not a retry.** A completion whose `stop_reason` is `max_tokens` with no
tool calls is a *truncated* answer, not a finished one. The harness appends the partial assistant
text, asks the model to continue exactly where it left off, and calls again — up to **3** times per
turn, each one a full step the circuit breaker counts and budgets. The pieces stream as they arrive
and are stitched into one assistant message, so neither the partials nor the harness's own
continuation prompts survive into the history to be imitated next turn. A truncated step that then
calls a tool abandons the stitching: those tool results have to attach to the assistant message
that actually requested them.

**`TurnSummary` is published at the start of a turn, not the end** (`orchestration/state.py`;
deliberately not in `types.py` — it is an orchestration record, not part of the provider-agnostic
lingua franca). A UI can watch it fill, and its duration is stamped at *every* exit — done,
cancelled, blocked, aborted — so the per-turn read-out is written on the error path too. It carries
input/output/cache tokens, cost, steps, tool calls, duration, compactions, and continuations, and
`run --json` serialises it under an additive `turn` key.

**The error path is part of the loop.** A turn appends the user message before it calls the
model, so a failure in the model-call stream must not simply escape: any exception —
a `ProviderError`, or a raw `httpx.RemoteProtocolError` / `json.JSONDecodeError` from a truncated
SSE or NDJSON line — aborts the turn (ERROR phase, `turn_end status="error"`, state persisted)
*before* being re-raised, as the original `ProviderError` when the provider produced one and
wrapped in one naming provider + model otherwise. A stream that ends with no final completion
takes the same path. The result is a resumable session and a trace whose turns always end.

Transient failures don't get that far: the provider adapters retry them first (§6).

**Cancellation** is a first-class exit, not an exception leak. A cancelled turn records
`turn_end status="cancelled"` with the steps taken, persists state, and — in redact mode — still
emits whatever was buffered, redacted.

**Redact buffering.** When `[guardrails] egress = "redact"`, the step's text deltas are held back
and replayed from the *inspected* text (including the terminal done delta, whose ordering
consumers rely on), and the inspected text is what gets stored in the assistant message and the
episodic outcome. `warn`/`off` stream live and are untouched. See §9.

---

## 6. Cognitive Tier — provider abstraction

One interface, four backends. The orchestrator is model-agnostic.

```python
class ModelProvider(ABC):
    name: str
    supports_native_tools: bool          # Anthropic/OpenAI yes; local varies

    def complete(self, req: CompletionRequest) -> Completion: ...
    def stream(self, req: CompletionRequest) -> Iterator[CompletionDelta]: ...
    def count_tokens(self, messages: list[Message]) -> int: ...
    def embed(self, texts: list[str]) -> list[list[float]] | None: ...
```

- **Native tool-calling** is used throughout: Anthropic and OpenAI natively, and Ollama and
  llama.cpp by passing tools through to the server's own tool support (which varies by model).
  There is no prompt-level tool-emulation shim today — a local model without reliable function
  calling is a model to swap, not to emulate around. *Not built; see §15.*
- **Self-correction at the boundary** is real and is where the book's `SQLQueryProposal`
  discipline lives: arguments are validated against the tool's Pydantic `Args` model and a
  failure returns a structured `ToolResult` error the model can correct from — including
  "invalid JSON in tool arguments", raised before the registry, the approval gate, or any tool
  when a provider could not parse the streamed argument text (previously substituted with `{}`,
  which sent the model chasing a phantom missing field).
- **Dynamic routing** (`router.py`): a triage step classifies each turn and routes simple
  work to a cheap/local model and hard work to a frontier model. Configurable policy. The
  router caches one provider per model string; `invalidate()` clears that cache (keeping the
  pinned provider) so a runtime config change — a new key, a new `base_url`, a re-registered
  provider — actually reaches the next call instead of the session continuing against the old
  endpoint.

**Per-model facts** (`capabilities.py`) — the seam every provider and the loop ask, so a per-model
quirk lives in one declarative table rather than scattered conditionals. It answers three
questions: whether a model still accepts `temperature`/`top_p`/`top_k` (some families removed them
and return 400), `context_window_for(model_ref, config)` (§8), and
`max_output_tokens_for(model_ref, config)` — `[providers.<name>] max_tokens`, else
`[limits] max_output_tokens`.

**Output caps.** `CompletionRequest.max_tokens` is the per-call cap and every adapter honours it:

| Adapter | Parameter | No cap requested |
|---|---|---|
| Anthropic | `max_tokens` | request → `[providers.anthropic] max_tokens` → **8192** (the API requires the parameter, so a number always goes out) |
| OpenAI-compatible | `max_completion_tokens`, with **one** fallback swap to `max_tokens` | nothing sent |
| Ollama | `options.num_predict` | nothing sent |

The OpenAI fallback exists because most compatible endpoints (Groq, OpenRouter, vLLM, llama.cpp)
only know the older name and nothing in the base URL says which — so a 400 naming the parameter
triggers one swap, memoised **per endpoint** for the session. That retry is a deterministic
correction rather than a flaky endpoint, so it deliberately does not come out of the
transient-failure budget and still works with `max_retries = 0`. Adapters that front *local*
servers send no cap when nobody asked for one: a guessed ceiling truncates a generation that runs
free today, and the loop supplies `limits.max_output_tokens` when a default is wanted.

**`StopReason`** (`types.py`) — the normalized vocabulary `end_turn | tool_use | max_tokens |
stop_sequence | other`, so "was this answer truncated?" is one question the loop can ask
generically (it is what drives continuation in §5) instead of a different test per provider.
`Completion.stop_reason` stays `str | None`, so this is additive and `None` still means "the
provider said nothing". Anything unrecognised — Anthropic's `pause_turn`, `refusal`, whatever is
added next — maps to `other` rather than being read as a finished turn; and a compatible server
reporting a plain `stop` on a turn that emitted tool calls maps to `tool_use`, because the turn is
not over, a tool is about to run.

**Prompt caching** (Anthropic) — caching is a prefix match over **tools → system → messages**, so a
breakpoint on the *last tool* caches the whole tool list and one on the *system block* caches
tools + system. Both are stable while the conversation after them is not, which is the split
caching pays for; at most two of the four available breakpoints are used, leaving room for a caller
that marks message content. A marker is placed only when the prefix it closes clears that model's
minimum cacheable length — below it the API silently ignores the marker and returns
`cache_creation_input_tokens: 0`, spending a breakpoint for nothing — and that minimum is **not**
monotonic across generations (512 on the newest models, 4096 on Opus 4.6/4.5 and Haiku 4.5), so it
is a per-family table with a conservative 4096 fallback for a model released after it was written.
Length is estimated at ~4 chars/token rather than spending a `count_tokens` round trip per turn on
a decision whose only cost when wrong is an ignored marker. The system string is converted to the
block-list form only when it is being marked, so an unmarked request goes out byte-identical to
before. `[providers.<name>] prompt_cache` is the off switch.

`Usage.cache_read_tokens` / `Usage.cache_creation_tokens` carry the two classes across the seam.
**`input_tokens` is the whole prompt, with the cache fields a breakdown of it** — Anthropic reports
`input_tokens` as the uncached *remainder*, so the adapter sums them, otherwise a well-cached turn
would look like it barely used any context. OpenAI's `prompt_tokens_details.cached_tokens` follows
the same convention.

**Retry policy** (`retry.py`) — one module decides whether a provider failure is worth another
attempt and how long to wait, so the four adapters can't drift:

- **Retryable**: HTTP 429/500/502/503/504 and transport errors (`ConnectError`, `ConnectTimeout`,
  `RemoteProtocolError`). Everything else fails immediately.
- **Backoff**: exponential with equal jitter; `Retry-After` honoured as delta-seconds or an
  HTTP-date, both clamped.
- **Budget**: `[providers.<name>] max_retries` (default 2, `0` disables).
- **Invariant**: nothing is retried once a delta has been yielded — a second attempt would
  duplicate text the user has already seen, so that failure surfaces as a `ProviderError`. The
  Anthropic adapter passes `max_retries` to the SDK client rather than wrapping a client that
  already retries; llama.cpp inherits the OpenAI path.

**Pricing** (`pricing.py`) — a built-in table of USD per million tokens (Anthropic and OpenAI;
Groq and OpenRouter deliberately absent), with `[pricing.models]` config overrides layered on top
through a `Config` post-validation hook, because providers price usage deep inside a stream with
no access to the resolved config. Lookup tries the full `provider:model` ref, then the bare model
id, then a dated-snapshot prefix. Three outcomes stay distinct — **priced**, **local**
(`ollama`/`llamacpp`: zero is correct), and **unknown** (`None`, rendered as
`cost n/a (unpriced model)`) — so a cost meter never reports a paid call as free. This is what
makes `[limits] max_cost_usd` a real circuit breaker rather than dead code.

`Price.cost()` bills the three token classes apart: **cache reads at 0.1×** the input rate,
**5-minute cache writes at 1.25×**, and the uncached remainder at the input rate, with a per-model
override table where a model prices reads differently and optional explicit
`cache_read_per_mtok` / `cache_write_per_mtok` so a config override can state a rate instead of
inheriting the multiplier. Passing zeros reduces exactly to the pre-cache arithmetic. Billing every
prompt token at the input rate made the cap wrong in *both* directions — a fully-cached turn is a
tenth of the price, a cache write a 25% premium — which is precisely the kind of quietly-wrong
number v0.7 existed to remove.

---

## 7. Tool & Execution Tier — three sources, one registry

1. **Built-in tools** — `run_command` (shell), `read_file`, `write_file`, `edit_file`,
   `list_dir`, `web_fetch`, `python_exec`, plus `remember`/`recall`, `use_skill`, and
   `delegate`. (A `web_search` tool is *not* implemented — see §15.)
2. **MCP client** — connect to MCP servers (stdio/HTTP); their tools are registered
   into the same registry with the same schema/guardrail treatment.
3. **Skills** — self-contained folders discovered from skill paths:

```
skills/my-skill/
├── SKILL.md          # frontmatter: name, description, (optional) allowed-tools
│                     # body: instructions loaded into context on demand
└── (scripts/refs/…)  # resources the skill may reference
```

Skills use **progressive disclosure**: only `name` + `description` sit in context until the
model chooses to invoke the skill, at which point its full instructions load. Keeps the
token budget lean (the book's Pillar-2 working-memory discipline).

**File edits are exact-match and answer with a diff.** `edit_file(path, old_string, new_string,
replace_all)` replaces a literal span — not a regex, not a line range — and refuses in a way the
model can act on: "0 matches … copy the text verbatim", "3 matches … add context, or pass
`replace_all=true`". The pre-v0.9 `old`/`new` argument names remain accepted aliases. The tool
decodes and re-encodes the file itself rather than round-tripping through `read_text`/`write_text`:
a BOM is detected and restored, CRLF is normalised for matching and written back as CRLF, a mixed
file is left verbatim, and a non-UTF-8 file is refused rather than mangled by an
`errors="replace"` pass. Both `edit_file` and `write_file` answer with a unified diff, also carried
in `metadata["diff"]`; `unified_diff_for()` / `head_of()` / `read_file_text()` are the shared
helpers the approval preview reuses.

**`Tool.preview(arguments, ctx) -> ApprovalPreview | None`** is on the ABC so the approval gate can
show what a call *does* rather than 300 characters of its JSON (§9). It is called with the **raw,
unvalidated** arguments — the gate runs before validation — and must never raise; `build_preview`
swallows and logs it if it does. `write_file`/`edit_file` return a unified diff against the file on
disk (and say so when `old_string` is missing or ambiguous, naming the count); `run_command` and
`python_exec` return the whole command or snippet capped at 60 lines rather than truncated
mid-token. `ApprovalPreview` is a `str` subclass carrying `detail`/`lexer`, so the
`(tool_name, preview) -> bool` callback contract every caller implements is unchanged while a
caller that knows about the detail can render it.

**The Agent Skills convention, and `allowed-tools` as a gate.** `SKILL.md` frontmatter is parsed to
the convention skills are actually written to: the closing delimiter is a `---` on its own **line**
(splitting on the next three hyphens anywhere truncated any skill whose body had a horizontal
rule); block scalars (`>` folded, `|` literal), quoted values, and inline or block lists are
understood; PyYAML is used when it is installed and a built-in mini parser covers the same ground
when it is not, because **a skill must never need a dependency** (both paths are tested);
`allowed-tools` is space-delimited, with commas, brackets and YAML lists tolerated; `license` and
`metadata` are carried. `discover_skills(config, workspace)` searches, **first root wins**:

| # | Root | Scope |
|---|---|---|
| 1 | `<workspace>/.agent86/skills` | project |
| 2 | `<workspace>/.claude/skills` | project |
| 3 | `~/.agent86/skills` | user |
| 4 | `~/.claude/skills` | user |
| 5 | `[skills] paths` | configured extras |

so a project skill shadows a user skill and nothing shadows the project. Project roots resolve
against the explicit `workspace` rather than the process CWD (a caller that passes none keeps the
CWD fallback). `skill_roots()` feeds `default_policy`, so a skill's bundled resources — which for a
user skill live *outside* the workspace — are readable instead of a jail error on the first "see
`reference.md`".

Enforcement closes the loop the convention implies: `use_skill` records the active skill on
`ToolContext`, and `ToolRegistry.dispatch` **refuses** any tool outside a non-empty `allowed-tools`,
naming the skill and the list so the model can re-plan rather than retry. `use_skill` itself is
always callable (a skill that forgot to list it would be a one-way door), activating another skill
*replaces* the restriction rather than intersecting it, and `clear_skill()` lifts it at the end of
every turn — the allowlist is a property of the turn, not of the session. The compiled system
prompt lists each skill's `allowed-tools`, so the boundary is known before a refusal costs a step.

A tool name is claimed once. Bulk registration keeps the first registration, appends the loser to
`registry.collisions`, and logs it (naming the 64-character truncation when the clash is a
truncation artefact) instead of dropping it silently; the strict `register()` still raises, so an
explicit `add_mcp_server` reports the clash to the caller.

**Sandboxing** (`sandbox/`): every side-effectful tool runs through an executor governed by
a `SandboxPolicy` (path allow/deny + cwd jail, network egress allow/deny, env scrubbing,
output/time limits). Default = restricted subprocess; `--sandbox docker` escalates to a
container when Docker is available. The per-tool budget is `[limits] tool_timeout_s`.

- **Environment allowlist.** A tool subprocess gets a curated environment, never the harness's:
  `PATH` + locale/encoding vars, plus the platform set — Windows (`SYSTEMROOT`, `COMSPEC`,
  `APPDATA`, `TEMP`, …) or POSIX (`HOME`, `USER`, `LOGNAME`, `SHELL`, `TMPDIR`, `TERM`, `TZ`, the
  `LC_*`/`XDG_*` prefix families, and the CA-bundle vars, without which git/pip/npm break rather
  than merely being constrained). `[sandbox] env_passthrough` forwards extra variables **by
  name**; credential-looking names (`*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*API_KEY*`, `*_KEY`) are
  refused even when named explicitly, with a logged warning — an allowlist entry must not become a
  way to hand the model's subprocesses the key that pays for the model.
- **Process-tree kill on timeout.** Each command starts in its own process group
  (`CREATE_NEW_PROCESS_GROUP` on Windows, `start_new_session` on POSIX) and the *group* is killed
  on timeout (`taskkill /T /F` or `killpg`), with a bounded drain of the pipes — a timed-out
  `npm test` no longer leaves workers holding ports. Docker runs get a unique
  `--name agent86-<uuid>` and a timeout follows up with `docker kill`, because killing the
  `docker run` client leaves the container alive and `--rm` never fires. stdin is closed (EOF)
  rather than inherited, so a command that reads stdin fails fast.
- **`web_fetch` SSRF guard.** The fetch tool runs inside the user's trust boundary against a
  model-chosen URL, so every hop is vetted before a connection: `http`/`https` only; all A/AAAA
  answers resolved and refused when loopback, private, link-local, multicast, reserved, or
  unspecified (IPv4-mapped, 6to4 and Teredo forms unwrapped first); redirects followed **manually**
  with a bound of 5 hops, because automatic following lets a public host bounce the fetch into the
  private network; the body streamed and stopped at 2 MB *before* decoding; and a textual content
  type required. Refusals are structured `ToolResult` errors naming the reason and the
  `[tools] web_allow_private` escape hatch. The tool stays `side_effecting = False` — the guard,
  not the approval gate, is the mitigation.
- **MCP stdio servers get the same scrubbed environment.** A server that declared any `env` value
  used to receive `{**os.environ, **cfg.env}` — the whole host environment, every API key on the
  machine, handed to a third-party subprocess. It now gets `SandboxPolicy.scrubbed_env()` with its
  own `env` layered on top, so a server that needs one token gets exactly that token via `${VAR}`.
  An MCP tool whose annotations carry `readOnlyHint` is mounted `side_effecting = False`, so
  reading through a server stops prompting for approval.

---

## 8. Memory Tier (Pillar 2)

Single embedded store: **SQLite** for relational state + **`sqlite-vec`** for vectors.

| Layer | What | Backing |
|---|---|---|
| **Working** | Current context window; budgeted against the model's *real* window, compacted by summary when it overflows (the system prompt is held out of the trim) | in-memory, budget-managed |
| **Episodic** | Append-only trace of every past step/run ("flight data recorder"); similar-task lookup injects warnings on new tasks | SQLite tables + vec index |
| **Semantic** | User/domain knowledge; RAG retrieval | SQLite + vec index |

Embeddings default to local **sentence-transformers** (`all-MiniLM-L6-v2` / `bge-small`) —
fully offline. `Embedder` is an ABC so provider embeddings can be swapped in later.

**Retrieval & scale.** Search uses sqlite-vec's native `vec_distance_cosine` (distance in C,
sort/limit in SQLite) when the extension is loaded, and a dependency-free Python cosine scan
otherwise. Both are a **full linear scan** — there is no ANN index. This is a deliberate fit
for personal-scale memory (comfortably into the tens of thousands of rows); it is *not* built
for millions. Retention caps bound the episode/session log automatically; curated facts are
never auto-pruned. If scale ever demands it, sqlite-vec's `vec0` virtual table would add a
true vector index — an intentional, isolated upgrade behind the same `MemoryStore` API.

**The conversation budget** (`memory/working.py`, `cognitive/capabilities.py`). Before v0.8 working
memory was constructed with `limits.max_context_tokens` — a flat 8000 for every model, which wasted
~96% of a 200k window and overspent a 4k local one, and which ignored the two things in every
request before any history. The budget is now derived:

```
window            = context_window_for(model_ref, config)
conversation      = window − (system prompt + tool schemas)
                           − limits.context_reserve_tokens
                           − max_output_tokens_for(model_ref, config)
                    …clamped by limits.max_context_tokens when one is set
```

The **window** resolves in priority order: a `[model.context_window]` override (full
`provider:model` ref, then bare id) → the *provider* where the server rather than the model owns
the window (Ollama serves `[providers.ollama] num_ctx`; llama.cpp's `-c` is a launch flag not
discoverable over the API, so 8192 is the only honest answer) → a built-in family table (Claude
4.x/5.x 200k; `gpt-5` 400k, `gpt-4.1` 1,047,576, `gpt-4o` 128k, o-series 200k; common open-weights
ids) → 8192. The **reserve** is headroom for the provider's token counting differing from ours — an
error the model call otherwise pays for with a hard 400 — and is clamped to half the window so a
small local model is not starved; the result is floored at a minimum and only *then* clamped by
`limits.max_context_tokens`, so an explicitly typed hard cap is never overruled by the floor.
`ModelProvider.count_tokens` counts tool-call arguments and tool names, because a step whose entire
payload was a large tool argument used to measure as zero.

**Compaction** (`[limits] compaction`). When the conversation exceeds the budget, the oldest prefix
is replaced by a model-written digest — GOAL / DECISIONS / FACTS / OPEN, instructed to reproduce
paths, identifiers and numbers verbatim, ~600 tokens — written by the cheap route model when
routing is on and the current provider otherwise. The digest rides on a **USER** message headed
`[Conversation summary — earlier turns compacted]`: no new `Role`, nothing for a provider adapter
to learn, and it is *merged* into the following turn when that is also a USER message, because
consecutive user messages are a shape some providers reject (Anthropic's `_to_messages` renders
`TOOL` results as `user` as well). Invariants:

- an assistant `tool_calls` message is never separated from its `TOOL` results — the cut walks back
  off any `TOOL` message it lands on;
- the last 6 messages and the whole current user turn are never compacted;
- compaction runs at most once per step and never re-entrantly;
- it **never raises** — a failed or empty summary falls back to the pre-v0.8 drop and records
  `compaction status="failed"|"empty" fallback="drop"` in the trace.

The compacted `state.messages` is persisted immediately so a resume sees the compacted history, and
the originals are archived verbatim to episodic memory (`record_compaction`, `kind="compaction"`),
held out of `recall` so a new turn is never handed a raw transcript. `compaction = "drop"` restores
the sliding window exactly.

---

## 9. Guardrails & Observability (Tier 5 / Pillar 4)

- **Ingress** (`off` | `warn` | `block`) — prompt-injection heuristics, jailbreak patterns, PII
  detection on input; `block` refuses a turn carrying prompt injection. Findings are recorded as
  `guardrail stage="ingress_input"`. Tool observations are scanned too
  (`stage="observation"`, `[guardrails] scan_observations`).
- **Egress** (`off` | `warn` | `redact`) — secret/API-key/PII scanning on output, plus Pydantic
  schema validation of any structured proposal before it can reach the tool tier.
  - `warn` scans and reports (`stage="egress"`); the text streams live.
  - `redact` additionally **buffers the step's text deltas and replays them from the inspected
    text**, and stores the inspected text in the assistant message and the episodic outcome — so
    a secret is never shown, never persisted, and never recalled later. (Before v0.7 the redacted
    copy was computed and discarded: raw text had already been streamed and stored, making
    `redact` a synonym for `warn`.) A cancelled turn still emits its buffered partial, redacted.
  - In both `warn` and `redact`, **tool-call arguments are scanned**
    (`stage="egress_tool_args"`) — a model that reads a key from a file and posts it to a URL
    never puts it in its prose. The call is recorded, not blocked, and the arguments are not
    rewritten: the approval gate is what stops side effects, and rewriting would hand the tool
    something the model never asked for.
- **Operational policy** — cost caps, step caps, wall-clock and consecutive-error bounds, shared
  with the circuit breakers (§5). Provider-side rate limiting is *absorbed*, not enforced: a 429
  is retried with backoff and `Retry-After` (§6). The harness does not implement its own
  request-rate limiter.
- **HITL approvals** — permission modes (`auto` / `ask` / `deny`) per tool category;
  destructive or side-effectful calls surface an approval prompt (a modal in the TUI) before
  running. MCP tools annotated `readOnlyHint` are not gated. The prompt shows the call's
  **`Tool.preview`** (§7) — a unified diff for a file write, the whole command for a shell or
  Python call — rather than a truncated JSON dump of the arguments, so the question being answered
  is "do you want this change?" and not "do you trust this tool name?". `ApprovalGate(…, context=)`
  is optional and preview-only; without it file previews resolve against the CWD, which is the
  default workspace. The TUI renders the detail in a scrollable `rich.syntax.Syntax` panel, never
  as console markup (a diff is full of `[`), and takes `y`/`n` alongside `escape`; the plain loop
  asks `y/N` with the same detail when stdin is a TTY, and `run` without `--yes` still declines.
- **Observability** — two recorders, one always on. The **JSONL flight recorder**
  (`observability/recorder.py`) gives a local, greppable audit trail with no collector
  configured; **OpenTelemetry spans** (`observability/tracing.py`) wrap each turn, model call and
  tool execution when a collector is wanted. Neither is ever allowed to be the reason a turn
  fails: an event that cannot be serialised or a file that cannot be written is dropped silently
  rather than raised into the ReAct loop, and every tracing failure path degrades to "no traces",
  never to "no agent".

**The flight recorder** (v1.0) is append-only JSONL under `[observability] path`, one file per
machine, every event tagged with the session id. Two properties make it safe to leave on forever:

- **Redacted** (`observability/redact.py`). Everything the harness sees flows through it — the
  user's task text, the model's tool arguments, whatever a tool read off disk — into a file that
  outlives the session and gets attached to bug reports. `redact_event` is the one gate between an
  event and the file. Every string, at any depth, is rewritten with the **same regexes the
  guardrail tier already uses** — `guardrails/scanners.py` for provider key shapes and credential
  assignments, `secrets.py` for the key-shaped-token catch-all, *imported rather than re-spelled*,
  so there is one place to fix when a provider invents a new prefix — and a match becomes
  `***REDACTED***`, deliberately loud when grepping. Size is bounded separately: the big free-text
  fields (`arguments`, `task`, `content`, `error`, `outcome`) are clipped to
  `[observability] max_field_chars` with a visible `…[truncated N chars]`, and truncation is
  *inherited* — once inside `arguments`, every nested string is a candidate, because the model
  chooses those key names and the harness cannot enumerate them. It never raises: a value that
  cannot be walked or serialised falls back to `str()`, and a redaction failure degrades to the
  untouched event, because a trace that drops events is worse than a trace with a long line in it.
  `redact = "none"` is the explicit, local opt-out.
- **Rotated.** The live file is capped at `max_trace_bytes`; crossing it shifts `trace.jsonl` →
  `trace.1.jsonl` … `trace.N.jsonl` and drops the oldest generation past `keep_traces`. Rotation
  happens **between** events — flush, then rename — so no event is ever half-written, and the
  rename retries briefly, because on Windows another process holding the file open (a tail, an
  editor, a scanner) fails it with `PermissionError`; giving up is safe, since the writer keeps
  appending and tries again at the next crossing. `max_trace_bytes = 0` disables rotation.

Reading back streams rather than slurps: `read_events` holds at most `limit` records in memory,
and `trace_generations` walks the rotated files newest-first when the tail of the live file does
not hold enough *matching* events — which is what makes `trace show --kind tool_call -n 50` show
fifty tool calls rather than whatever few survive the last fifty events of any kind (§12).

**OpenTelemetry** (v1.0). Before v1.0 the tracer only called `trace.get_tracer`, which returns a
handle on the **no-op global provider** unless something else in the process has already installed
one — so with `otel = true` and the extra installed, spans were created and dropped on the floor.
`Tracer` now builds a provider of its own:

- a `Resource` carrying `service.name = "agent86"` and `service.version`;
- an exporter selected by `[observability] otel_exporter` — `otlp` (gRPC, falling back to HTTP
  when only the HTTP exporter is installed), `console` (stderr, for local debugging), or `none`
  (record, export nothing);
- a `BatchSpanProcessor`, flushed by `Tracer.close()` from `Harness.close()`.

The standard `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_EXPORTER_OTLP_HEADERS` are honoured — the
exporters read them themselves, which is how every other instrumented process is configured — and
`[observability] otel_endpoint` overrides them when config, not environment, is the source of
truth.

The provider is deliberately **not installed as the global provider**. agent86 is importable
inside a host that owns its own tracing, and calling `set_tracer_provider` would make stealing it
a side effect of an import; the tracer keeps its own handle instead and `get_tracer` is only used
on the fallback path. `Tracer.active` says whether spans are really being recorded and
`Tracer.note` carries the one-line reason when they are not ("otel enabled but the 'otel' extra is
not installed"), so a surface can say *why* instead of silently doing nothing. Nothing in the
module imports `opentelemetry` at module scope — the imports live inside `_build_provider`, which
only runs when tracing is switched on, so `agent86 run` never pays for them.

**The span tree**, following the GenAI semantic conventions where a name exists and `agent86.*`
where one does not:

```
turn                 session.id, gen_ai.request.model
├── model_call       gen_ai.system, gen_ai.request.model,
│                    gen_ai.usage.input_tokens / .output_tokens,
│                    gen_ai.response.finish_reasons
└── tool_call        tool.name, gen_ai.tool.name
```

The same four event kinds (`turn_start`, `turn_end`, `model_call`, `tool_call`) are what
`agent86 trace export -f otlp-json` reconstructs a span tree from, so a trace captured with no
collector running can still be handed to one afterwards (§12).

---

## 10. Multi-agent (MAS)

- **Agent** = a harness instance bound to a role, system prompt, and toolset.
- **Envelope** = structured message (sender, recipient, intent, payload, correlation id) —
  never raw natural language as a wire protocol (the book's "Babel problem").
- **Broker** = in-process async pub/sub for agent-to-agent messaging.
- **Orchestrator** = spawns sub-agents and fans work out over the **supervisor** topology, the
  one wired path. Pipeline and blackboard topologies, and harness-level conflict resolution
  (state-oscillation detection, gated locks), remain design intent — *not built; see §15.*

**Sub-agent accounting** (v0.7). A delegated turn is bounded and billed like any other work:

- Its step budget is `[agents] max_steps` (default 8), handed to its own `CircuitBreaker` and
  clamped by `[limits] max_steps` — a sub-agent can tighten the bound, never widen it.
- Its messages run through the *parent's* working memory, with the system prompt held out of the
  trim, so a delegated task can't blow the context window.
- It inherits the parent's compiled system prompt and skills list (it was previously offered
  `use_skill` with no skills to call it with) and records `model_call` events tagged with role
  and depth.
- It returns its `Usage`; `spawn_subagent` accumulates it on the harness and `run_turn` folds it
  into the step and the breaker's **cost** after each tool call — so delegated spend appears in
  `state.usage` and counts against `max_cost_usd`. Cost only, never `record_step`: a sub-agent is
  not one of the parent's model calls and must not shrink the parent's step budget. The
  `delegate` tool's `str -> str` contract is unchanged.

v0.1 shipped single-agent-first with the MAS scaffolding present; supervisor topology is the
first wired path.

---

## 11. Configuration

Layered resolution (later overrides earlier): **built-in defaults → `~/.agent86/config.toml`
→ project `./.agent86/config.toml` → env vars → CLI flags**. Secrets (API keys) come from
env or the OS keyring, never written to config files.

`config.py` is **read-only** — it resolves and validates, and never writes. Every write goes
through **`config_writer.py`**, the single writer: a tomlkit round-trip so existing comments and
formatting survive, a scope choice (user by default, project opt-in), a rendered diff the user
confirms before anything lands, and an atomic replace. It also carries the **SEC-01 guard** that
refuses secret-looking leaf keys, so an in-app flow physically cannot write a plaintext key.

**Secret resolution** (`secrets.py`) is: **environment variable first, then the OS keyring**
(`keyring`, lazy-imported). Existing env-var setups keep working unchanged, and a headless or
backend-less machine falls through silently rather than failing. Config never names a secret,
only the env var that holds it (`api_key_env`); MCP entries may hold a `${VAR}` reference, which
is expanded at connect time, at the transport boundary.

**Validated enums.** `model.router`, `sandbox.mode`, `guardrails.ingress`, and
`guardrails.egress` are `StrEnum`s (as `guardrails.approval` already was). They were plain
strings, so `egress = "redcat"` validated cleanly and silently turned a safety switch off — the
worst failure mode available to a guardrail. A bad value now raises a `ValidationError` naming
the allowed values, while every existing `== "triage"` / `== "docker"` / `== "off"` comparison
and f-string rendering keeps working, and `model_dump(mode="json")` still emits plain strings so
the tomlkit round-trip is unaffected.

```toml
[model]
default   = "anthropic:claude-opus-4-8"
router    = "triage"                 # off | triage                      (enum)
[model.route]
cheap     = "ollama:llama3.1"
frontier  = "anthropic:claude-opus-4-8"

[model.context_window]."ollama:qwen2.5:3b" = 16384   # override the resolved context window

[providers.anthropic]  api_key_env = "ANTHROPIC_API_KEY"  max_retries = 2
                       max_tokens = 8192     # per-provider output cap (None = provider default)
                       prompt_cache = true   # Anthropic only: mark the stable prefix cacheable
[providers.openai]     api_key_env = "OPENAI_API_KEY"  base_url = "https://api.openai.com/v1"
[providers.ollama]     base_url = "http://localhost:11434"
[providers.llamacpp]   base_url = "http://localhost:8080"

[pricing.models."anthropic:claude-sonnet-5"]   # override or add a rate; USD per million tokens
input_per_mtok = 3.0  output_per_mtok = 15.0

[ui]          tui = true             # false → the plain input() loop (pre-v0.6: `status_line`)
              markdown = true        # re-render a finished reply as Markdown in the transcript
              history_file = "~/.agent86/history"   # prompt history, shared by both surfaces
              history_size = 1000    # entries kept before the oldest are dropped

[skills]      enabled = true
              paths = []             # extra roots, searched after the four conventional ones

[sandbox]     mode = "subprocess"    # subprocess | docker               (enum)
              env_passthrough = []   # extra env var NAMES for tool/MCP subprocesses
[tools]       web_allow_private = false   # let web_fetch reach loopback/RFC1918 (SSRF escape hatch)
              mention_max_bytes = 200_000 # largest file an `@path` mention may inline
[guardrails]  approval = "ask"       # auto | ask | deny  (per-category overrides allowed)
              ingress = "warn"       # off | warn | block                (enum)
              egress  = "warn"       # off | warn | redact               (enum)
[memory]      path = "~/.agent86/memory.db"  embeddings = "sentence-transformers:all-MiniLM-L6-v2"
[observability]
              trace = true           # the JSONL flight recorder
              path = "~/.agent86/traces"
              redact = "secrets"     # secrets | none                      (enum)
              max_field_chars = 2000 # clip for arguments/task/content/error/outcome
              max_trace_bytes = 50_000_000  # rotate past this; 0 = never rotate
              keep_traces = 5        # rotated generations kept
              otel = false           # emit OpenTelemetry spans (needs the `otel` extra)
              otel_exporter = "otlp" # otlp | console | none                (enum)
              otel_endpoint = ""     # overrides OTEL_EXPORTER_OTLP_ENDPOINT when set
[limits]      max_steps = 40  max_cost_usd = 5.0  max_wall_clock_s = 900  tool_timeout_s = 60
              max_context_tokens = 0        # optional HARD cap on conversation tokens; 0 = none
              max_output_tokens = 8192      # per-call generation cap when no provider names one
              context_reserve_tokens = 4096 # headroom kept free inside the window
              compaction = "summarize"      # summarize | drop                    (enum)
              parallel_tools = true         # run a step's read-only tool calls concurrently
[agents]      max_steps = 8          # per-sub-agent cap, clamped by limits.max_steps

[mcp.servers.example]  command = "npx"  args = ["-y", "some-mcp-server"]   # stdio (local subprocess)
[mcp.servers.remote]   url = "https://mcp.example.com/mcp"  enabled = true  # streamable HTTP (transport inferred)
[mcp.servers.remote.headers]  Authorization = "Bearer ${TOKEN}"           # optional auth headers
```

Fields added in v0.7: `providers.<name>.max_retries` (2), `agents.max_steps` (8),
`tools.web_allow_private` (false), `sandbox.env_passthrough` (`[]`), `limits.tool_timeout_s` (60),
and the `[pricing.models]` table. `env_passthrough` holds variable **names** only — values are
read from the parent environment at spawn time, so the "no secrets in config" rule (§11 opening,
and the `config_writer` guard) still holds. `[limits] tool_timeout_s` replaces the old derived
per-tool timeout (`max_wall_clock_s if under 120 else 60`), which silently shortened every tool
timeout for anyone who lowered their run budget.

Fields added in v0.8: `providers.<name>.max_tokens` (`None`), `providers.<name>.prompt_cache`
(`true`), `limits.max_output_tokens` (8192), `limits.context_reserve_tokens` (4096),
`limits.compaction` (`"summarize"`), `limits.parallel_tools` (`true`), and the
`[model.context_window]` override table. **`limits.max_context_tokens` changed meaning**: it was a
flat `8000` that *was* the conversation budget; it now defaults to `0` = "no cap" and, when set, is
an optional hard cap applied on top of the derived budget (§8). Anyone who had deliberately chosen
a value keeps exactly that value.

Fields added in v0.9: `[ui] history_file` (`~/.agent86/history`), `[ui] history_size` (1000),
`[ui] markdown` (`true`), and `[tools] mention_max_bytes` (200000). All four are additive with
defaults, so an existing config keeps its behaviour: the history file is created on first write and
a missing or unwritable one degrades to "this session only" rather than failing a REPL start.
`[skills] paths` is unchanged but now *last* in a five-root search order (§7), where it used to be
one of three.

Fields added in v1.0 — six under `[observability]`, all additive with defaults, so an existing
config keeps working and starts getting a redacted, bounded trace for free:

| Field | Default | What it does |
|---|---|---|
| `redact` | `"secrets"` | `secrets` rewrites secret-shaped values and clips the big free-text fields; `none` writes events exactly as the loop emitted them (`RedactMode` enum) |
| `max_field_chars` | `2000` | clip applied to `arguments` / `task` / `content` / `error` / `outcome` and anything nested inside them |
| `max_trace_bytes` | `50_000_000` | cap on the live trace file; crossing it rotates. `0` disables rotation |
| `keep_traces` | `5` | rotated generations kept (`trace.1.jsonl` … `trace.N.jsonl`); `0` keeps no history |
| `otel_exporter` | `"otlp"` | where spans go when `otel = true`: `otlp` \| `console` \| `none` (`OtelExporter` enum) |
| `otel_endpoint` | `None` | overrides `OTEL_EXPORTER_OTLP_ENDPOINT`; unset means "whatever the standard `OTEL_*` env vars say" |

`redact` and `otel_exporter` are `StrEnum`s, for the same reason the v0.7 mode fields are (§11
above): a typo in a field that governs whether secrets reach disk must fail validation, not
silently turn the scrubbing off. The defaults are the safe ones — redaction is on and rotation is
bounded without anyone opting in — because the flight recorder was the one place in the harness
where a credential could come to rest in plain text on disk without a user choosing to put it
there.

An MCP server is reached over one of three transports: **stdio** (default — set `command`),
**streamable HTTP** (default when `url` is set), or **SSE** (`url` + `transport = "sse"`). Exactly
one of `command`/`url` is required; the transport is inferred but can be set explicitly.
`enabled = false` keeps a server configured but unmounted.

---

## 12. CLI surface

```
agent86                          # interactive: the full-screen Textual TUI
agent86 --plain                  # interactive: the plain input() loop
agent86 run "goal"               # one-shot; prints result, exits (scriptable/pipeable)
agent86 run "goal" --json        # structured output for automation
agent86 --model ollama:llama3.1  # override model
agent86 --sandbox docker         # override sandbox
agent86 config [get|set|path]    # inspect/edit config
agent86 skills [list|show NAME]  # manage skills
agent86 mcp [list|add|remove]    # manage MCP servers
agent86 trace [path|show|export] # inspect and export the flight recorder
agent86 models                   # list configured/available models across providers
```

**The trace sub-app** (v1.0). `trace path` prints the live file and every rotated generation with
its size. `trace show` and `trace export` share one reader, `_read_trace`, which applies the
filters **before** the limit and streams generation by generation, so a filtered `-n` returns that
many *matching* events rather than whatever survives the last N events of any kind:

```
agent86 trace show   [-s SESSION] [-n LIMIT] [-k KIND]... [--since 30m|2h|7d]
agent86 trace export [-s SESSION] [-n LIMIT] [--since 2h] [-f jsonl|json|otlp-json] [-o FILE]
```

`--since` parses `30s` / `15m` / `2h` / `7d` (a bare number is seconds). `show` renders
`time · session · kind · in · out · cost · detail`, with the token and cost columns filled only on
a `model_call` — where they are the only place they mean anything — and a totals line beneath the
table. `export` writes `jsonl` (the filtered events), `json` (one array), or **`otlp-json`**, which
reconstructs a span tree from the four span-shaped event kinds (§9) with **derived**, not random,
span ids, so exporting the same trace twice produces identical output and re-exporting is
idempotent. Everything else the recorder writes — guardrail hits, compactions, routing decisions —
stays in the JSONL views, where it is greppable.

**`run_turn(user_text, state, *, display_text=None)`** (v1.0). The model gets `user_text`, which
for an interactive turn is the *expanded* prompt with `@file` blocks inlined; `display_text` is
what the user actually typed, and it is what titles the session and what `turn_start` records in
the trace. Without it, a prompt whose body was an inlined file named the session after 60
characters of that file. The parameter is keyword-only and falls back to `user_text`, so every
existing caller is unaffected.

**A memory database that will not open degrades, rather than refusing to start** (v1.0). A locked
file (a second agent86 running) or an unwritable home used to raise a bare `sqlite3` error several
frames deep. `MemoryStore` raises `MemoryStoreError` naming the file and offering the fixes, the
CLI turns it into a message, and `Harness` catches it and **runs with memory disabled plus a
visible note** — the same degradation rule every optional dependency follows (§13).

**Two interactive surfaces, one command registry.** The default is the **TUI** (`tui/app.py`):
a Markdown transcript, a multi-line prompt, a live status footer (model · ctx% · tokens · cost ·
phase, updating *while* a turn runs), a `/`-triggered command palette with autocomplete,
arrow-key pickers for commands that need a choice, and a modal approval dialog. The harness is
built once, in `ui/repl.py`, and handed to `run_tui`.

The **plain loop** (stdlib `input()`) runs when `[ui] tui = false`, `--plain`, `AGENT86_PLAIN`,
a non-TTY stdin/stdout, or Textual can't be imported or started. Both surfaces dispatch through
the same declarative `COMMANDS` registry in `tui/commands.py`, which also backs `/help` and the
palette, so the two can't drift; commands that need a modal return a plain-mode explanation.
Textual is imported only on the TUI path, so `run` and `--plain` never pay for it. The two share
more than the registry: one prompt-history file, one mention expander (`tui/mentions.py` imports no
Textual, and `_Repl.expand_mentions` is the seam), and one approval preview.

In-app commands: `/help`, `/config`, **`/config model`**, **`/config mcp`**, `/models`,
`/model`, `/tools`, `/skills`, `/memory`, `/mode [ask|auto|deny]`, `/cost`, **`/sessions`**,
**`/resume [id]`**, `/clear`, `/exit`.

- **`/config model`** — provider manager → catalog picker (live models endpoint, type-to-filter,
  free-text fallback) → masked key entry (stored in the OS keyring) → live connection test →
  TOML diff preview → `config_writer` write → the new model takes effect on the next turn.
- **`/config mcp`** — server list → add/edit form (stdio · SSE · HTTP) → `${VAR}` resolution
  through the same masked entry → connection test that starts the server and enumerates its
  tools → diff preview → write → **live mount** of the tested server's tools into the running
  session. Remove and enable/disable go through the identical diff-and-confirm gate.

- **`/sessions` / `/resume [id]`** — a session is named after the first thing the user said to it
  (collapsed, 60 characters), stored by `MemoryStore.save_session` and read back through
  `SessionInfo` / `recent_sessions()` / `session_title()`, so no UI ever touches a sqlite `Row`.
  `Harness._persist` names a session **once**, on the first persist that has a user message to name
  it after, asking the store first so a compaction that drops the opening message can't silently
  rename the conversation. `/resume` accepts the 8-character prefix the listing shows and refuses
  an ambiguous one rather than guessing; with no argument it raises `SessionPickerModal` (a filter
  `Input` over an `OptionList`, shaped like `CatalogPickerModal`, options built as Rich `Text`
  because titles are user input).

**The transcript is a model, not a log.** The widget stays a `RichLog` — append-only, cheap to
stream into, and what every other surface queries as `#transcript` — but `tui/widgets/transcript.py`
keeps an ordered list of **entries** beside it, any of which may change how it renders after it was
first written; a re-render replays the list into the log. That buys two things without slowing
streaming down:

- **Markdown on completion.** A reply streams as plain escaped text and is re-rendered once, as a
  single `rich.markdown.Markdown` document, when it completes (turn end, a harness notice, or the
  next tool call). Re-parsing per delta is the cost this avoids, and a half-written fence or table
  would render as garbage. Fenced code goes through `Syntax(word_wrap=True)`; Markdown never parses
  console markup, so model text like `[/weird]` can neither raise `MarkupError` on the main thread
  nor vanish into a style tag. A reply with no Markdown structure is not re-rendered at all.
  `[ui] markdown` is the switch. `UserEntry` (the prompt echo) and `NoticeEntry` (`[compacted …]`,
  `[continuing …]`) are always plain and escaped.
- **Collapsible tool-call blocks.** One call is one block: `▸ name(args) → summary`, cropped to the
  terminal width, expandable (`ctrl+o` for the last, `ctrl+shift+o` for all) to the full arguments
  as pretty JSON and the full result, capped at 200 lines with a truncated tail. The full data
  comes from the session state via `turn_bridge`, not from the delta lines — the loop appends the
  assistant message (with `tool_calls`) before announcing a call and the `TOOL` message before
  summarising one, so both are looked up and posted with the UI message, which also stopped result
  lines falling through to `TurnDelta` and reading as model speech. A block is rendered when its
  result lands (its header is never rewritten), its slot reserved at announce time, and a call the
  turn never observed is flushed at turn end. Everything inside renders through `rich.text.Text`.
  *Not* a Textual `Collapsible`: a `RichLog` renders to strips and cannot host interactive
  children, so toggling is keyboard-driven rather than click-driven (BACKLOG).

**The prompt is a composer.** `tui/widgets/prompt_input.PromptInput` is a `TextArea` that keeps the
`Input` interface (`.value`, `.clear()`, a `Submitted` message whose `.input` aliases the widget),
so it swapped into the app without reopening turn handling: Enter submits, Shift+Enter and Ctrl+J
insert newlines, Up/Down walk history from the first/last line only, Escape clears the draft, and
it grows to 8 rows before scrolling. History is `ui/history.PromptHistory` — Textual-free,
stdlib-only, bash's rules (no blanks, no leading-space lines, no consecutive duplicates, capped at
`[ui] history_size`, atomic append with a temp-file rewrite when the cap trims it), degrading to
"this session only" on a missing, unwritable or corrupt file, and built lazily so constructing a
REPL never reads the user's real file. `@path` / `@"path with spaces"` mentions are expanded on
submit by `tui/mentions.expand_mentions`: every path goes through `SandboxPolicy.resolve_within`
**first**, so a path outside the jail is refused and never opened — not stat'ed, not sniffed, not
read — and what is inlined is bounded by `[tools] mention_max_bytes`, 200 names for a directory
listing, a binary refusal, and a fence long enough to survive backticks in the content. Refusals go
to the user *and* into the prompt, so neither side assumes a file arrived when it didn't.

**Three seams hold the app together**, so a widget can be replaced without reopening turn handling:
`submit_prompt(text)` is everything `Input.Submitted` does after clearing the box (one dispatch
path for any input widget), `open_session_picker()` pushes the picker lazily and guarded, and
`load_session(state)` makes a state live and rebuilds the transcript from its messages — prompts
echoed plain, assistant turns through the Markdown path, every tool call a collapsed block with its
arguments and result attached.

**A failed turn names what raised it.** The line leads with the exception **type**, keeps the
(escaped) message, and is followed by a dim `see agent86 trace show -s <session>` — a wrapped
provider failure used to render as `error: <str(exc)>`, which says what went wrong but never what
raised it, and left no way to get at the rest.

**Cancellation.** `Escape` (when no palette, modal, or draft owns it) and `Ctrl+C` cancel a running
turn and return to the prompt; `Ctrl+C` with no turn running — or a second press — quits, as does
`Ctrl+Q`. `Shift+Tab` cycles the approval mode live. Shutdown tears the workers down and
releases any pending approval with a bounded wait, so quitting can never hang on a modal nobody
is left to answer.

---

## 13. Dependencies (planned)

| Purpose | Package |
|---|---|
| CLI framework | `typer` |
| Terminal UI | `rich`, `textual` (lazy-imported) |
| Config write-back | `tomlkit` (lazy-imported) |
| Secrets | `keyring` (lazy-imported, optional at runtime) |
| Validation | `pydantic` v2 |
| HTTP | `httpx` |
| Anthropic | `anthropic` |
| OpenAI-compatible | `openai` |
| Local vectors | `sqlite-vec` |
| Embeddings | `sentence-transformers` (optional extra) |
| MCP | `mcp` (Python SDK) |
| Tracing | `opentelemetry-sdk`, `opentelemetry-exporter-otlp` |
| Sandbox (opt-in) | `docker` |

Heavy/optional deps (`sentence-transformers`, `docker`) live behind extras:
`agent86[local]`, `agent86[docker]`, `agent86[all]`.

---

## 14. Build phases

1. **Skeleton** — package, `pyproject.toml`, config, types, `agent86` entry point, empty tiers.
2. **Cognitive + loop** — provider ABC + Anthropic + Ollama adapters; minimal ReAct loop; REPL.
3. **Tools + sandbox** — registry, built-in tools, subprocess sandbox, HITL approval gate.
4. **Memory** — SQLite + sqlite-vec store; working/episodic/semantic; embeddings.
5. **Guardrails + observability** — ingress/egress, circuit breakers, OTel + flight recorder.
6. **Skills + MCP** — skill loader; MCP client mounting external tools.
7. **Remaining providers + routing** — OpenAI-compatible, llama.cpp; dynamic router.
8. **Multi-agent** — broker, envelope, sub-agent orchestrator (supervisor topology).
9. **Docker sandbox + polish** — container executor; tests; docs.

---

> **Build status:** All nine phases are implemented, tested, and verified live. Phase 4
> (memory), 5 (guardrails/observability), 8 (multi-agent), and 9 (Docker sandbox) each shipped
> with a graceful-degradation path so the harness runs without heavy optional deps.

## 15. Non-goals, and design intent not yet built

> **1.0 status.** Nothing this document specifies as part of the harness remains unbuilt. The
> three rows that closed in v1.0 — a configured OTel exporter, flight-recorder redaction, and
> flight-recorder rotation (all §9) — were the last entries here that described the *contract*
> rather than an alternative to it. What is left below is either an explicit non-goal, an
> alternative implementation of something that already works, or an evaluation the project has
> not written yet; each is tracked in `docs/BACKLOG.md`.

**Non-goals (still, as of v1.0):**

- Distributed/networked multi-host agents (in-process MAS only).
- gVisor / WASM sandboxes (subprocess + Docker only; WASM is a later option).
- A hosted service / web UI — this is a local-first CLI.
- A harness-side request-rate limiter. Provider rate limits are *absorbed* (429 → backoff +
  `Retry-After`, §6), not pre-empted.

**Described above as design intent, deliberately not implemented yet.** Each is marked *not
built* at its section; the full list with analysis is in `docs/BACKLOG.md`.

> Three rows left this table in v1.0, all of them §9 observability: a configured OTel exporter
> (the tracer now owns a `TracerProvider` with a `BatchSpanProcessor`, rather than handing spans
> to the no-op global provider), flight-recorder **redaction**, and flight-recorder **rotation**.
> Alongside them, and never a row here because it was distribution rather than described design
> intent, the project is now published to PyPI from a `v*` tag (`docs/RELEASING.md`).
> One row left this table in v0.9: `SKILL.md` `allowed-tools` is now enforced as a gate (§7),
> alongside the rest of the "coding-agent UX" set, none of which were rows here because they were
> UI surface rather than described design intent — the Markdown transcript, collapsible tool-call
> blocks, the multi-line prompt with history, `@file` mentions, the session picker, the approval
> diff (§9), and exact-match `edit_file` (§7). Four rows left in v0.8, all of them "Context & cost":
> summarization of the compacted span (§8), Anthropic prompt-cache breakpoints (§6), parallel
> execution of a step's read-only tool calls (§5), and `max_tokens` continuation (§5).

| Not built | Area | Tracked |
|---|---|---|
| Prompt-level tool-emulation shim for models without native tool calling | §6 cognitive | — (swap the model) |
| An eval for compaction *quality* — the summary is tested for shape, not for what it preserves | §8 memory | BACKLOG § Context & cost |
| Auto-sizing Ollama's `num_ctx` to the hardware (now the input to `context_window_for`) | §8 memory | BACKLOG § Ollama `num_ctx` |
| A `web_search` built-in tool | §7 tools | — (use an MCP search server) |
| Pipeline / blackboard topologies; state-oscillation detection and gated locks | §10 MAS | BACKLOG |
| Click-to-toggle tool-call blocks — a `RichLog` cannot host interactive children | §12 TUI | BACKLOG § TUI |
| History *navigation* in the plain loop — stdlib `input()` has no line editor | §12 TUI | BACKLOG § TUI |
| A read/write split in the sandbox jail, so a skill root granted for reading isn't also writable | §7 tools | BACKLOG § Skills & tools |
| A `trace show` view of *what* a compaction summarized — the originals are archived, but unreadable from the CLI | §9 observability | BACKLOG § Context & cost |
