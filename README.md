# agent86

[![CI](https://github.com/tdfleming/agent86CLI/actions/workflows/ci.yml/badge.svg)](https://github.com/tdfleming/agent86CLI/actions/workflows/ci.yml)

**An agentic harness on the command line.** A Python CLI that connects to remote or
local models and lets them use tools and skills — a faithful, runnable implementation of
the five-tier architecture and four pillars from *The Agentic Harness* (Tony Fleming, 2026).

The design contract lives in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Status

**v0.6.0 — the full harness, a full-screen interactive TUI, cloud providers, and remote MCP.** A
five-tier agentic harness that runs on remote or local models and uses tools, skills, MCP servers,
and sub-agents. Every pillar and tier from *The Agentic Harness* is implemented, tested
(532 tests), and verified live against a local model.

| Tier / Pillar | What's there |
|---|---|
| **Tier 1 Gateway** | the CLI/TUI entry point + input sanitization (session lifecycle lives in `orchestration/`) |
| **Tier 2 Orchestration** (Pillar 1) | ReAct loop, FSM state, dynamic routing, circuit breakers |
| **Tier 3 Cognitive** | Anthropic · OpenAI-compatible (incl. built-in OpenRouter & Groq) · Ollama · llama.cpp/LM Studio; prompt compilation; token budgeting |
| **Tier 4 Tools** (Pillar 3) | built-ins (files, shell, python, web) + memory/skill/delegate + MCP (stdio · SSE · streamable HTTP); **subprocess or Docker** sandbox |
| **Tier 5 Guardrails/Obs** (Pillar 4) | ingress/egress scanning, HITL approvals, circuit breakers, flight recorder, OpenTelemetry |
| **Pillar 2 Memory** | working + episodic + semantic (SQLite + sqlite-vec), session persistence, automatic retention/pruning |
| **Multi-agent** | sub-agents via `delegate`, message envelopes, broker, supervisor orchestrator |
| **Interactive TUI** | full-screen Textual app: scrollable transcript, live status footer, slash-command palette, arrow-key pickers, approval modal, in-app `/config model` + `/config mcp`; plain fallback for any terminal |

New in v0.6: the full-screen TUI is the default interactive UI, with in-app model/provider and
MCP configuration (keyring-backed keys, live connection tests, comment-preserving config writes)
and cancellable turns. Since v0.2: first-class cloud providers (OpenRouter/Groq built in, any
OpenAI-compatible endpoint via config), live mid-session `/model` switching, automatic memory
retention/pruning, and cleaner `web_fetch` (main-content extraction, model-friendly sizing).

Optional heavy deps degrade gracefully: no torch → hash-embedder memory; no Docker → subprocess
sandbox; no `mcp` → MCP disabled. Install extras as needed: `pip install -e ".[all]"`.

Try it (with a running Ollama chat model, or provider API keys set):

```bash
agent86 --model ollama:qwen2.5:3b            # interactive TUI: type `/` for the command palette
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

## Interactive TUI

Running `agent86` with no subcommand opens a full-screen [Textual](https://textual.textualize.io)
app: a scrollable transcript, a prompt input, and a footer status bar that stays **live while a
turn runs** — active model, context-fill %, output tokens, session cost, sandbox and approval
mode, and the current phase. Turns execute on a worker thread, so streamed output arrives
incrementally and the UI never freezes. Tool approvals appear as a modal dialog.

Type `/` to open the **command palette** — an autocompleting list of every command with its
description. Commands that need a choice (`/model`, `/mode`) present an arrow-key picker instead
of demanding a typed argument:

```
/help    /config    /config model    /config mcp    /models    /model <provider:model>
/tools   /skills    /memory          /mode [ask|auto|deny]     /cost    /clear    /exit
```

| Key | What it does |
|---|---|
| `Escape` | dismiss the palette; otherwise cancel the running turn |
| `Ctrl+C` | cancel the running turn; quit if none is running (or on a second press) |
| `Ctrl+Q` | quit |
| `Shift+Tab` | cycle the approval mode (`ask` → `auto` → `deny`) live |
| `↑` / `↓` | move through the palette or a picker |

**`/config model`** walks the whole provider setup in-app: a provider manager lists what's
configured, a type-to-filter catalog picker browses the provider's live model list (with a
free-text fallback), the API key is entered **masked** and stored in the **OS keyring**, a live
connection test confirms the endpoint actually answers, and the exact TOML diff is shown for
confirmation before anything is written. Keys are never written to config.

**`/config mcp`** does the same for MCP servers — add, edit, remove, enable/disable across stdio,
SSE, and streamable HTTP. Secret values are held as `${VAR}` references and resolved at connect
time; a pre-save connection test starts the server and enumerates its tools; and after saving,
the server's tools are mounted into the running session **without a restart**.

Both write through a comment-preserving TOML writer, defaulting to user scope
(`~/.agent86/config.toml`) with a project-scope option.

**Plain mode.** `--plain`, `AGENT86_PLAIN=1`, or a non-TTY stdin/stdout runs the dependable
stdlib `input()` loop instead — same slash-commands (they share one registry), no full-screen
app. `run` and `run --json` are unaffected and never import Textual.

```toml
[ui]
tui = true       # false forces the plain loop (pre-v0.6 `status_line` is still accepted)
```

## Configuring model providers

> Everything in this section can also be done from inside the app with **`/config model`** —
> including storing the key in the OS keyring and testing the connection before saving.

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

## Connecting MCP servers

> Everything in this section can also be done from inside the app with **`/config mcp`** —
> with a pre-save connection test and live mounting, no restart.

Each `[mcp.servers.<name>]` block mounts an external [MCP](https://modelcontextprotocol.io)
server's tools as first-class harness tools (same schema, approval gating, and tracing).
Servers are reached over one of three transports:

```toml
# stdio — spawn a local subprocess (transport inferred from `command`)
[mcp.servers.files]
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-filesystem", "."]

# streamable HTTP — connect to a remote URL (the default when `url` is set)
[mcp.servers.remote]
url = "https://mcp.example.com/mcp"
[mcp.servers.remote.headers]      # optional auth / custom headers
Authorization = "Bearer sk-..."

# SSE — the legacy HTTP transport; opt in explicitly
[mcp.servers.legacy]
url       = "https://mcp.example.com/sse"
transport = "sse"
```

Set exactly one of `command` (stdio) or `url` (sse/http); `transport` is inferred but can be
given explicitly (`stdio` | `sse` | `http`). Add `enabled = false` to keep a server configured but
unmounted. Inspect with `agent86 mcp list` and `agent86 mcp tools`. Requires the `mcp` extra
(`pip install -e ".[mcp]"`).

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
agent86                     # interactive TUI (full-screen)
agent86 --plain             # interactive plain loop (also AGENT86_PLAIN=1, or a non-TTY)
agent86 run "your goal"     # one-shot, scriptable
agent86 run "goal" --json   # structured output for automation
agent86 config path         # show resolved config location
agent86 models              # list configured models
agent86 --help
```

## Design

The core rule (from the book): **the model proposes; the deterministic harness validates,
executes, and persists.** The model never touches the sandbox, the database, or the terminal
directly. Everything crosses the harness.

```
Tier 1  Gateway         cli.py + tui/     entry point, input sanitization (guardrails/ingress)
Tier 2  Orchestration   orchestration/    ReAct loop, state machine, routing, circuit breakers
Tier 3  Cognitive       cognitive/        provider adapters, prompt compilation, token budget
Tier 4  Tool & Exec     tools/            built-ins + MCP + sandbox
Tier 5  Guardrails/Obs  guardrails/ + observability/   HITL, OTel, flight recorder
        Memory          memory/           SQLite + sqlite-vec (working/episodic/semantic)
```

Tier 1 is deliberately thin: `gateway/` holds no logic of its own — the entry point and input
sanitization live in `cli.py`/`tui/` and `guardrails/ingress.py`, and session lifecycle is
`orchestration/state.py`.

## License

MIT
