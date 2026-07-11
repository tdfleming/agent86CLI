# agent86

**An agentic harness on the command line.** A Python CLI that connects to remote or
local models and lets them use tools and skills — a faithful, runnable implementation of
the five-tier architecture and four pillars from *The Agentic Harness* (Tony Fleming, 2026).

The design contract lives in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Status

**Phase 2 — Cognitive tier + minimal loop.** The harness now talks to a live model. The
`ModelProvider` interface is implemented by **Anthropic** (Claude Messages API, native tool
use, streaming) and **Ollama** (local, via `/api/chat`); one-turn Reason→Act→Observe drives
the REPL and one-shot `run`, streaming tokens with a session cost meter. Tool execution is
the Phase 3 branch already structured into the loop. See the build phases in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Try it (with a running Ollama chat model, or `ANTHROPIC_API_KEY` set):

```bash
agent86 --model ollama:llama3.1              # then chat; /help, /cost, /clear, /exit
agent86 --model ollama:llama3.1 run "Say hi in three words"
ANTHROPIC_API_KEY=... agent86 run "Explain the harness in one sentence"
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
