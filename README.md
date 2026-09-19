# agent86

[![CI](https://github.com/tdfleming/agent86CLI/actions/workflows/ci.yml/badge.svg)](https://github.com/tdfleming/agent86CLI/actions/workflows/ci.yml)

**An agentic harness on the command line.** A Python CLI that connects to remote or
local models and lets them use tools and skills — a faithful, runnable implementation of
the five-tier architecture and four pillars from *The Agentic Harness* (Tony Fleming, 2026).

The design contract lives in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Status

**v0.7.0 — the full harness, a full-screen interactive TUI, cloud providers, remote MCP, and a
cost meter and security posture you can trust.** A five-tier agentic harness that runs on remote
or local models and uses tools, skills, MCP servers, and sub-agents. Every pillar and tier from
*The Agentic Harness* is implemented, tested (670+ tests), and verified live against a local
model.

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
| **Cost & resilience** | real per-model price table + `[pricing.models]` overrides (`limits.max_cost_usd` actually trips), retries with backoff on transient provider failures, sub-agent spend rolled into the session total |
| **Security** | `web_fetch` SSRF guard, cross-platform sandbox env allowlist, MCP stdio env scrubbing, process-tree kill on timeout |

New in v0.7 — the **trustworthy** pass: the cost meter is backed by a real price table (and says
`n/a` rather than `$0.00` when it doesn't know), transient provider failures retry with backoff
instead of killing the turn, `guardrails.egress = "redact"` actually redacts what is streamed and
stored, `[limits] max_steps` is the only step budget, delegated sub-agents trim their context and
bill their spend to the parent turn, and four security holes are closed (see
[Security model](#security-model)). New in v0.6: the full-screen TUI is the default interactive
UI, with in-app model/provider and MCP configuration (keyring-backed keys, live connection tests,
comment-preserving config writes) and cancellable turns. Since v0.2: first-class cloud providers
(OpenRouter/Groq built in, any OpenAI-compatible endpoint via config), live mid-session `/model`
switching, automatic memory retention/pruning, and cleaner `web_fetch` (main-content extraction,
model-friendly sizing).

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
max_retries = 2                          # transient 429/5xx/connection failures (0 = off)

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

## Cost tracking

The status footer and `/cost` report what a session actually spent, and `[limits] max_cost_usd`
is a real circuit breaker that trips on it. Both read `cognitive/pricing.py`, which ships a
built-in price table in **USD per million tokens**:

| Provider | Priced from | Notes |
|---|---|---|
| `anthropic` | the Claude API model/pricing reference | dated snapshots resolve by prefix |
| `openai` | developers.openai.com pricing, fetched 2026-09-19 | `gpt-*`, `o*` families |
| `ollama`, `llamacpp` | — | **free**: they run on your hardware, so `$0.0000` is the truth |
| `groq`, `openrouter` | — | deliberately **unpriced** (see below) |

A lookup tries the full `provider:model` ref, then the bare model id, then a dated-snapshot
prefix — so `anthropic:claude-sonnet-5-20260101` resolves to the `claude-sonnet-5` entry. (Only a
dated suffix is stripped: a loose longest-prefix rule would happily price `gpt-5.6-sol` off the
`gpt-5` row.)

**Unknown is not zero.** Groq's rates change often and OpenRouter ids are `vendor/model` with
per-route pricing that can't be derived from the id, so neither is in the table. A model with no
known rate reads **`cost n/a (unpriced model)`** in the status line rather than `$0.0000` —
showing a free call for a paid one is the one mistake a cost meter must not make. Local models are
a separate, *correct* zero.

Override or add a rate with `[pricing.models]`. Keys are a `provider:model` ref (which wins) or a
bare model id, and overrides beat the built-in table:

```toml
[pricing.models."anthropic:claude-sonnet-5"]
input_per_mtok  = 3.0
output_per_mtok = 15.0

[pricing.models."my-finetune"]          # bare id: matches any provider
input_per_mtok  = 0.5
output_per_mtok = 1.5

[limits]
max_cost_usd = 5.0                      # trips the circuit breaker for real now
```

Delegated work counts too: a sub-agent's usage and cost roll up into the parent turn's totals and
against the same cap.

## Resilience

A transient provider failure no longer ends a turn you've already paid the prompt for.
`cognitive/retry.py` retries **429 / 500 / 502 / 503 / 504** and transport errors (connect
failures, connect timeouts, protocol errors) with exponential backoff plus equal jitter, honouring
`Retry-After` as either delta-seconds or an HTTP-date:

```toml
[providers.anthropic]
max_retries = 2        # per-provider retry budget; 0 disables retrying
```

Two rules keep it honest. **Nothing is retried once the first delta has been streamed** — a second
attempt would duplicate text you've already read, so that failure surfaces as a `ProviderError`
instead. And the Anthropic provider hands `max_retries` to the SDK client rather than wrapping a
client that already retries.

Whatever isn't retryable fails *cleanly*: the turn aborts into the ERROR phase, a
`turn_end status="error"` lands in the flight recorder, the session is persisted and resumable,
and you get a `ProviderError` naming the provider and model — instead of a half-written turn and
a raw decode error.

**Egress redaction is on the output path.** With `[guardrails] egress = "redact"`, the step's text
deltas are buffered and replayed from the *inspected* text, so a leaked secret is never shown,
never stored in the transcript or episodic memory, and never recalled later (a cancelled turn
still gets its buffered partial, redacted). `warn` and `off` stream live as before. In both `warn`
and `redact`, tool-call **arguments** are scanned as well — a model that reads a key from a file
and posts it to a URL never puts it in its prose. Findings are recorded, not blocked: the approval
gate is what stops side effects.

## Security model

The model is untrusted, so the harness — not the model — decides what a tool may reach.

- **Sandbox environment allowlist.** Tool subprocesses get a curated environment, never yours.
  `PATH`, the locale and encoding vars, plus the platform set (Windows: `SYSTEMROOT`, `COMSPEC`,
  `APPDATA`, `TEMP`, …; POSIX: `HOME`, `USER`, `SHELL`, `TMPDIR`, `TERM`, `TZ`, the `LC_*` and
  `XDG_*` families, and the CA-bundle vars so git/pip/npm still work). Everything else — every
  API key on the machine included — is scrubbed.
- **`[sandbox] env_passthrough`** forwards extra variables **by name** when a tool genuinely needs
  one. Values are read from the parent environment at spawn time, so no secret is written to
  config. Credential-looking names (`*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*API_KEY*`, `*_KEY`) are
  refused even when named explicitly, with a logged warning: the allowlist must not become a way
  to hand the model's subprocesses the key that pays for the model.
- **MCP stdio servers get the same scrubbed environment**, plus whatever that server's own `env`
  block asks for. A third-party MCP subprocess no longer inherits the whole host environment; a
  server that needs one token gets exactly that token via `${VAR}`.
- **`web_fetch` SSRF guard.** Every hop is vetted before a connection: `http`/`https` only; all
  A/AAAA answers resolved and refused when loopback, private, link-local, multicast, reserved, or
  unspecified (IPv4-mapped, 6to4, and Teredo forms unwrapped first); redirects followed manually
  with a bound of 5 hops so a public host can't bounce the fetch into your intranet; the body
  streamed and stopped at 2 MB before any decoding; and a textual content type required. Cloud
  metadata (`169.254.169.254`), your local Ollama, and RFC1918 hosts are all off-limits.
- **`[tools] web_allow_private`** is the escape hatch for local development targets — off by
  default, and named in every refusal message.
- **Process-tree kill on timeout.** A timed-out command takes its children with it: each runs in
  its own process group (`CREATE_NEW_PROCESS_GROUP` on Windows, `start_new_session` on POSIX) and
  the whole group is killed (`taskkill /T /F` or `killpg`). Under Docker, each run gets a unique
  `--name` and a timeout follows up with `docker kill`, so the container dies with the client.
  stdin is closed (EOF) rather than inherited, so a command that reads stdin fails fast.
- **API keys are never written to config**, in any flow. Config names only the *env var*
  (`api_key_env`) or holds a `${VAR}` reference resolved at connect time; keys live in the
  environment or the OS keyring, and `config_writer.py` refuses secret-looking leaf keys outright.

```toml
[sandbox]
mode            = "subprocess"          # subprocess | docker  (validated enum)
env_passthrough = ["GIT_SSH_COMMAND"]   # names only; secret-looking names are refused

[tools]
web_allow_private = false               # true lets web_fetch reach localhost/RFC1918

[guardrails]
ingress = "warn"                        # off | warn | block
egress  = "redact"                      # off | warn | redact

[limits]
tool_timeout_s = 60                     # per-tool budget (was derived from max_wall_clock_s)
max_steps      = 40                     # the only step cap — no hidden 12-step ceiling

[agents]
max_steps = 8                           # per-sub-agent cap, clamped by limits.max_steps
```

A typo in any of the enum fields (`egress = "redcat"`) now fails validation with the allowed
values named, rather than silently turning the guardrail off.

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
