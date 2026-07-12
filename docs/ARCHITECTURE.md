# agent86 — Architecture & Specification

> An agentic harness on the command line. A Python CLI that connects to remote or
> local models and lets them use tools and skills — built as a faithful, runnable
> implementation of the five-tier architecture and four pillars described in
> *The Agentic Harness* (Tony Fleming, 2026).

**Status:** Implemented (Phases 1–9 complete), then extended through v0.4.1. This document is
the contract the code was built against; the build followed §14 phase-by-phase, each phase
verified with tests and a live run against a local model. Post-v0.1 releases added an
interactive REPL with a persistent status line, processing spinner, and live approval-mode
and model switching (v0.2, v0.4); memory management via `memory prune`/`forget` plus automatic
log retention (v0.3, v0.4); and first-class OpenAI-compatible cloud providers — OpenRouter,
Groq, and any configured `base_url` endpoint (v0.4).
**Version:** 0.4.1

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
│   ├── cli.py                     # Typer app: repl + `run` one-shot
│   ├── config.py                  # layered config (defaults→file→env→flags), profiles, secrets
│   ├── types.py                   # shared dataclasses/Pydantic: Message, Step, ToolCall, ToolResult
│   │
│   ├── gateway/                   # ── Tier 1 ──
│   │   ├── session.py             #   session lifecycle, identity→role mapping
│   │   └── ingress.py             #   input sanitization, file/MIME validation
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
│   │   └── budget.py              #   token budgeting, sliding window, recursive summarization
│   │
│   ├── tools/                     # ── Tier 4 / Pillar 3 ──
│   │   ├── base.py                #   Tool ABC, JSON-Schema spec, ToolResult
│   │   ├── registry.py            #   registration, schema export, dispatch, per-tool policy
│   │   ├── builtin/
│   │   │   ├── shell.py           #   run_command (sandboxed)
│   │   │   ├── files.py           #   read_file / write_file / edit_file / list_dir (path-jailed)
│   │   │   ├── web.py             #   web_fetch / web_search
│   │   │   └── python_exec.py     #   python interpreter tool (sandboxed)
│   │   ├── mcp_client.py          #   MCP client — mounts external MCP-server tools
│   │   └── sandbox/
│   │       ├── policy.py          #   allow/deny paths, network, env scrub, timeouts, limits
│   │       ├── subprocess_exec.py #   default restricted-subprocess executor
│   │       └── docker_exec.py     #   opt-in Docker container executor
│   │
│   ├── skills/                    # ── Skills (progressive disclosure) ──
│   │   ├── loader.py              #   discover skill folders, parse frontmatter, load on demand
│   │   └── models.py              #   Skill dataclass (name, description, instructions, resources)
│   │
│   ├── memory/                    # ── Pillar 2 ──
│   │   ├── store.py               #   MemoryStore: SQLite schema + sqlite-vec vector index
│   │   ├── working.py             #   working memory (context window) manager
│   │   ├── episodic.py            #   episodic traces — "flight data recorder" of past runs
│   │   ├── semantic.py            #   semantic memory / RAG retrieval
│   │   └── embeddings.py          #   Embedder ABC + sentence-transformers default
│   │
│   ├── guardrails/                # ── Tier 5 / Pillar 4 ──
│   │   ├── ingress.py             #   prompt-injection & PII/jailbreak scan
│   │   ├── egress.py              #   secret/PII leak scan, output schema validation
│   │   └── policy.py              #   operational policy + HITL approval gate
│   │
│   ├── observability/             # ── Tier 5 ──
│   │   ├── tracing.py             #   OpenTelemetry spans (per step / tool / model call)
│   │   └── recorder.py            #   local JSONL trace (append-only audit trail)
│   │
│   ├── agents/                    # ── Multi-agent (MAS) ──
│   │   ├── agent.py               #   Agent = harness instance with a role + toolset
│   │   ├── envelope.py            #   structured agent message envelope
│   │   ├── broker.py              #   in-process async message broker
│   │   └── orchestrator.py        #   sub-agent spawning, topologies, conflict resolution
│   │
│   └── ui/
│       ├── repl.py                #   Rich/prompt_toolkit interactive loop, streaming render
│       └── render.py              #   markdown, tool-call panels, approval prompts, cost meter
│
└── tests/
    ├── unit/                      # prompt templates, schema validators, state transitions
    └── integration/               # simulated-world trajectory tests
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
the antidote to the "naive ReAct infinite loop" failure mode.

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

- **Native tool-calling** (Anthropic, OpenAI) is used when available.
- **Tool-emulation shim** for local models without reliable function calling: the harness
  injects a JSON tool protocol into the prompt and parses/repairs the response
  (Pydantic validation → structured error → self-correction), exactly as the book's
  `SQLQueryProposal` example does.
