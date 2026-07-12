# agent86

[![CI](https://github.com/tdfleming/agent86CLI/actions/workflows/ci.yml/badge.svg)](https://github.com/tdfleming/agent86CLI/actions/workflows/ci.yml)

**An agentic harness on the command line.** A Python CLI that connects to remote or
local models and lets them use tools and skills — a faithful, runnable implementation of
the five-tier architecture and four pillars from *The Agentic Harness* (Tony Fleming, 2026).

The design contract lives in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Status

**v0.2 — the full harness plus an interactive UX.** A five-tier agentic harness that runs on
remote or local models and uses tools, skills, MCP servers, and sub-agents. Every pillar and
tier from *The Agentic Harness* is implemented, tested (107 tests), and verified live against a
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
| **Interactive REPL** (v0.2) | persistent status line, processing spinner, Shift+Tab approval-mode cycle; plain fallback for any terminal |

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

## Configuring model providers

Models are named `provider:model`. Config lives in `~/.agent86/config.toml` (user) or
`./.agent86/config.toml` (project). **API keys are never stored in config** — each provider
names the *environment variable* that holds its key, and the key is read at call time.

Built-in providers: `anthropic`, `openai`, `openrouter`, `groq`, `ollama`, `llamacpp`.
The last four `openai`/`openrouter`/`groq`/… all speak the OpenAI-compatible API.

**Claude** (first-class, and the default) — just set the key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
agent86 -m anthropic:claude-opus-4-8 run "hello"
```

**OpenRouter / Groq** ship as ready-to-use prefixes — set the key and go:

```bash
export OPENROUTER_API_KEY=sk-or-...
agent86 -m "openrouter:anthropic/claude-3.7-sonnet" run "hello"

export GROQ_API_KEY=gsk-...
agent86 -m "groq:llama-3.3-70b-versatile" run "hello"
```

**Any other OpenAI-compatible endpoint** (Together, Fireworks, Azure OpenAI, vLLM,
LM Studio, …) works by adding a `[providers.<name>]` block with a `base_url`. The name
becomes a first-class prefix; add `api_key_env` if the endpoint needs a key (omit it for a
keyless local server):

```toml
[providers.together]
base_url    = "https://api.together.xyz/v1"
api_key_env = "TOGETHER_API_KEY"

[providers.localvllm]
base_url = "http://localhost:8000/v1"    # keyless local endpoint

[model]
default = "together:meta-llama/Llama-3.3-70B-Instruct-Turbo"
```

```bash
agent86 -m "localvllm:my-model" run "hello"
```

To override an endpoint (e.g. point `openai` at an Azure deployment), set its `base_url`
and `api_key_env` under `[providers.openai]`. Run `agent86 models` to see what's configured.

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
