# agent86 — Coding-Agent UX Milestone (v0.9)

## What This Is

agent86 is a Python agentic harness on the command line: it connects to remote or local
models (Anthropic, OpenAI, OpenRouter, Groq, Ollama, llama.cpp) and lets them use tools,
skills, and MCP servers. v0.6 made the harness **usable** (a full-screen TUI with menus,
in-CLI configuration, a live status line). v0.7 makes it **trustworthy**: the places where the
harness reported or defended *less than it claimed* — a cost meter backed by an empty price
table, a `redact` mode that only warned, a provider failure that vanished mid-turn, tool and
MCP subprocesses inheriting every key on the machine, a `web_fetch` that would happily read
cloud metadata. v0.8 makes it **deliberate about what it spends**: v0.7 taught the harness to
report its context and cost accurately, and the numbers it then reported were bad — a flat 8000-token
conversation budget on a 200k window, the oldest turns silently forgotten, a stable prompt prefix
re-billed every turn, a long answer cut off mid-sentence, and five file reads taken one at a time.
v0.9 makes it usable **for code**: the harness was a good chat client with tools attached — replies
arrived as raw Markdown source, ten tool calls buried the answer, the prompt was a single line with
no memory, a file had to be read through a tool round trip, sessions were opaque 12-character ids,
`edit_file` rewrote a file's line endings and answered "Edited a.py.", an approval showed 300
characters of JSON, and a skill's `allowed-tools` was a comment.

## Core Value

The transcript and the prompt do for a coding session what the TUI already did for a chat session.
A reply renders as Markdown with highlighted code, a tool call is one expandable line, the prompt
is a multi-line composer with history and `@file` mentions, sessions have names and a picker, an
edit is exact-match and shows its diff — at the approval prompt, before it happens — and a skill's
declared tool allowlist is enforced.

Carried from v0.8: the context window and the token budget are spent well, not merely measured
accurately.
Carried from v0.7: what the harness reports is true and what it claims to defend, it defends.
Carried from v0.6: the user can run, configure, and steer the agent entirely from within an
interactive terminal app — switching models, wiring up MCP servers, and watching live progress —
without hand-editing TOML or restarting.

## Requirements

### Validated

<!-- Inferred from existing v0.5.8 code — shipped and relied upon. -->

- ✓ **TUI-01**: Full-screen Textual app is the default interactive UI (transcript + input +
  footer, slash-command parity) — Phase 1
- ✓ **TUI-02**: Status bar stays live during turn processing (model/ctx%/tokens/cost/phase) — Phase 1
- ✓ **TUI-05**: Tool-approval requests use a modal dialog that unblocks the worker thread — Phase 1
- ✓ **TUI-03**: Command palette with autocomplete for slash-commands (declarative `COMMANDS`
  registry + `/`-triggered `OptionList` dropdown) — Phase 2
- ✓ **TUI-04**: Arrow-key selectable menus/modals for interactive choices (`ModePickerModal`
  RadioSet + `ModelPickerModal` OptionList, chained from palette selection) — Phase 2
- ✓ Interactive REPL (rich prompt_toolkit loop + plain fallback) — existing
- ✓ One-shot `run` command with `--json` for scripting — existing
- ✓ Layered TOML config (user → project → env → flags), Pydantic-validated — existing
- ✓ Live model switching via `/model` and `harness.set_model()` — existing
- ✓ MCP servers configurable via TOML (stdio/sse/http transports) — existing
- ✓ Persistent bottom status line at the prompt (model, ctx%, tokens, cost) — existing
- ✓ HITL approval gate with Shift+Tab mode cycle — existing
- ✓ Long-term memory, skills, guardrails, sandbox, flight-recorder trace — existing
- ✓ **MODEL-01**: Add / switch / test model providers and models from within the CLI
  (`/config model` manager, key-entry + connection-test modals, live provider catalogs) — Phase 3
- ✓ **MODEL-02**: Config changes written back to `~/.agent86/config.toml` non-destructively
  (`config_writer.py` on tomlkit, with a save-diff confirmation modal) — Phase 3
- ✓ **SEC-01**: API keys stored in the OS keyring, env vars still take precedence; keys never
  reach the transcript or a traceback (`secrets.py` + `redact()`, fail-soft provider
  construction) — Phase 3
