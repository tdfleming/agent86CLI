# agent86

**An agentic harness on the command line.** A Python CLI that connects to remote or
local models and lets them use tools and skills — a faithful, runnable implementation of
the five-tier architecture and four pillars from *The Agentic Harness* (Tony Fleming, 2026).

The design contract lives in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Status

**Phase 8 — Multi-agent orchestration.** A single harness can now spawn and coordinate
specialized sub-agents (the book's MAS chapters).

- **Sub-agents** — a `delegate(role, task)` tool lets the main agent act as a *supervisor*,
  spinning up a role-scoped sub-agent that runs its own Reason→Act→Observe loop with the same
  tools, sandbox, and guardrails, and returns its result. Delegation nests up to
  `agents.max_depth` (depth-guarded so it can't recurse without bound).
- **Message envelopes** — agents never exchange raw natural language; every inter-agent
  message is a structured `AgentMessage` (sender, recipient, intent, correlation id) — the
  book's answer to the "Babel problem".
- **Broker + orchestrator** — an in-process `MessageBus` and a `SupervisorOrchestrator` that
  fans role-scoped tasks out to sub-agents and collects correlated reply envelopes.

Everything prior holds: four providers, dynamic routing, tools + skills + MCP, memory,
guardrails, circuit breakers, and observability. Remaining: Docker sandbox + polish (Phase 9).
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Try it (with a running Ollama chat model, or provider API keys set):

```bash
agent86 --model ollama:qwen2.5:3b            # REPL: /help /tools /skills /memory /cost /exit
agent86 --model openai:gpt-4o run "Summarize the harness in one sentence"
agent86 run --yes "Delegate to a 'researcher' sub-agent: find X. Then summarize."
agent86 skills list ; agent86 mcp tools ; agent86 trace show
```

Route cheap vs frontier per turn in `.agent86/config.toml`:

```toml
[model]
router = "triage"
[model.route]
cheap = "ollama:qwen2.5:3b"
frontier = "anthropic:claude-opus-4-8"
```

## Install (development)

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv venv
uv pip install -e ".[dev]"
```

Or with pip:

```bash
python -m venv .venv
# Windows PowerShell:  .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Optional backends are extras — install what you need:

```bash
pip install -e ".[anthropic]"   # Claude
pip install -e ".[openai]"      # OpenAI / OpenAI-compatible
pip install -e ".[local]"       # sentence-transformers + sqlite-vec
pip install -e ".[mcp]"         # MCP client
pip install -e ".[all]"         # everything
```

## Usage

```bash
agent86                     # interactive REPL
agent86 run "your goal"     # one-shot, scriptable
agent86 config path         # show resolved config location
agent86 models              # list configured models
agent86 --help
```

## Design

The core rule (from the book): **the model proposes; the deterministic harness validates,
executes, and persists.** The model never touches the sandbox, the database, or the terminal
directly. Everything crosses the harness.

```
Tier 1  Gateway         gateway/          session, input sanitization
Tier 2  Orchestration   orchestration/    ReAct loop, state machine, routing, circuit breakers
Tier 3  Cognitive       cognitive/        provider adapters, prompt compilation, token budget
Tier 4  Tool & Exec     tools/            built-ins + MCP + sandbox
Tier 5  Guardrails/Obs  guardrails/ + observability/   HITL, OTel, flight recorder
        Memory          memory/           SQLite + sqlite-vec (working/episodic/semantic)
```

## License

MIT
