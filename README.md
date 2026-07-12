# agent86

[![CI](https://github.com/tonyfleming/agent86CLI/actions/workflows/ci.yml/badge.svg)](https://github.com/tonyfleming/agent86CLI/actions/workflows/ci.yml)

**An agentic harness on the command line.** A Python CLI that connects to remote or
local models and lets them use tools and skills — a faithful, runnable implementation of
the five-tier architecture and four pillars from *The Agentic Harness* (Tony Fleming, 2026).

The design contract lives in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Status

**Complete — all nine phases (v0.1).** A full five-tier agentic harness that runs on remote
or local models and uses tools, skills, MCP servers, and sub-agents. Every pillar and tier
from *The Agentic Harness* is implemented, tested (93 tests), and verified live against a
local model.

| Tier / Pillar | What's there |
|---|---|
| **Tier 1 Gateway** | session lifecycle, input sanitization |
| **Tier 2 Orchestration** (Pillar 1) | ReAct loop, FSM state, dynamic routing, circuit breakers |
| **Tier 3 Cognitive** | Anthropic · OpenAI-compatible · Ollama · llama.cpp/LM Studio; prompt compilation; token budgeting |
| **Tier 4 Tools** (Pillar 3) | built-ins (files, shell, python, web) + memory/skill/delegate + MCP; **subprocess or Docker** sandbox |
| **Tier 5 Guardrails/Obs** (Pillar 4) | ingress/egress scanning, HITL approvals, circuit breakers, flight recorder, OpenTelemetry |
| **Pillar 2 Memory** | working + episodic + semantic (SQLite + sqlite-vec), session persistence |
| **Multi-agent** | sub-agents via `delegate`, message envelopes, broker, supervisor orchestrator |

Optional heavy deps degrade gracefully: no torch → hash-embedder memory; no Docker → subprocess
sandbox; no `mcp` → MCP disabled. Install extras as needed: `pip install -e ".[all]"`.

Try it (with a running Ollama chat model, or provider API keys set):

```bash
agent86 --model ollama:qwen2.5:3b            # REPL: /help /tools /skills /memory /cost /exit
agent86 --model openai:gpt-4o run "Summarize the harness in one sentence"
agent86 --sandbox docker run --yes "Use python_exec to print the OS you're running on"
agent86 run --yes "Delegate to a 'researcher' sub-agent: find X. Then summarize."
agent86 skills list ; agent86 mcp tools ; agent86 memory stats ; agent86 trace show
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