- ✓ **MCP-01**: List / add / remove / enable / disable MCP servers from within the app via
  `/config mcp`, with a pre-save connection test that starts the server for real and enumerates
  its tools; servers mount and unmount live in the running session (no restart) — Phase 4
- ✓ **TUI-06**: Plain loop and `run --json` keep working unchanged; Textual/keyring/tomlkit
  are core-but-lazy (never imported on the `run`/`--plain` path, pinned by
  `tests/tui/test_lazy_import.py`) and their absence degrades to the plain loop / env-var key
  resolution rather than crashing — Phase 5

<!-- v0.7 "Trustworthy harness" — Phase 6. Shipped as v0.7.0 on 2026-09-19. -->

- ✓ **REL-01**: The cost meter is real — a built-in USD price table (Anthropic, OpenAI) plus
  `[pricing.models]` overrides, full-ref → bare-id → dated-snapshot lookup, local providers
  priced at a *correct* zero, unpriced models shown as `cost n/a (unpriced model)` rather than
  `$0.0000`, and `limits.max_cost_usd` consequently able to trip — Phase 6
- ✓ **REL-02**: Config mode fields are validated enums (`model.router`, `sandbox.mode`,
  `guardrails.ingress`, `guardrails.egress`) so a typo fails loudly instead of silently
  disabling a guardrail; the v0.7 shared contract fields land with them
  (`providers.*.max_retries`, `agents.max_steps`, `tools.web_allow_private`,
  `sandbox.env_passthrough`, `limits.tool_timeout_s`) — Phase 6
- ✓ **REL-03**: The loop survives a provider failure — a failed or malformed stream aborts the
  turn (ERROR phase, `turn_end status="error"`, persisted) and surfaces a `ProviderError`
  instead of leaving an unresumable session; transient failures retry first via
  `cognitive/retry.py` (backoff + jitter, `Retry-After`, never after the first streamed delta);
  and `limits.max_steps` is the only step budget — Phase 6
- ✓ **REL-04**: `guardrails.egress = "redact"` redacts what is streamed *and* what is stored,
  and tool-call arguments are scanned (`guardrail stage="egress_tool_args"`) — Phase 6
- ✓ **REL-05**: Sub-agents are bounded and accounted for — `agents.max_steps`, context trimming
  through the parent's working memory, inherited system prompt and skills list, `model_call`
  events, and usage/cost folded into the parent turn and the cost cap — Phase 6
- ✓ **SEC-02**: `web_fetch` cannot be used as an SSRF pivot — scheme restriction, DNS-resolved
  refusal of loopback/private/link-local/reserved addresses (IPv4-mapped, 6to4, Teredo
  unwrapped), manually followed and re-vetted redirects capped at 5 hops, a 2 MB body cap
  before decoding, a content-type check, and the `tools.web_allow_private` escape hatch —
  Phase 6
- ✓ **SEC-03**: The sandbox environment allowlist is cross-platform (POSIX set alongside the
  Windows one, `LC_*`/`XDG_*` families, CA-bundle vars), `sandbox.env_passthrough` extends it by
  name only, credential-looking names are refused even when named, and a timed-out command's
  whole process tree — and its Docker container — is killed — Phase 6
- ✓ **SEC-04**: MCP stdio subprocesses get the scrubbed sandbox environment plus their own
  declared `env`, instead of the full host environment — Phase 6

<!-- v0.8 "Context & cost" — Phase 7. Shipped as v0.8.0 on 2026-09-19. -->

- ✓ **CTX-01**: The conversation is budgeted against the model's **real** context window —
  `capabilities.context_window_for` (a `[model.context_window]` override → the provider where the
  server owns the window → a built-in family table → 8192), minus the system prompt and tool
  schemas, minus `limits.context_reserve_tokens`, minus the output cap; recomputed before every
  request and shared with sub-agents; `limits.max_context_tokens` demoted from *the budget* (a flat
  8000) to an optional hard cap defaulting to `0` = none; `count_tokens` counts tool-call arguments
  and names — Phase 7
