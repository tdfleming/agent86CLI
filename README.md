# agent86

**An agentic harness on the command line.** A Python CLI that connects to remote or
local models and lets them use tools and skills — a faithful, runnable implementation of
the five-tier architecture and four pillars from *The Agentic Harness* (Tony Fleming, 2026).

The design contract lives in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Status

**Phase 4 — Memory (Pillar 2).** The harness now remembers. A single embedded store
(SQLite + optional `sqlite-vec`) backs three kinds of memory, and sessions persist across
runs.

- **Working memory** — sliding-window token budget trims the context sent each request.
- **Episodic memory** — one record per completed turn (task → outcome); similar past turns
  are recalled and injected as context on a new task (the "flight data recorder").
- **Semantic memory** — durable facts retrieved by meaning, exposed to the agent via the
  `remember` / `recall` tools.
- **Embeddings** — local `sentence-transformers` by default, with a dependency-free hash
  embedder fallback so memory works (and tests run) without the `local` extra.
- **Sessions** — persisted after every turn; resume with `--resume <id>` (REPL) or
  `run --session <id>`. Inspect with `agent86 memory stats|sessions|search`.

Earlier phases still hold: the full Reason→Act→Observe loop, **Anthropic** + **Ollama**
providers, 7 built-in tools, a restricted-subprocess sandbox with secret-scrubbing, and the
`auto`/`ask`/`deny` HITL approval gate. MCP and skills join in Phase 6. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Try it (with a running Ollama chat model, or `ANTHROPIC_API_KEY` set):

```bash
agent86 --model ollama:qwen2.5:3b            # REPL: /help /tools /memory /cost /clear /exit
agent86 --model ollama:qwen2.5:3b run --yes "Remember that my favorite color is teal"
agent86 --model ollama:qwen2.5:3b run --yes "What's my favorite color? Use recall."
agent86 memory stats
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
