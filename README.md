# agent86

[![CI](https://github.com/tdfleming/agent86CLI/actions/workflows/ci.yml/badge.svg)](https://github.com/tdfleming/agent86CLI/actions/workflows/ci.yml)

**An agentic harness on the command line.** A Python CLI that connects to remote or
local models and lets them use tools and skills — a faithful, runnable implementation of
the five-tier architecture and four pillars from *The Agentic Harness* (Tony Fleming, 2026).

The design contract lives in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Status

**v0.9.0 — the full harness, a full-screen interactive TUI that works like a coding agent, cloud
providers, remote MCP, a cost meter and security posture you can trust, and a context window spent
deliberately.** A five-tier agentic harness that runs on remote or local models and uses tools,
skills, MCP servers, and sub-agents. Every pillar and tier from *The Agentic Harness* is
implemented, tested (1100 tests), and verified live against a local model.

| Tier / Pillar | What's there |
|---|---|
| **Tier 1 Gateway** | the CLI/TUI entry point + input sanitization (session lifecycle lives in `orchestration/`) |
| **Tier 2 Orchestration** (Pillar 1) | ReAct loop, FSM state, dynamic routing, circuit breakers |
| **Tier 3 Cognitive** | Anthropic · OpenAI-compatible (incl. built-in OpenRouter & Groq) · Ollama · llama.cpp/LM Studio; prompt compilation; token budgeting |
| **Tier 4 Tools** (Pillar 3) | built-ins (`read_file` · `write_file` · **`edit_file`** · `list_dir` · `run_command` · `python_exec` · `web_fetch`) + memory/skill/delegate + MCP (stdio · SSE · streamable HTTP); **subprocess or Docker** sandbox |
| **Tier 5 Guardrails/Obs** (Pillar 4) | ingress/egress scanning, HITL approvals, circuit breakers, flight recorder, OpenTelemetry |
| **Pillar 2 Memory** | working + episodic + semantic (SQLite + sqlite-vec), session persistence, automatic retention/pruning |
| **Multi-agent** | sub-agents via `delegate`, message envelopes, broker, supervisor orchestrator |
| **Interactive TUI** | full-screen Textual app: Markdown transcript, collapsible tool-call blocks, multi-line prompt with persistent history and `@file` mentions, session picker, live status footer, slash-command palette, arrow-key pickers, diff-showing approval modal, in-app `/config model` + `/config mcp`; plain fallback for any terminal |
| **Skills** (Pillar 3) | the Agent Skills convention — `SKILL.md` frontmatter, progressive disclosure, a five-root search order, and `allowed-tools` enforced as a gate for the turn |
| **Context & cost** | the conversation budgeted against the model's **real** context window, summarizing compaction of the oldest span, `max_tokens` continuation, parallel read-only tool calls, Anthropic prompt caching, cache-aware pricing, and a per-turn cost line |
| **Cost & resilience** | real per-model price table + `[pricing.models]` overrides (`limits.max_cost_usd` actually trips), retries with backoff on transient provider failures, sub-agent spend rolled into the session total |
| **Security** | `web_fetch` SSRF guard, cross-platform sandbox env allowlist, MCP stdio env scrubbing, process-tree kill on timeout |

New in v0.9 — the **coding-agent UX** pass: a finished reply renders as Markdown with
syntax-highlighted code, each tool call folds into one expandable line, the prompt is a multi-line
composer with persistent history and `@file` mentions, sessions have names and a picker,
`edit_file` does exact-match edits and answers with a unified diff, the approval prompt shows the
*change* rather than 300 characters of JSON, and a skill's `allowed-tools` is a real gate (see
[Interactive TUI](#interactive-tui) and [Skills](#skills)).
New in v0.8 — the **context & cost** pass: the conversation is budgeted against the model's real
context window instead of a flat 8000 tokens, the span that no longer fits is *summarized* rather
than forgotten, an answer truncated at the output cap continues instead of stopping mid-sentence,
a step's read-only tool calls run concurrently, the Anthropic prompt cache is used and priced, and
every turn ends with one line saying what it cost (see [Context management](#context-management)).
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
app: a Markdown transcript, a multi-line prompt, and a footer status bar that stays **live while a
turn runs** — active model, a context gauge measured against the window the harness actually
budgets against, `tok <in>/<out>` (plus `(1.9k cached)` once a session has prompt-cache traffic),
session cost, sandbox and approval mode, and the current phase. Turns execute on a worker thread,
so streamed output arrives incrementally and the UI never freezes. Tool approvals appear as a
modal dialog, and each finished turn ends with a dim per-turn read-out (see
[Cost tracking](#cost-tracking)).

**The footer stays one row.** Rather than wrapping on a narrow terminal, it fits itself to the
available width and sheds whole segments in a fixed order: the `[Shift+Tab]` hint first (it is in
`/help` too), then the token counts (one `/cost` away), then the context gauge. The model name,
the cost, the approval mode, and the working/phase indicator are **never** shed — they say what is
running, what it costs, and whether it can act without asking. Widening the terminal brings the
shed segments straight back.

Type `/` to open the **command palette** — an autocompleting list of every command with its
description. Commands that need a choice (`/model`, `/mode`) present an arrow-key picker instead
of demanding a typed argument:

```
/help    /config    /config model    /config mcp    /models    /model <provider:model>
/tools   /skills    /memory          /mode [ask|auto|deny]     /cost    /clear    /exit
/sessions          /resume [id]
```

| Key | What it does |
|---|---|
| `Enter` | submit the prompt |
| `Shift+Enter` / `Ctrl+J` | insert a newline instead of submitting |
| `↑` / `↓` | walk the prompt history (from the first/last line); move through the palette or a picker |
| `Escape` | clear the draft; dismiss the palette; otherwise cancel the running turn |
| `Ctrl+O` | expand/collapse the **last** tool-call block |
| `Ctrl+Shift+O` | expand/collapse **every** tool-call block |
| `Ctrl+C` | cancel the running turn; quit if none is running (or on a second press) |
| `Ctrl+Q` | quit |
| `Shift+Tab` | cycle the approval mode (`ask` → `auto` → `deny`) live |

### The transcript

A finished reply is re-rendered as **Markdown** — headings, lists, tables, inline code, and fenced
blocks with syntax highlighting — rather than arriving as its own source. It *streams* as plain
escaped text (a half-written fence or table renders as garbage, and re-parsing the document on
every delta is exactly the cost this avoids) and is re-parsed once when the reply completes. A
reply with no Markdown structure is left alone, so a short answer pays nothing. `[ui] markdown =
false` turns it off.

A tool call is **one collapsible block** rather than two flat lines with the interesting part
truncated away:

```
▸ read_file({"path": "src/agent86/tui/app.py"}) → 1284 lines
```

`Ctrl+O` expands the last block, `Ctrl+Shift+O` expands them all, to the full arguments as pretty
JSON and the full result text (capped at 200 lines with a truncated tail). The data comes from the
session state, not from the display lines, so nothing you might want was thrown away on the way in.
Toggling is keyboard-driven rather than click-driven — see the note in `docs/BACKLOG.md`.

A turn that fails names the exception **type**, keeps its message, and tells you where the rest is:

```
error: ProviderError: stream ended without a stop reason
  see agent86 trace show -s 0f3a91c2
```

### The prompt

The prompt is a multi-line composer. **Enter** submits; **Shift+Enter** and **Ctrl+J** add a
newline; the box grows to 8 rows before it scrolls; **Escape** clears the draft. **Up**/**Down**
walk a **persistent history** — kept in `[ui] history_file`, capped at `[ui] history_size`, and
shared with the plain loop, which appends to the same file. History follows bash's rules: blanks,
consecutive duplicates, and any line typed with a **leading space** are not recorded. A missing or
unwritable history file degrades to "this session only" rather than refusing to start.

**`@file` mentions** put a file in front of the model without spending a tool round trip on it:

```
what does @src/agent86/tui/app.py do with @"docs/ARCHITECTURE.md"?
```

Each path is resolved **inside the workspace jail** before anything is opened — a path outside it
is refused and never read, not even stat'ed — then inlined as a fenced block appended to the
prompt. A directory is listed (up to 200 names) instead of read; binaries are refused; a file over
`[tools] mention_max_bytes` is refused with a note telling the model to read it with a tool
instead. Refusals are shown to you *and* carried in the prompt, so neither side assumes a file
arrived when it didn't. The palette completes `@` paths as you type (directories first,
`.git`/`.venv`/`node_modules`/`__pycache__` skipped). Mentions work in `--plain` too.

### Sessions

Sessions are named after the first thing you said to them (truncated to 60 characters), so the
history is readable rather than a wall of 12-character ids:

```
/sessions          # recent sessions, the active one highlighted
/resume 0f3a91c2   # by id, or the 8-character prefix the listing shows
/resume            # arrow-key picker with a type-to-filter box
```

An ambiguous prefix is refused rather than guessed at. Resuming rebuilds the transcript from the
session's messages — prompts plain, replies through the Markdown path, and every tool call a
collapsed block with its arguments and result attached.

### Approving a change

In `ask` mode a side-effecting tool raises a modal showing **what the call does**, not just its
name and 300 characters of JSON. `write_file` and `edit_file` render a unified diff against the
file on disk (syntax-highlighted, scrollable, and never parsed as console markup — a diff is full
of `[`); `run_command` and `python_exec` show the whole command or snippet, capped at 60 lines
rather than truncated mid-token. `y`/`n` answer it, as does `Escape`.

The plain loop asks the same question at the terminal with the same diff when stdin is a TTY:

```
edit_file wants to run:
--- src/agent86/config.py
+++ src/agent86/config.py
@@ -156,6 +156,7 @@
     web_allow_private: bool = False
+    mention_max_bytes: int = 200_000
Approve? [y/N]
```

`agent86 run` without `--yes` is non-interactive and still declines, unchanged.

### Configuring from inside the app

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

### Plain mode

`--plain`, `AGENT86_PLAIN=1`, or a non-TTY stdin/stdout runs the dependable stdlib `input()` loop
instead — same slash-commands (they share one registry), no full-screen app. It shares the TUI's
prompt history file, expands `@path` mentions through the same module, and asks for approval with
the same diff; what it doesn't have is a line editor, so history is append-only there (see
`docs/BACKLOG.md`). `run` and `run --json` are unaffected and never import Textual.

```toml
[ui]
tui          = true                  # false forces the plain loop (pre-v0.6 `status_line` works too)
markdown     = true                  # re-render a finished reply as Markdown in the transcript
history_file = "~/.agent86/history"  # shared by the TUI and the plain loop
history_size = 1000                  # entries kept; the oldest are dropped past the cap

[tools]
mention_max_bytes = 200_000          # largest file an `@path` mention may inline
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

## Skills

A skill is a folder with a `SKILL.md` in it: YAML frontmatter the harness reads, and a body of
instructions the model loads **on demand**. Only each skill's `name` and `description` sit in the
system prompt; the full instructions arrive when the model calls `use_skill`, so a dozen skills
cost a dozen lines of context rather than a dozen documents.

```
.agent86/skills/release-notes/
├── SKILL.md          # frontmatter + instructions
└── reference.md      # resources the skill may point at
```

```markdown
---
name: release-notes
description: >
  Draft the CHANGELOG entry for a release from the commit range,
  grouped Added / Changed / Fixed.
allowed-tools: run_command read_file edit_file
---

1. `git log --stat <base>..HEAD` for the range.
2. Group by workstream, not by commit order.
...
```

Frontmatter follows the **Agent Skills convention**: the closing delimiter is a `---` on its own
line (so a horizontal rule in the body no longer truncates the skill), block scalars (`>` folded,
`|` literal), quoted values, and inline or block lists all parse. PyYAML is used when it happens to
be installed and a built-in mini parser covers the same ground when it is not — a skill must never
need a dependency. `license` and `metadata` are carried through.

**Search order** — first root wins, so a project skill shadows a user skill and nothing shadows the
project:

| # | Root | Scope |
|---|---|---|
| 1 | `./.agent86/skills` | project |
| 2 | `./.claude/skills` | project |
| 3 | `~/.agent86/skills` | user |
| 4 | `~/.claude/skills` | user |
| 5 | `[skills] paths` | extra directories from config |

Project roots resolve against the workspace, not the process CWD. Every existing root is also
granted to the sandbox policy, so a skill's bundled resources — which for a user skill live outside
the workspace — are readable instead of a jail error on the first "see `reference.md`".

**`allowed-tools` is a gate, not a comment.** While a skill is active, `ToolRegistry.dispatch`
refuses any tool outside a non-empty `allowed-tools`, naming the skill and the list so the model
can re-plan rather than retry. The list is **space-delimited** per the convention (commas,
brackets, and YAML lists are tolerated). `use_skill` itself is always callable — a skill that
forgot to list it would be a one-way door — activating another skill replaces the restriction, and
the restriction is lifted at the end of every turn. The system prompt names each skill's
`allowed-tools`, so the model knows the boundary before a refusal costs it a step.

```toml
[skills]
enabled = true
paths   = ["/opt/shared-skills"]   # searched after the four conventional roots
```

Inspect what's discovered with `agent86 skills list` / `agent86 skills show <name>`, or `/skills`
in the app.

## Context management

Before v0.8 the conversation was trimmed to a flat `8000` tokens no matter which model was
answering — which threw away ~96% of a 200k Claude window you are paying for, and *overspent* a 4k
local model into a context-length error. The budget is now derived from the model's real window,
and the span that no longer fits is summarized instead of forgotten.

**The window.** Resolved in priority order, by `cognitive/capabilities.py`:

| Source | What it gives | Notes |
|---|---|---|
| `[model.context_window]` | your explicit override | looked up by full `provider:model` ref, then bare model id |
| the **provider**, where the server owns the window | `ollama` → `[providers.ollama] num_ctx`; `llamacpp` → 8192 | llama.cpp's `-c` isn't discoverable over the API, so guessing 128k from `llama3.1` would hand the budget a number the server truncates |
| the built-in family table | Claude 4.x/5.x **200k**; `gpt-5` 400k, `gpt-4.1` 1,047,576, `gpt-4o` 128k, o-series 200k; common open-weights ids (llama-3.x 131,072, qwen/mixtral/mistral 32,768, gemma 8,192, phi 16,384) | matched as a substring of the model id |
| the default | **8192** | the smallest window any modern model ships with |

**The budget.** Every request is measured against *the window, minus what is already in the
request before any history*: the compiled system prompt and the tool schemas, minus
`limits.context_reserve_tokens` of headroom (slack for the provider's token counting differing
from ours — an error the model call otherwise pays for with a hard 400), minus the output cap the
call will ask for. The reserve is clamped to half the window so a small local model isn't starved,
and `limits.max_context_tokens` is an optional **hard cap** applied last, for anyone who wants to
spend less than the window allows. It is recomputed before every request — skills, MCP servers and
the episodic recall note all change the overhead mid-session — and shared with sub-agents so they
trim to the same number.

**Compaction.** When the conversation outgrows the budget, `[limits] compaction` decides what
happens to the oldest turns:

| Mode | Behaviour |
|---|---|
| `"summarize"` *(default)* | the oldest prefix is replaced by a model-written digest — GOAL / DECISIONS / FACTS / OPEN, instructed to reproduce paths, identifiers and numbers verbatim — written by the cheap route model when routing is on, else the current provider. It rides on a user message headed `[Conversation summary — earlier turns compacted]`. |
| `"drop"` | the pre-v0.8 sliding window: the oldest messages are discarded. |

An assistant message that requested tools is never separated from its tool results, the last 6
messages and the whole current turn are never compacted, and compaction **never raises** — a
failed or empty summary falls back to dropping and records `compaction status="failed"` in the
trace. The compacted history is persisted immediately so a resumed session sees it, and the
originals are archived verbatim to episodic memory (held out of `recall`, so a later turn is never
handed a raw transcript). You see it happen: `[compacted N messages into a summary]` or
`[compaction failed; dropped N messages]` appears dim in the transcript.

**Continuation.** A completion that stops because it hit the output cap (`stop_reason` is
`max_tokens`) with no tool calls used to just end mid-sentence, with the turn reported as done.
The harness now asks the model to continue where it left off — up to **3** times per turn, each
one a full step the circuit breaker counts and budgets, shown as `[continuation k/3]` — and
stitches the pieces into one assistant message, so neither the partials nor the harness's own
prompts survive into the history.

**Parallel tool calls.** A model that asks for five files in one step no longer waits for five
sequential round-trips. Approvals for the whole step are resolved first (sequentially — the gate
may prompt you, and must ask exactly once per call), then read-only calls run together on a
4-worker pool, then side-effecting calls run one at a time in the order the model asked for them:
two writes racing could interleave edits to one file, and a write racing a read could hand the
model a half-written one. Results are observed in **call** order regardless of completion order.
`[limits] parallel_tools = false` restores strictly sequential execution.

```toml
[limits]
max_context_tokens    = 0           # optional HARD cap; 0 = none (was a flat 8000 budget)
max_output_tokens     = 8192        # tokens the model may generate when no provider cap is set
context_reserve_tokens = 4096       # headroom kept free inside the window
compaction            = "summarize" # summarize | drop
parallel_tools        = true        # run a step's read-only tool calls concurrently

[model.context_window]
"ollama:qwen2.5:3b" = 16384         # override the resolved window for one model

[providers.anthropic]
max_tokens = 8192                   # per-provider output cap (None = the provider's own default)
```

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

### Prompt caching

Every turn used to re-send the whole system prompt and tool list at full input price, though
neither changes across a session. The Anthropic adapter now marks the stable prefix as cacheable:
caching is a prefix match over tools → system → messages, so one breakpoint on the **last tool**
caches the tool list and one on the **system block** caches tools + system — both stable while the
conversation after them is not. A marker is placed only when the prefix it closes clears that
model's minimum cacheable length (512 tokens on the newest models, 4096 on Opus 4.6/4.5 and
Haiku 4.5 — the minimum is not monotonic across generations), because below it the API silently
ignores the marker and the breakpoint is spent for nothing. At most two of the four available
breakpoints are used.

```toml
[providers.anthropic]
prompt_cache = true     # false for an endpoint that proxies Anthropic and rejects cache_control
```

Caching is billed at its own rates, so the meter tells the truth about it: **cache reads at 0.1×**
the input rate, **5-minute cache writes at 1.25×**, and the uncached remainder at the input rate
(with a per-model override where a model prices reads differently, and optional explicit
`cache_read_per_mtok` / `cache_write_per_mtok` in a `[pricing.models]` entry). Billing every
prompt token at the input rate made `limits.max_cost_usd` wrong in both directions: a fully-cached
turn is a tenth of the price, a cache write a 25% premium. OpenAI's `cached_tokens` is read the
same way.

`/cost` reports the session's cache traffic — `cache read N  written N tok`, plus `saved $X` where
it can be computed — alongside the usual totals.

### The per-turn line

The session total has been climbing all afternoon; the number you actually watch while deciding
whether to hit `Escape` is *this* turn's. Every finished turn now ends with one dim read-out:

```
— 3 steps · 2 tools · 4.1k in / 612 out (1.9k cached) · $0.0123 · 8.2s
```

It appears on the TUI transcript, in the plain loop, and on `agent86 run`'s stderr (non-JSON), all
through one formatter so they cannot drift. An unpriced model reads `cost n/a (unpriced model)`
rather than a fabricated `$0.0000`, and the cached parenthetical is dropped when nothing was
cached. It is written on the error path too — a turn that failed halfway still spent tokens.

`run --json` carries the same summary under an additive **`turn`** key; every pre-existing key is
untouched, so the scripting contract holds.

```bash
agent86 run --json "hello" | jq '.turn'
```

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