- ✓ **CTX-02**: The span that no longer fits is **summarized, not forgotten** —
  `[limits] compaction = "summarize"` writes a GOAL/DECISIONS/FACTS/OPEN digest with the cheap
  route model, merged into the next user message under
  `[Conversation summary — earlier turns compacted]`; tool_call/result pairs are never split, the
  last 6 messages and the current turn are never compacted, the compacted history is persisted for
  resume and the originals archived to episodic memory, and a failure falls back to `drop` rather
  than raising — Phase 7
- ✓ **CTX-03**: A completion that stops for length continues — `stop_reason == "max_tokens"` with
  no tool calls continues up to 3 times per turn, each a full breaker step, stitched into one
  assistant message with a `continuation` event — Phase 7
- ✓ **CTX-04**: A step's read-only tool calls run **in parallel** — approvals resolved
  sequentially first, then reads on a ≤4-worker pool, then side-effecting calls one at a time in
  model order; results observed in call order; `Tool.parallel_safe` opts a tool out (`delegate`
  does); cancellation gives pending calls a `Not executed: cancelled` result;
  `[limits] parallel_tools` — Phase 7
- ✓ **COST-01**: The stable prompt prefix is **cached** — Anthropic `cache_control` breakpoints on
  the last tool and the system block, placed only above that model's minimum cacheable length
  (a per-family table, since the minimum is not monotonic across generations),
  `[providers.<name>] prompt_cache` to disable, and `Usage.cache_read_tokens` /
  `cache_creation_tokens` carrying the breakdown provider-agnostically — Phase 7
- ✓ **COST-02**: Cache traffic is **priced as cache** — reads at 0.1×, 5-minute writes at 1.25×,
  the uncached remainder at the input rate, with per-model overrides and optional explicit
  per-mtok cache rates, so `limits.max_cost_usd` stops being wrong in both directions — Phase 7
- ✓ **COST-03**: Every turn ends with **one line saying what it cost** — `TurnSummary` on
  `state.last_turn` (tokens incl. cache, cost, steps, tool calls, duration, compactions,
  continuations), published at turn start and closed on every exit, rendered identically on the
  TUI, the plain loop and `agent86 run`'s stderr, with an additive `turn` key in `run --json` —
  Phase 7

<!-- v0.9 "Coding-agent UX" — Phase 8. Shipped as v0.9.0 on 2026-09-21. -->

- ✓ **UX-01**: A finished assistant reply renders as **Markdown** — headings, lists, tables, inline
  code and fenced blocks through `Syntax(word_wrap=True)` — re-rendered once on completion rather
  than re-parsed per delta, skipped entirely for a reply with no Markdown structure, never
  markup-parsed (so `[/weird]` can neither raise `MarkupError` nor vanish into a style tag), with
  the prompt echo and harness notices kept plain; `[ui] markdown` is the switch, and the transcript
  becomes an ordered entry list replayed into the `RichLog` rather than an append-only log —
  Phase 8
- ✓ **UX-02**: A tool call is **one collapsible block** — `▸ name(args) → summary` cropped to the
  terminal width, expanded with `Ctrl+O` (last) / `Ctrl+Shift+O` (all) to the full arguments as
  pretty JSON and the full result capped at 200 lines; the data read from the session state through
  `turn_bridge` rather than from the delta lines, which also stopped tool results reading as model
  speech; the block rendered when its result lands, its slot reserved at announce time, an
  unobserved call flushed at turn end — Phase 8
- ✓ **UX-03**: A **multi-line prompt with persistent history** — `PromptInput` keeps the `Input`
  interface while Enter submits, Shift+Enter/Ctrl+J insert newlines, Up/Down walk history from the
  first/last line, Escape clears, and the box grows to 8 rows; `PromptHistory` is stdlib-only and
  follows bash's rules (no blanks, no leading-space lines, no consecutive duplicates, capped at
  `[ui] history_size`, atomic append), degrades to "this session only" on a bad file, and is shared
  with the plain loop through `[ui] history_file` — Phase 8
