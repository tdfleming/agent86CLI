# agent86

**An agentic harness on the command line.** A Python CLI that connects to remote or
local models and lets them use tools and skills — a faithful, runnable implementation of
the five-tier architecture and four pillars from *The Agentic Harness* (Tony Fleming, 2026).

The design contract lives in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Status

**Phase 5 — Guardrails + Observability (completes Tier 5).** The harness now defends and
records itself.

- **Ingress guardrail** — scans user input *and tool output* for prompt-injection / PII;
  `off` / `warn` / `block`. Suspicious tool output is banded as untrusted DATA before the
  model sees it (the real injection vector in an agent).
- **Egress guardrail** — scans model output for leaked secrets (API keys, private keys) and
  PII; `off` / `warn` / `redact`.
- **Circuit breakers** — per-turn bounds on steps, cumulative cost, wall-clock, and
  consecutive tool errors — the antidote to the runaway ReAct loop.
- **Flight recorder** — append-only JSONL trace of every turn / model call / tool call /
  guardrail hit, tagged by session. Read it with `agent86 trace show`.
- **OpenTelemetry** — spans per step / model call / tool when enabled (no-op otherwise).

All prior tiers hold: Reason→Act→Observe loop, **Anthropic** + **Ollama**, 9 built-in tools,
secret-scrubbing subprocess sandbox, HITL approvals, and persistent working/episodic/semantic
memory. MCP and skills join in Phase 6. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Try it (with a running Ollama chat model, or `ANTHROPIC_API_KEY` set):

```bash
agent86 --model ollama:qwen2.5:3b            # REPL: /help /tools /memory /cost /clear /exit
agent86 --model ollama:qwen2.5:3b run --yes "Remember that my favorite color is teal"
agent86 --model ollama:qwen2.5:3b run --yes "What's my favorite color? Use recall."
agent86 memory stats
agent86 trace show                            # the flight recorder
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
