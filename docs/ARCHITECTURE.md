# agent86 — Architecture & Specification

> An agentic harness on the command line. A Python CLI that connects to remote or
> local models and lets them use tools and skills — built as a faithful, runnable
> implementation of the five-tier architecture and four pillars described in
> *The Agentic Harness* (Tony Fleming, 2026).

**Status:** Implemented (Phases 1–9 complete), then extended through v0.7.0. This document is
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
`web_fetch` / sandbox-environment / MCP-environment / process-tree security fixes (v0.7).
**Version:** 0.7.0

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
[PROMPT COMPILE]  system + skills + history        │  ReAct
   + tool schemas + budget-trimmed context         │  loop
        │                                         │  (until DONE or
        ▼                                         │   circuit trips)
[COGNITIVE]  model proposes: text | tool_call(s)   │
        │                                         │
        ▼                                         │
[EGRESS GUARDRAIL]  validate proposal / schema     │
        │                                         │
   has tool call? ──no──► emit answer ─► VERIFY ──►┘ done
        │yes                                       │
        ▼                                         │
[POLICY / HITL]  approve side-effectful calls      │
        │                                         │
        ▼                                         │
[SANDBOX]  execute tool (subprocess|docker|mcp)    │
        │                                         │
        ▼                                         │
[OBSERVE]  append ToolResult, persist state,       │
   record trace, increment cost/step counters ────┘
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
| **Working** | Current context window; token-budgeted sliding window (the system prompt is held out of the trim) | in-memory, budget-managed |
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

**Not yet built.** Working memory *drops* the oldest span when the budget is exceeded; it does
not summarize it. Recursive/rolling summarization of the trimmed span, and Anthropic prompt-cache
breakpoints for the stable system + tool-schema block, are tracked in `docs/BACKLOG.md`
§ "Context & cost" (see also §15).

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
  running. MCP tools annotated `readOnlyHint` are not gated.
- **Observability** — OpenTelemetry spans wrap each step, model call, and tool execution;
  a parallel append-only **JSONL flight recorder** gives a local, greppable audit trail even
  with no OTel collector configured.

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

[providers.anthropic]  api_key_env = "ANTHROPIC_API_KEY"  max_retries = 2
[providers.openai]     api_key_env = "OPENAI_API_KEY"  base_url = "https://api.openai.com/v1"
[providers.ollama]     base_url = "http://localhost:11434"
[providers.llamacpp]   base_url = "http://localhost:8080"

[pricing.models."anthropic:claude-sonnet-5"]   # override or add a rate; USD per million tokens
input_per_mtok = 3.0  output_per_mtok = 15.0

[ui]          tui = true             # false → the plain input() loop (pre-v0.6: `status_line`)

[sandbox]     mode = "subprocess"    # subprocess | docker               (enum)
              env_passthrough = []   # extra env var NAMES for tool/MCP subprocesses
[tools]       web_allow_private = false   # let web_fetch reach loopback/RFC1918 (SSRF escape hatch)
[guardrails]  approval = "ask"       # auto | ask | deny  (per-category overrides allowed)
              ingress = "warn"       # off | warn | block                (enum)
              egress  = "warn"       # off | warn | redact               (enum)
[memory]      path = "~/.agent86/memory.db"  embeddings = "sentence-transformers:all-MiniLM-L6-v2"
[limits]      max_steps = 40  max_cost_usd = 5.0  max_wall_clock_s = 900  tool_timeout_s = 60
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
agent86 trace [show|tail]        # inspect the flight recorder
agent86 models                   # list configured/available models across providers
```

**Two interactive surfaces, one command registry.** The default is the **TUI** (`tui/app.py`):
a scrollable transcript, a prompt input, a live status footer (model · ctx% · tokens · cost ·
phase, updating *while* a turn runs), a `/`-triggered command palette with autocomplete,
arrow-key pickers for commands that need a choice, and a modal approval dialog. The harness is
built once, in `ui/repl.py`, and handed to `run_tui`.

The **plain loop** (stdlib `input()`) runs when `[ui] tui = false`, `--plain`, `AGENT86_PLAIN`,
a non-TTY stdin/stdout, or Textual can't be imported or started. Both surfaces dispatch through
the same declarative `COMMANDS` registry in `tui/commands.py`, which also backs `/help` and the
palette, so the two can't drift; commands that need a modal return a plain-mode explanation.
Textual is imported only on the TUI path, so `run` and `--plain` never pay for it.

In-app commands: `/help`, `/config`, **`/config model`**, **`/config mcp`**, `/models`,
`/model`, `/tools`, `/skills`, `/memory`, `/mode [ask|auto|deny]`, `/cost`, `/clear`, `/exit`.

- **`/config model`** — provider manager → catalog picker (live models endpoint, type-to-filter,
  free-text fallback) → masked key entry (stored in the OS keyring) → live connection test →
  TOML diff preview → `config_writer` write → the new model takes effect on the next turn.
- **`/config mcp`** — server list → add/edit form (stdio · SSE · HTTP) → `${VAR}` resolution
  through the same masked entry → connection test that starts the server and enumerates its
  tools → diff preview → write → **live mount** of the tested server's tools into the running
  session. Remove and enable/disable go through the identical diff-and-confirm gate.

**Cancellation.** `Escape` (when no palette or modal owns it) and `Ctrl+C` cancel a running turn
and return to the prompt; `Ctrl+C` with no turn running — or a second press — quits, as does
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

**Non-goals (still, as of v0.7):**

- Distributed/networked multi-host agents (in-process MAS only).
- gVisor / WASM sandboxes (subprocess + Docker only; WASM is a later option).
- A hosted service / web UI — this is a local-first CLI.
- A harness-side request-rate limiter. Provider rate limits are *absorbed* (429 → backoff +
  `Retry-After`, §6), not pre-empted.

**Described above as design intent, deliberately not implemented yet.** Each is marked *not
built* at its section; the full list with analysis is in `docs/BACKLOG.md`.

| Not built | Area | Tracked |
|---|---|---|
| Recursive/rolling summarization of the trimmed context span | §8 memory | BACKLOG § Context & cost |
| Anthropic prompt-cache breakpoints for the stable prompt + tool-schema block | §6 cognitive | BACKLOG § Context & cost |
| Parallel execution of a turn's independent tool calls | §5 loop | BACKLOG § Context & cost |
| `max_tokens` continuation after a truncated response | §5 loop | BACKLOG § Context & cost |
| Prompt-level tool-emulation shim for models without native tool calling | §6 cognitive | — (swap the model) |
| A `web_search` built-in tool | §7 tools | — (use an MCP search server) |
| Pipeline / blackboard topologies; state-oscillation detection and gated locks | §10 MAS | BACKLOG |
| `SKILL.md` `allowed-tools` enforced as a gate rather than documentation | §7 skills | BACKLOG § Skills & tools |
| A configured OTel exporter; flight-recorder redaction and rotation | §9 observability | BACKLOG § Observability |