- ✓ **UX-04**: **`@path` mentions** inline a file into the prompt — `@"path with spaces"` accepted,
  every path resolved through `SandboxPolicy.resolve_within` *before* it is opened, directories
  listed (≤200 names) instead of read, binaries and files over `[tools] mention_max_bytes` refused,
  refusals surfaced to the user *and* carried in the prompt, up to 20 palette completions, and no
  Textual import so `--plain` expands them through the same module — Phase 8
- ✓ **UX-05**: **Sessions have names, a listing and a picker** — titled from the first user message
  (60 chars) once, on the first persist that can name them, asking the store first so compaction
  can't rename a conversation; `SessionInfo`/`recent_sessions()`/`session_title()` keep sqlite
  `Row`s out of the UI; `/sessions` lists with the active one highlighted and `/resume [id]` takes
  the 8-character prefix the listing shows, refusing an ambiguous one; `/resume` with no argument
  raises `SessionPickerModal` and a resumed session rebuilds the transcript — Phase 8
- ✓ **UX-06**: **The approval prompt shows the change** — `Tool.preview(arguments, ctx)` on the
  ABC, called with raw unvalidated arguments and never raising, returning a unified diff for
  `write_file`/`edit_file` (naming the count when `old_string` is missing or ambiguous) and the
  whole command or snippet capped at 60 lines for `run_command`/`python_exec`; `ApprovalPreview` is
  a `str` subclass so the `(tool_name, preview) -> bool` contract is untouched; the TUI renders it
  as scrollable `Syntax` (never markup) with `y`/`n`, and the plain loop asks `y/N` with the same
  detail on a TTY while `run` without `--yes` still declines — Phase 8
- ✓ **TOOL-01**: **`edit_file` is exact-match and answers with a diff** —
  `old_string`/`new_string`/`replace_all` (with the `old`/`new` aliases kept), refusals that name
  the match count and the way out, BOM and CRLF preserved by decoding and re-encoding in the tool
  rather than round-tripping `read_text`/`write_text`, a mixed file left verbatim, a non-UTF-8 file
  refused rather than mangled, a unified diff in the result and in `metadata["diff"]`, and
  `write_file` saying "new file, N lines" when there was nothing to diff — Phase 8
- ✓ **SKILL-01**: **The Agent Skills convention, with `allowed-tools` enforced** — frontmatter
  closed by a `---` on its own line, block scalars/quoted values/inline and block lists, PyYAML
  used when present and a built-in mini parser when not (a skill must never need a dependency),
  space-delimited `allowed-tools`; a five-root search order (project `.agent86/skills` →
  `.claude/skills` → `~/.agent86/skills` → `~/.claude/skills` → `[skills] paths`) with first root
  winning and project roots resolved against an explicit workspace; `skill_roots()` feeding
  `default_policy` so bundled resources are readable; and `ToolRegistry.dispatch` refusing anything
  outside a non-empty allowlist, naming the skill and the list, with `use_skill` always callable
  and `clear_skill()` lifting the restriction at the end of every turn — Phase 8

### Active

<!-- This milestone. Hypotheses until shipped. -->

_None — all 10 v0.6, all 8 v0.7, all 7 v0.8 and all 8 v0.9 requirements validated; v0.9 shipped
as v0.9.0 on 2026-09-21._

### Out of Scope

- Retaining the legacy `rich_loop` long-term — replaced by TUI + plain loop (two loops, not three)
- Storing secrets in plaintext config or a hand-rolled encrypted file — keyring only
- Rewriting the harness / cognitive loop — this milestone is a presentation + config-write layer
- Web or GUI front-ends — terminal only

## Context

- **Codebase**: `src/agent86/` — key modules for this milestone are `cli.py` (Typer surface),
  `ui/repl.py` (the two loops + threaded turn bridge), `ui/status.py` (`StatusState`,
  `format_status_line` — already has an unused `working`/`phase` branch), `config.py` (read-only
  today), `cognitive/base.py` + provider modules (each reads `os.getenv(api_key_env)` directly).
- **The turn bridge already exists**: `_run_turn_rich` runs `harness.run_turn()` (a sync
  generator) in a worker thread, drains a queue, and blocks the worker on a `threading.Event`
  for approvals. The TUI reuses this exact pattern, posting Textual messages instead of printing.
- **Secret seam**: providers call `os.getenv(config.api_key_env)`. A single
  `resolve_api_key(provider, pconf)` helper (env → keyring) is the only change needed to their
  key lookup.
