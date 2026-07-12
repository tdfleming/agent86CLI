# agent86

**An agentic harness on the command line.** A Python CLI that connects to remote or
local models and lets them use tools and skills — a faithful, runnable implementation of
the five-tier architecture and four pillars from *The Agentic Harness* (Tony Fleming, 2026).

The design contract lives in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Status

**Phase 7 — More providers + dynamic routing.** The Cognitive Tier is now complete.

- **OpenAI-compatible provider** — one httpx/SSE adapter for OpenAI, Azure OpenAI, Together,
  Groq, OpenRouter, vLLM — and local servers (llama.cpp, LM Studio, Ollama's `/v1`).
  Streaming tool calls are accumulated across chunks.
- **llama.cpp / LM Studio** — a thin no-key specialization of the OpenAI provider.
- **Dynamic routing (triage)** — with `model.router = "triage"`, each turn is routed to a
  cheap/local model or a frontier model by a fast complexity heuristic; the choice is logged
  to the flight recorder. `off` keeps a single default model.

All four providers now available: **Anthropic**, **OpenAI-compatible**, **Ollama**,
**llama.cpp/LM Studio**. Everything else holds: Reason→Act→Observe loop, built-in tools +
skills + MCP, secret-scrubbing sandbox, HITL approvals, memory, guardrails, circuit breakers,
and observability. Remaining: multi-agent (Phase 8), Docker sandbox (Phase 9). See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Try it (with a running Ollama chat model, or provider API keys set):

```bash
agent86 --model ollama:qwen2.5:3b            # REPL: /help /tools /skills /memory /cost /exit
agent86 --model openai:gpt-4o run "Summarize the harness in one sentence"
agent86 --model llamacpp:my-model run "hi"   # local llama.cpp / LM Studio server
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