- **Dynamic routing** (`router.py`): a triage step classifies each turn and routes simple
  work to a cheap/local model and hard work to a frontier model. Configurable policy.

---

## 7. Tool & Execution Tier — three sources, one registry

1. **Built-in tools** — `shell`, `read_file`, `write_file`, `edit_file`, `list_dir`,
   `web_fetch`, `web_search`, `python_exec`.
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

**Sandboxing** (`sandbox/`): every side-effectful tool runs through an executor governed by
a `SandboxPolicy` (path allow/deny + cwd jail, network egress allow/deny, env scrubbing,
CPU/mem/time limits). Default = restricted subprocess; `--sandbox docker` escalates to a
container when Docker is available.

---

## 8. Memory Tier (Pillar 2)

Single embedded store: **SQLite** for relational state + **`sqlite-vec`** for vectors.

| Layer | What | Backing |
|---|---|---|
| **Working** | Current context window; sliding window + recursive summarization | in-memory, budget-managed |
| **Episodic** | Append-only trace of every past step/run ("flight data recorder"); similar-task lookup injects warnings on new tasks | SQLite tables + vec index |
| **Semantic** | User/domain knowledge; RAG retrieval | SQLite + vec index |

Embeddings default to local **sentence-transformers** (`all-MiniLM-L6-v2` / `bge-small`) —
fully offline. `Embedder` is an ABC so provider embeddings can be swapped in later.

---

## 9. Guardrails & Observability (Tier 5 / Pillar 4)

- **Ingress** — prompt-injection heuristics, jailbreak patterns, PII detection on input.
- **Egress** — secret/API-key/PII scanning on output; Pydantic schema validation of any
  structured proposal before it can reach the tool tier.
- **Operational policy** — rate limits, cost caps, step caps (shared with circuit breakers).
- **HITL approvals** — permission modes (`auto` / `ask` / `deny`) per tool category;
  destructive or side-effectful calls surface an approval prompt in the REPL before running.
- **Observability** — OpenTelemetry spans wrap each step, model call, and tool execution;
  a parallel append-only **JSONL flight recorder** gives a local, greppable audit trail even
  with no OTel collector configured.

---

## 10. Multi-agent (MAS)

- **Agent** = a harness instance bound to a role, system prompt, and toolset.
- **Envelope** = structured message (sender, recipient, intent, payload, correlation id) —
  never raw natural language as a wire protocol (the book's "Babel problem").
- **Broker** = in-process async pub/sub for agent-to-agent messaging.
- **Orchestrator** = spawns sub-agents, wires topologies (supervisor / pipeline / blackboard),
  and applies harness-level conflict resolution (state-oscillation detection, gated locks)
  rather than trusting pure LLM debate to converge.

v0.1 ships single-agent-first with the MAS scaffolding present; supervisor topology is the
first wired path.

---

## 11. Configuration

Layered resolution (later overrides earlier): **built-in defaults → `~/.agent86/config.toml`
→ project `./.agent86/config.toml` → env vars → CLI flags**. Secrets (API keys) come from
env or the OS keyring, never written to config files.

```toml
[model]
default   = "anthropic:claude-opus-4-8"
router    = "triage"                 # off | triage
[model.route]
cheap     = "ollama:llama3.1"
frontier  = "anthropic:claude-opus-4-8"

[providers.anthropic]  api_key_env = "ANTHROPIC_API_KEY"
[providers.openai]     api_key_env = "OPENAI_API_KEY"  base_url = "https://api.openai.com/v1"
[providers.ollama]     base_url = "http://localhost:11434"
[providers.llamacpp]   base_url = "http://localhost:8080"

[sandbox]     mode = "subprocess"    # subprocess | docker
[guardrails]  approval = "ask"       # auto | ask | deny  (per-category overrides allowed)
[memory]      path = "~/.agent86/memory.db"  embeddings = "sentence-transformers:all-MiniLM-L6-v2"
[limits]      max_steps = 40  max_cost_usd = 5.0  max_wall_clock_s = 900

[mcp.servers.example]  command = "npx"  args = ["-y", "some-mcp-server"]
```

---

## 12. CLI surface

```
agent86                          # interactive REPL
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

In-REPL: `/help`, `/model`, `/tools`, `/skills`, `/memory`, `/cost`, `/approve`, `/clear`, `/exit`.

---

## 13. Dependencies (planned)

| Purpose | Package |
|---|---|
| CLI framework | `typer` |
| Terminal UI | `rich`, `prompt_toolkit` |
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

## 15. Non-goals for v0.1

- Distributed/networked multi-host agents (in-process MAS only).
- gVisor / WASM sandboxes (subprocess + Docker only; WASM is a later option).
- A hosted service / web UI — this is a local-first CLI.