- **Config is read-only**: `config.py` uses `tomllib`. Writing back non-destructively (preserving
  the comments already in user configs) needs `tomlkit`.

## Constraints

- **Performance**: Core deps are deliberately light so `agent86` starts fast. New deps
  (Textual, keyring, tomlkit) MUST be lazy-imported — `run` (one-shot) and `--plain` must not
  import them, and cold-start for scripting must not regress.
- **Compatibility**: The plain loop and `run --json` are the scripting/CI contract and must keep
  working unchanged. keyring absence (headless/CI) must silently fall through to env vars.
- **Tech stack**: Python ≥3.11, Textual (TUI), keyring (secrets), tomlkit (config write-back),
  Rich, Typer, Pydantic v2 (prompt_toolkit was dropped in v0.6.0; the plain loop uses stdlib
  `input()`).
- **Platform**: Primary dev/test on Windows 11 (console quirks already handled via UTF-8
  reconfigure in `cli.py`); must also work on macOS/Linux.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Full-screen **Textual** TUI (vs prompt_toolkit Application or incremental Rich) | Most Claude-Code-like; live footer during processing falls out of the async event loop | ✓ Good (Phase 1) |
| Reuse threaded turn bridge: `run_worker(thread=True)` + `post_message`; Event-based approval (not `push_screen_wait`) | Approval + streaming already solved in `_run_turn_rich`; avoids under-documented async-worker API | ✓ Good (Phase 1) |
| Secrets in **OS keyring** (vs env-only or encrypted file) | Safe default, no hand-rolled crypto, env still wins for CI | ✓ Good (Phase 3) |
| Config writes default to **user** scope (`~/.agent86`), project toggle offered | Applies across projects; repo-specific settings opt-in | ✓ Good (Phase 3) |
| `UNRESOLVED` sentinel for "key not yet looked up" (vs `None`) | `None` conflates "absent" with "unresolved", which silently defeated keyring retest | ✓ Good (Phase 3) |
| Per-family **capabilities seam** gates sampling params, with self-correcting retry | Providers reject params per model family; one declarative table beats scattered conditionals | ✓ Good (Phase 3) |
| Redact-and-sever on provider construction failure (`raise … from None`, no frame locals) | A traceback through key-handling code is a second, independent secret-leak path | ✓ Good (Phase 3) |
| New deps **lazy-imported**; Textual a core-but-lazy dep | Preserve fast cold-start for `run`/`--plain` | — Pending |
| Reuse existing threaded turn bridge; post Textual messages | Approval + streaming already solved; don't re-derive | — Pending |
| Single declarative `COMMANDS` registry backs dispatch, `/help`, and the palette | One source of truth — help and palette can't drift from real commands | ✓ Good (Phase 2) |
| Enter-routing "Approach B": bind/unbind priority `enter` only while palette open (spike-proven) | Permanent priority `enter` swallows `Input.Submitted`; arrow/escape need `SkipAction` fallthrough too | ✓ Good (Phase 2) |
| Picker callbacks synthesize `/mode`/`/model` lines through `handle_command` (not direct state mutation) | Keeps `_dispatch_line` the single execution path for typed + picker input | ✓ Good (Phase 2) |
| Three pricing outcomes (priced / local / **unknown**) instead of collapsing onto `0.0` | A cost meter that shows a paid call as free is worse than one that admits it doesn't know; `n/a` is honest, `$0.0000` is a lie | ✓ Good (Phase 6) |
| Groq and OpenRouter deliberately left unpriced | OpenRouter ids are `vendor/model` with per-route pricing not derivable from the id; unknown beats wrong | ✓ Good (Phase 6) |
| Dated-snapshot prefix matching only, never longest-prefix | A loose rule would price `gpt-5.6-sol` off the `gpt-5` entry | ✓ Good (Phase 6) |
| `StrEnum` for the mode fields, not `(str, Enum)` | Every existing `== "triage"` comparison and f-string rendering keeps working; `model_dump(mode="json")` stays a plain string so the tomlkit round-trip is unaffected | ✓ Good (Phase 6) |
| Never retry once a delta has been streamed | A second attempt would duplicate text the user has already read; surface a `ProviderError` instead | ✓ Good (Phase 6) |
| Anthropic retries via the SDK's own `max_retries`, not a wrapper | Don't stack a retry loop on a client that already retries | ✓ Good (Phase 6) |
| Egress scans tool-call arguments but never rewrites them | The approval gate stops side effects; rewriting would hand the tool something the model never asked for | ✓ Good (Phase 6) |
| Sub-agent usage folds into the parent's **cost**, never `record_step` | A sub-agent is not one of the parent's model calls and must not shrink its step budget | ✓ Good (Phase 6) |
| `env_passthrough` refuses credential-looking names even when explicitly listed | An allowlist entry must not become a way to hand tool subprocesses the key that pays for the model | ✓ Good (Phase 6) |
| `web_fetch` keeps `side_effecting = False`; the SSRF guard is the mitigation | A read is a read; approval-gating every fetch would train users to approve blindly | ✓ Good (Phase 6) |
| The context window is resolved by a **capabilities seam**, not by the provider adapters | One lookup the loop, the budget and the ctx gauge all ask; two tables is how the gauge came to lie | ✓ Good (Phase 7) |
| For Ollama/llama.cpp the **provider** owns the window, not the model name | The server serves `num_ctx` / was launched with `-c`; guessing 131k from `llama3.1` hands the budget a number the server truncates | ✓ Good (Phase 7) |
| `max_context_tokens` demoted to an optional hard cap (`0` = none) rather than removed | An explicitly chosen budget is a legitimate preference; it just must not *be* the default budget | ✓ Good (Phase 7) |
| The summary rides on a **USER** message, not a new `Role` | Nothing for four provider adapters to learn; merged into the next user turn because consecutive user messages are a shape some providers reject | ✓ Good (Phase 7) |
| Compaction **never raises** — it falls back to the old drop | Losing the digest is a degradation; losing the turn is a failure | ✓ Good (Phase 7) |
| Approvals resolved sequentially *before* any parallel dispatch | The gate may prompt a human and must be asked exactly once per call; two prompts racing for one terminal is not untanglable | ✓ Good (Phase 7) |
| Reads in parallel, writes strictly sequential and in model order | Two writes could interleave edits to one file, and a write racing a read hands the model a half-written one; determinism is worth the latency | ✓ Good (Phase 7) |
| Results observed in **call** order regardless of completion order | The `TOOL` messages must line up with the assistant's `tool_calls` for every provider | ✓ Good (Phase 7) |
| Continuation is a **step the circuit breaker counts**, not a retry | A truncated answer that continues 3× really is 4 model calls, and the budget must see them | ✓ Good (Phase 7) |
| Cache-breakpoint eligibility estimated at ~4 chars/token, not via `count_tokens` | A round trip per turn to decide something whose only cost when wrong is an ignored marker | ✓ Good (Phase 7) |
| `Usage.input_tokens` is the whole prompt; cache fields are a breakdown *of* it | Anthropic reports the uncached remainder; left as-is, a well-cached turn would look like it barely used context | ✓ Good (Phase 7) |
| `TurnSummary` lives in `orchestration/state.py`, not `types.py` | It is an orchestration record, not part of the provider-agnostic lingua franca | ✓ Good (Phase 7) |
| `TurnSummary` published at turn **start**, duration stamped at every exit | A UI can watch it fill, and a turn that failed halfway still spent tokens | ✓ Good (Phase 7) |
| The footer sheds whole segments by priority; model/cost/mode/phase are never shed | They say what is running, what it costs, and whether it can act without asking — the quiet omission v0.7 exists to remove | ✓ Good (Phase 7) |
| The transcript keeps an **entry model** beside the `RichLog` rather than migrating to a `VerticalScroll` of widgets | Every surface queries `#transcript` as a `RichLog`; an entry that can change how it renders buys Markdown and collapsing without touching any of them | ✓ Good (Phase 8) |
| Markdown re-rendered **on completion**, never per delta | A half-written fence or table renders as garbage, and re-parsing the document on every delta is the cost the streaming path exists to avoid | ✓ Good (Phase 8) |
| Tool blocks toggle by **keyboard**, not by click | A `RichLog` renders to strips and cannot host interactive children; a click-to-toggle block needs a widget-based transcript (BACKLOG) | ✓ Good (Phase 8) |
| Block contents come from the **session state**, not the delta lines | The loop already appends the assistant message and the tool message; reconstructing them from display text would be lossy by construction | ✓ Good (Phase 8) |
| `PromptInput` keeps the `Input` interface (`.value`, `.clear()`, `Submitted`) | The app swaps a `TextArea` in without reopening turn handling, and one `submit_prompt` path serves any input widget | ✓ Good (Phase 8) |
| One history **file** shared by both surfaces, appended by the plain loop | The prompts you type are one history; the plain loop just can't navigate it, because stdlib `input()` has no line editor | ✓ Good (Phase 8) |
| A mention resolves through the jail **before** the file is opened | A refused path must not be stat'ed or sniffed either — otherwise the refusal still leaks whether it exists | ✓ Good (Phase 8) |
| A mention refusal is carried **in the prompt** as well as shown to the user | Otherwise the model reasons as though the file arrived; a visible refusal the model can't see is worse than no mention | ✓ Good (Phase 8) |
| `ApprovalPreview` is a `str` subclass carrying `detail`/`lexer` | Every caller implements `(tool_name, preview) -> bool`; a richer type would have broken the TUI bridge, the plain loop and every test double at once | ✓ Good (Phase 8) |
| `Tool.preview` takes **raw, unvalidated** arguments and must never raise | The gate runs before validation, and a preview that raises would turn a question into a crash; `build_preview` swallows and logs | ✓ Good (Phase 8) |
| `edit_file` keeps `old`/`new` as aliases for `old_string`/`new_string` | An older transcript replayed against the new tool should degrade to working, not hard-fail | ✓ Good (Phase 8) |
| The edit tool owns decoding and re-encoding, rather than `read_text`/`write_text` | Only the tool knows it must preserve a BOM and CRLF; the convenience API silently rewrites both | ✓ Good (Phase 8) |
| Skill frontmatter parses with PyYAML **when present**, a mini parser when not | A skill must never need a dependency to be discovered; both paths are tested against the same cases | ✓ Good (Phase 8) |
| First skill root wins, project roots before user roots | A project skill shadows a user skill and nothing shadows the project — the only shadowing order that can't surprise | ✓ Good (Phase 8) |
| `allowed-tools` is a property of the **turn**: activating another skill replaces it, `clear_skill()` lifts it | Intersecting allowlists across a turn makes a skill's boundary depend on history; `use_skill` stays callable so a forgetful skill isn't a one-way door | ✓ Good (Phase 8) |

