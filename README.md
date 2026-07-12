# agent86

**An agentic harness on the command line.** A Python CLI that connects to remote or
local models and lets them use tools and skills — a faithful, runnable implementation of
the five-tier architecture and four pillars from *The Agentic Harness* (Tony Fleming, 2026).

The design contract lives in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Status

**Phase 6 — Skills + MCP.** The registry is now extensible from two more sources.

- **Skills** — a skill is a folder with a `SKILL.md` (frontmatter + instructions). Only
  each skill's name + description sit in context (progressive disclosure); the model calls
  `use_skill(name)` to load the full instructions on demand. Discovered from
  `~/.agent86/skills` and `./.agent86/skills`. Manage with `agent86 skills list|show`.
- **MCP client** — agent86 is an MCP client: for each configured server it spawns the
  process, lists its tools, and mounts each as a first-class tool (same schema, approval
  gating, and tracing as built-ins). `agent86 mcp list|tools`.

All prior tiers hold: Reason→Act→Observe loop, **Anthropic** + **Ollama** providers, built-in
tools, secret-scrubbing sandbox, HITL approvals, working/episodic/semantic memory, ingress/
egress guardrails, circuit breakers, and the flight recorder. Remaining: more providers +
routing (Phase 7), multi-agent (Phase 8), Docker sandbox (Phase 9). See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Try it (with a running Ollama chat model, or `ANTHROPIC_API_KEY` set):

```bash
agent86 --model ollama:qwen2.5:3b            # REPL: /help /tools /skills /memory /cost /exit
agent86 --model ollama:qwen2.5:3b run --yes "Remember that my favorite color is teal"
agent86 skills list                           # discovered skills
agent86 mcp tools                             # tools from configured MCP servers
agent86 trace show                            # the flight recorder
```

Configure an MCP server in `.agent86/config.toml`:

```toml
[mcp.servers.everything]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-everything"]
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