## Next milestone candidates

Every v0.9 candidate shipped. v0.6 made the harness usable, v0.7 made it honest, v0.8 made it
frugal, v0.9 made it a coding agent; **v1.0** is the release milestone:

- **PyPI release workflow** — a tagged release should build and publish via trusted publishing,
  rather than the project being install-from-source only
- **OTel exporter wiring** — spans are emitted but no exporter is configured, so nothing leaves
  the process
- **Trace redaction and rotation** — the flight recorder is append-only, unbounded and unredacted;
  it should scrub secrets on write and roll over by size/age

Smaller things v0.9 opened, all recorded in `docs/BACKLOG.md`: click-to-toggle tool blocks (needs a
widget-based transcript — a `RichLog` can't host children), history *navigation* in the plain loop
(needs `readline`), and a read/write split in the sandbox jail, since a skill root granted for
reading is also writable today.

Deferred further: see `docs/BACKLOG.md` § "Review findings 2026-09-19" (observability, release)
and § "v0.7 review leftovers".

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-09-21 after Phase 8 (Coding-Agent UX) — UX-01…UX-06, TOOL-01 and SKILL-01
validated; the v0.9 Coding-Agent UX milestone is complete (1/1 phase, 8/8 requirements) and
released as v0.9.0. The v0.8 Context & Cost milestone closed at 1/1 phase and 7/7 requirements;
the v0.7 Trustworthy milestone at 1/1 phase and 8/8; the v0.6 Interactive milestone at 5/5 phases
and 10/10.*
