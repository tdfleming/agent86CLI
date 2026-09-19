# Changelog

All notable changes to agent86 are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.0] - 2026-09-19

The trustworthy milestone. v0.6 made the harness usable; v0.7 makes what it *reports* and what
it *defends* true. The cost meter is backed by a real price table (so `limits.max_cost_usd` can
actually trip), a provider failure mid-stream degrades instead of vanishing, `redact` really
redacts, `web_fetch` can no longer be pointed at the private network, and tool and MCP
subprocesses get a curated environment rather than every key on the machine. No breaking changes
to the scripting contract: `run`, `run --json`, and `--plain` are unchanged.

### Added

- **A real price table, so the cost cap is real.** `cognitive/pricing.py` shipped with an empty
  `PRICES` dict, which meant `estimate_cost` always returned `0.0` — `limits.max_cost_usd` was
  unreachable dead code and `/cost` and the status footer showed `$0.0000` no matter what a turn
  spent. There is now a built-in table in USD per million tokens covering Anthropic (ids and
  rates from the Claude API reference) and OpenAI (developers.openai.com pricing, fetched
  2026-09-19). Lookup tries the full `provider:model` ref, then the bare model id, then a
  dated-snapshot prefix match, so `claude-sonnet-5-20260101` resolves to `claude-sonnet-5` (the
  prefix rule is restricted to a dated suffix on purpose — a loose longest-prefix match would
  price `gpt-5.6-sol` off the `gpt-5` entry).
- **Three distinct pricing outcomes instead of one lie.** *Priced* (a built-in or configured rate
  exists), *local* (Ollama and llama.cpp really are free — `Price.source == "local"`, `$0.0000`
  is the truth), and *unknown* (`lookup` and `estimate_cost` return `None`, and the status line
  reads **`cost n/a (unpriced model)`** rather than implying a free call). Groq and OpenRouter are
  deliberately left unpriced: OpenRouter ids are `vendor/model` with per-route pricing that
  cannot be derived from the id, and unknown beats wrong.
- **`[pricing.models]` config overrides.** Keys are a `provider:model` ref or a bare model id,
  each with `input_per_mtok` / `output_per_mtok`; overrides win over the built-in table and reach
  it through a `Config` post-validation hook, because providers price usage deep inside a stream
  with no access to the resolved config.

  ```toml
  [pricing.models."anthropic:claude-sonnet-5"]
  input_per_mtok  = 3.0
  output_per_mtok = 15.0
  ```
- **Automatic retries for transient provider failures.** A 429 while a rate-limit bucket refills,
  a 503 from a gateway shedding load, or a connection reset before the first byte used to fail
  the whole turn *after* the prompt had already been paid for. New `cognitive/retry.py` is the
  single place that decides whether a failure is worth another attempt and how long to wait:
  retryable statuses (429/500/502/503/504), transport errors (`ConnectError`, `ConnectTimeout`,
  `RemoteProtocolError`), exponential backoff with equal jitter, and `Retry-After` honoured as
  either delta-seconds or an HTTP-date (both clamped). The budget is
  `[providers.<name>] max_retries` (default `2`; `0` disables). Two invariants: **nothing is
  retried once a delta has been yielded** — a second attempt would duplicate text the user has
  already seen, so it surfaces a `ProviderError` instead — and the Anthropic provider passes
  `max_retries` to the SDK client rather than wrapping a client that already retries. llama.cpp
  inherits the OpenAI path. Retries log to the `agent86.cognitive` logger.
- **Validated enums for the mode fields.** `model.router`, `sandbox.mode`, `guardrails.ingress`,
  and `guardrails.egress` were plain strings, so `egress = "redcat"` validated cleanly and
  silently turned a safety switch off. They are now `StrEnum`s (like `ApprovalMode` already was):
  a typo raises a `ValidationError` naming the allowed values, every existing `== "triage"` /
  `== "docker"` / `== "off"` comparison still works, and `model_dump(mode="json")` still emits
  plain strings so the tomlkit round-trip is unaffected.
- **New config fields**: `[providers.<name>] max_retries` (int, `2`), `[agents] max_steps` (int,
  `8`), `[tools] web_allow_private` (bool, `false`), `[sandbox] env_passthrough` (list, `[]`),
  and `[limits] tool_timeout_s` (int, `60`). `env_passthrough` holds variable *names* only —
  values are read from the parent environment at spawn time, so the "no secrets in config" rule
  still holds.
- **Tool-name collisions are recorded and logged.** A tool whose name was already taken used to
  be dropped by a bare `except ValueError: pass`, so a user whose two MCP servers expose the same
  tool name — or whose server shadows a built-in — just saw a tool that never worked, with
  nothing to explain it. Bulk registration now keeps the first registration, appends the loser to
  `registry.collisions`, and warns through the module logger (naming the 64-character truncation
  when the clash is a truncation artefact). The strict `register()` still raises, so an explicit
  `add_mcp_server` keeps reporting collisions.

### Changed

- **`[limits] max_steps` is now the only step budget.** A hard-coded `_MAX_TURN_STEPS = 12` was
  handed to every turn's circuit breaker, which takes the *minimum* of it and `limits.max_steps`
  — so the configured budget (default 40) never applied, and a user who raised it watched a long
  task die at 12 anyway. The constant is gone. Relatedly, the breaker now reads `max_steps=None`
  as "use `limits.max_steps`" via an explicit `is None` check rather than a falsy test, so an
  explicit `0` trips immediately instead of being silently replaced with the config budget.
- **Sub-agents are accountable.** A delegated turn had a hard-coded 8-step cap, no context
  trimming, and its tokens billed to nobody. Sub-agents now take `[agents] max_steps`, run their
  messages through the parent's working memory (with the system prompt held out of the trim),
  inherit the parent's compiled system prompt and skills list (they were previously offered
  `use_skill` with no skills to call it with), record `model_call` events tagged with role and
  depth, and return their `Usage`. `spawn_subagent` accumulates that usage on the harness and
  `run_turn` folds it into the step and the breaker's cost, so delegated spend shows up in
  `state.usage` and counts against the cost cap. Cost only, not `record_step` — a sub-agent is
  not one of the parent's model calls and must not shrink the parent's step budget. The
  `delegate` tool's `str -> str` contract is unchanged.
- **The per-tool timeout is `[limits] tool_timeout_s`** (default 60) instead of
  `max_wall_clock_s if under 120 else 60`, which silently shortened every tool timeout for
  anyone who lowered their run budget.
- **Read-only MCP tools no longer ask for approval.** A tool whose annotations carry
  `readOnlyHint` is mounted with `side_effecting = False`, so reading through an MCP server stops
  prompting the user to approve a read.
- **MCP failure notes accumulate and the manager restarts.** `start()` used to overwrite its
  notes, reporting only the last failing server; it now reports all of them. `close()` resets the
  started flag and the session/task maps, so a later `start()` actually reconnects instead of
  silently doing nothing.
- **The streamable-HTTP MCP transport builds its client with the SDK's own
  `create_mcp_http_client`**, matching what `mcp>=2` expects rather than casting an httpx client
  at the call site.

### Fixed

- **A failed provider stream can no longer leave a turn dangling.** A `ProviderError` — or a raw
  `httpx.RemoteProtocolError` / `json.JSONDecodeError` from a truncated SSE or NDJSON line —
  escaped `run_turn` *after* the user message had been appended: no abort, no `turn_end` event,
  nothing persisted, so the session was unresumable and the trace showed a turn that started and
  never ended. The model-call stream is now wrapped: any exception aborts the turn (ERROR phase,
  `turn_end status="error"`, persisted) before being re-raised — as the original `ProviderError`
  when the provider produced one, and wrapped in a `ProviderError` naming provider and model
  otherwise. A stream that ends with no final completion takes the same path instead of raising a
  bare `HarnessError`.
- **Malformed provider output is a `ProviderError`, not a stray decode error.** The OpenAI and
  Ollama providers convert `json.JSONDecodeError` and the remaining `httpx.HTTPError` subclasses
  into a `ProviderError` that names the endpoint, the model, and what to do about it.
- **`guardrails.egress = "redact"` actually redacts.** The inspection computed a redacted copy and
  threw it away: the raw text had already been streamed delta by delta, and the raw text was what
  got stored in the assistant message and the episodic outcome — "redact" was, in practice,
  "warn". In redact mode the step's text deltas (and the terminal done delta, whose order
  consumers rely on) are now buffered and replayed from the *inspected* text, so a secret is never
  shown, never persisted, and never recalled later. A cancelled turn still gets its buffered
  partial, redacted. `warn` and `off` keep streaming live and are untouched.
- **Egress scanning now covers tool-call arguments.** In `warn` and `redact`, a model that reads a
  key from a file and posts it to a URL never puts it in its prose — the arguments are scanned and
  recorded as `guardrail stage="egress_tool_args"`. The call is recorded, not blocked: the
  approval gate is what stops side effects, and rewriting arguments would hand the tool something
  the model never asked for.
- **Malformed tool-call JSON says so.** When the OpenAI provider could not parse streamed tool
  arguments it substituted `{}`, so the schema validator answered "field required" — sending the
  model off to invent a missing argument when the real bug was its own truncated JSON. Providers
  now carry the raw argument text through a sentinel key (also for valid JSON that isn't an
  object, e.g. a bare string), and the orchestrator and the sub-agent loop intercept such calls
  before the registry, the approval gate, and any tool, returning *"invalid JSON in tool
  arguments … Call the tool again with its arguments as a single valid JSON object."* Tools never
  see the sentinel. Ollama's unparseable-string branch stops fabricating `{"value": …}` the same
  way.
- **A runtime config change reaches the provider.** `ModelRouter` built one provider per model
  string and cached it forever, so a new API key, a new `base_url`, or a provider re-registered
  from the manager kept hitting the old endpoint with the old key for the rest of the session —
  and the change looked like it had silently done nothing. `invalidate()` now clears the cache
  (keeping the pinned provider, which is the current choice rather than a stale entry) and
  `Harness.set_model` calls it before pinning the new one.
- **The status line prices the right model.** `format_cost` can only distinguish priced,
  free-local, and unpriced from a full `provider:model` ref, but the plain REPL set only the bare
  model id — so `llama3.1` fell through the table as *unknown* and an Ollama user read "cost n/a
  (unpriced model)" where `$0.0000` is the truth. `model_ref` is now set alongside `model` (the
  short display label) in both construction and refresh.
- **MCP 2.0 tool mounting.** `Tool.inputSchema` was renamed `input_schema` in `mcp` 2.0, so the
  old attribute access would have raised `AttributeError` against any real 2.x server — at mount
  time, for every tool. It is now read defensively across both spellings.
- **Two TUI crashes closed with the types that allowed them.** A key entered with no provider row
  in flight raised `AttributeError` (it is now discarded — never tested, never echoed to the
  transcript), and the connection-test and MCP-test dismissal callbacks now accept `None`, so a
  cancel reads as a cancel: no save-diff modal, and the in-memory secret cleared rather than
  stored.

### Security

- **`web_fetch` is guarded against SSRF.** It ran inside the user's trust boundary with no address
  check: a model-chosen URL could read cloud metadata (`169.254.169.254`), the user's own Ollama
  on localhost, or any RFC1918 host — and httpx followed redirects automatically, so a public host
  could bounce the fetch straight into the private network. Every hop is now vetted before a
  connection is made: `http`/`https` schemes only; all A/AAAA answers resolved and refused when
  loopback, private, link-local, multicast, reserved, or unspecified (IPv4-mapped, 6to4, and
  Teredo forms unwrapped first); redirects followed manually with a bound of 5 hops; the body
  streamed and stopped at 2 MB *before* any decoding; and the content type required to be textual.
  Each refusal returns a structured `ToolResult` error naming the reason and the
  `[tools] web_allow_private` escape hatch for local development targets.
- **The sandbox environment allowlist is cross-platform, and opt-in extension can't leak keys.**
  The allowlist was Windows-only, so on macOS/Linux every tool subprocess lost `HOME`, `USER`,
  `LOGNAME`, `SHELL`, `TMPDIR`, `TERM`, the locale and `XDG_*` families, and the CA-bundle
  variables — which breaks git, pip, and npm outright rather than merely constraining them. The
  POSIX set is added alongside the Windows one, with `LC_*` / `XDG_*` prefix families, and
  `[sandbox] env_passthrough` forwards anything else by name. Credential-looking names
  (`*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*API_KEY*`, `*_KEY`) are refused even when explicitly
  named, with a logged warning: an allowlist entry must not become a way to hand tool
  subprocesses the key that pays for the model.
- **MCP stdio servers get the scrubbed environment, not the host's.** A stdio server that declared
  any `env` value received `{**os.environ, **cfg.env}` — the whole host environment, every API key
  on the machine, handed to a third-party subprocess. It now gets the same
  `SandboxPolicy.scrubbed_env()` the tool subprocesses do (platform allowlist plus
  `sandbox.env_passthrough`, credential names refused), with its own `env` layered on top — so a
  server that genuinely needs a token still gets exactly the one it asked for via `${VAR}`, and
  nothing else.
- **A timed-out tool no longer leaves its children running.** A timeout only killed the direct
  child: `npm test`, a shell one-liner, or anything that spawns workers left those workers alive,
  holding ports, burning CPU, and keeping the output pipes open after the harness had moved on.
  Each command now starts in its own process group (`CREATE_NEW_PROCESS_GROUP` on Windows,
  `start_new_session` on POSIX) and the whole group is killed on timeout (`taskkill /T /F` or
  `killpg`), with a bounded drain of the pipes. Docker had the same hole one level up — killing
  the `docker run` client leaves the container running and `--rm` never fires — so each run gets a
  unique `--name agent86-<uuid>` and a timeout follows up with `docker kill`, reporting in stderr
  if that fails. Commands also get a closed stdin (EOF) instead of inheriting the parent's, so a
  command that reads stdin fails fast rather than blocking until the timeout.

## [0.6.0] - 2026-09-19

The interactive milestone. `agent86` with no subcommand is now a full-screen terminal app, and
model providers and MCP servers can be configured from inside it — no hand-edited TOML, no
restart. The scripting contract (`run`, `run --json`, `--plain`) is unchanged.

### Added

- **A full-screen Textual TUI, now the default interactive UI.** Running `agent86` with no
  subcommand opens an app with a scrollable transcript, a prompt input, and a footer status bar
  that stays *live while a turn runs* — active model, context-fill %, output tokens, session
  cost, sandbox/approval mode, and the current phase. Turns still run on a worker thread, so
  streamed output arrives incrementally and the UI never freezes. Tool approvals are a modal
  dialog instead of an inline `y/N`. Textual is lazy-imported, so `run` and `--plain` don't pay
  for it.
- **A slash-command palette with autocomplete.** Typing `/` drops an autocompleting list of every
  command with its description; arrow keys select, Enter runs. Commands that need a choice
  (`/model`, `/mode`) present an arrow-key picker rather than demanding a typed argument. One
  declarative `COMMANDS` registry backs the palette, `/help`, and dispatch, so they can't drift.
- **`/config model` — in-app model and provider configuration.** A provider manager lists what's
  configured, a type-to-filter catalog picker browses a provider's live model list (with a
  free-text fallback), an API key is entered masked, a live connection test confirms the endpoint
  actually answers before anything is saved, and a diff of the exact TOML change is shown for
  confirmation. Writes go through `config_writer.py` (tomlkit), so existing comments and
  formatting survive; user scope (`~/.agent86/config.toml`) is the default with a project-scope
  option. Switching the active model takes effect on the next turn.
- **API keys in the OS keyring (`SEC-01`).** New `secrets.py` resolves a provider key from the
  environment first, then the keyring, so existing env-var setups keep working unchanged and a
  missing/headless keyring backend silently falls through. **Keys are still never written to
  config** — a `config_writer` guard rejects secret-looking leaf keys, Typer's
  `pretty_exceptions_show_locals` is off, and provider construction fails soft with a redacted
  `ProviderError` so a key can't surface in a traceback.
- **`/config mcp` — in-app MCP server configuration.** List, add, edit, remove, and
  enable/disable servers across all three transports (stdio · SSE · streamable HTTP). Values may
  reference secrets as `${VAR}`, resolved at connect time (and prompted for through the same
  masked entry modal, never stored). Before an entry is written, a connection test starts the
  server and enumerates its tools; after saving, the server's tools are mounted **live** into the
  running session — no restart. Remove/disable go through the identical diff-and-confirm gate.
  `[mcp.servers.<name>] enabled` is a new config field, and `agent86 mcp list` shows it.
- **Turn cancellation.** Escape (or Ctrl+C) cancels a running turn and returns to the prompt; a
  second Ctrl+C quits. Shutdown no longer hangs on a modal nobody is left to answer — pending
  approvals are released with a bounded wait.

### Changed

- **The default interactive UI is the TUI.** `--plain`, `AGENT86_PLAIN=1`, or a non-TTY
  stdin/stdout forces the plain `input()` loop, exactly as before.
- **`[ui] tui = true|false` replaces `[ui] status_line`.** The old spelling is still accepted and
  mapped onto `tui`, so pre-v0.6 configs keep working.
- **The plain loop dispatches slash-commands through the shared registry** rather than its own
  hand-parsed chain, so the two surfaces can't drift. Commands that need a modal (`/config
  model`, `/config mcp`) return a plain-mode explanation.
- **The startup banner and launch notes print only in plain mode.** Behind the full-screen app
  they were invisible anyway; the TUI renders the notes into the transcript instead.
- **`mcp` is now a dev dependency**, so CI installs it with `.[dev]` and the live MCP transport
  test (`test_mcp_live.py`) runs in CI instead of skipping. It also means CI's mypy now
  type-checks `tools/mcp_client.py` against the real (py.typed) `mcp` API rather than treating it
  as an ignored missing import.

### Removed

- **The prompt_toolkit rich REPL loop and the threaded spinner.** The TUI replaced both; the
  rich loop had become unreachable. `prompt_toolkit` is no longer a dependency, and
  `ui/spinner.py` is gone — the status footer renders the working state.
- **`[ui] mode_cycle_key`.** The approval-mode cycle is a fixed Shift+Tab binding in the TUI
  (`/mode [ask|auto|deny]` still works on both surfaces).

### Fixed

- **Bracketed text no longer crashes the TUI.** Untrusted text (a user line like
  `see [/path]`, a model response, a tool error, a config value) reached Rich's markup parser
  unescaped and raised `MarkupError`, taking the transcript down. Everything written to the
  transcript — including command renderables — is now escaped at the boundary, with a
  `MarkupError` guard behind it.
- **The harness is built once per process.** `run_tui` now takes the already-constructed `_Repl`
  instead of building a second one, which had been starting every MCP server twice and doubling
  startup cost.
- **Quitting no longer hangs.** An approval waiting on a modal that would never be answered could
  block shutdown indefinitely; the approval wait is now bounded and workers are torn down on
  quit, unmount, and interrupt.
- **A long response no longer pushes the prompt off screen.** The live stream region is capped
  and holds only the tail, so the prompt and the status footer stay visible on short terminals.
- **`/help` printed `/mode` instead of `/mode [ask|auto|deny]`** — the usage string's literal
  brackets were being eaten as console markup.
- **Catalog-picker test flake fixed**, and the `/model` bare-ref fallback is validated against
  the active provider's catalog.

## [0.5.8] - 2026-07-19

### Added

- **Live MCP transport test.** A new `tests/integration/test_mcp_live.py` spins up a real FastMCP
  server in a subprocess and drives `MCPManager` against it end-to-end over both remote
  transports — connect, `list_tools`, and a real `call_tool` round trip — exercising the
  `_streamable_http` / `sse_client` code that mocked unit tests can't reach. The module skips
  when the `mcp` extra isn't installed (e.g. CI's minimal `.[dev]` install), so it runs locally
  and under `.[all]` without adding a subprocess/port dependency to CI.

## [0.5.7] - 2026-07-19

### Changed

- **README status header synced to the current release** and the tagline now notes remote MCP,
  reflecting the SSE/streamable-HTTP transport support. Docs-only; no behavior change.

## [0.5.6] - 2026-07-19

### Added

- **MCP servers over SSE and streamable HTTP, not just stdio.** An `[mcp.servers.<name>]` block
  can now point at a remote `url` (with optional auth `headers`) instead of spawning a local
  `command`. Three transports are supported: `stdio` (subprocess, the default when `command` is
  set), `http` (streamable HTTP, the default when `url` is set), and `sse` (opt in with
  `transport = "sse"`). Exactly one of `command`/`url` is required and the transport is inferred,
  with explicit `transport` and clear validation errors for bad combinations. Remote tools are
  mounted with the same schema, approval gating, and tracing as stdio ones. `agent86 mcp list`
  now shows each server's transport and endpoint. The streamable-HTTP path uses the SDK's current
  `streamable_http_client` (owning its httpx client), avoiding the deprecated all-in-one helper.

## [0.5.5] - 2026-07-19

### Changed

- **README status refreshed to v0.5.** The status block still described v0.2 (107 tests) and
  omitted everything shipped in v0.3–v0.5. It now reads v0.5 (141 tests) and reflects the
  built-in OpenRouter/Groq providers, live mid-session `/model` switching, automatic memory
  retention/pruning, and the cleaner `web_fetch` (main-content extraction, model-friendly
  sizing). Docs-only; no behavior change.

## [0.5.4] - 2026-07-14

### Fixed

- **CI mypy no longer fails on the `anthropic` extra.** CI installs only `.[dev]`, which
  excludes the `anthropic` and `openai` provider extras, so mypy could not resolve
  `import anthropic` and failed with `import-not-found`. The runtime import is already guarded;
  this only affected static analysis in CI's minimal-install environment. The mypy overrides
  already whitelisted every other extras-gated backend — `anthropic` and `openai` were simply
  omitted. Both are now added to `ignore_missing_imports`. No behaviour change.

## [0.5.3] - 2026-07-12

### Fixed

- **Ollama responses no longer get cut off mid-sentence.** The Ollama provider never set a
  context window, so Ollama used its small default (~4k) — a tool observation (e.g. a
  `web_fetch` result) filled it, leaving no room to generate, so long answers were truncated.
  The provider now sends `num_ctx` (default 8192, configurable via `[providers.ollama] num_ctx`)
  so the model has room for both the prompt and its full response.

## [0.5.2] - 2026-07-12

Better `web_fetch` — clean content extraction and model-friendly sizing.

### Fixed

- **`web_fetch` returns clean article text instead of page chrome.** The old HTML→text reducer
  kept navigation menus, sidebars, infobox template JSON, and reference markers, so the first
  ~7 KB the model saw of a Wikipedia page was boilerplate — and the real content got pushed
  past the size cap, producing lopsided answers (e.g. a "bio" summarising a mid-article
  section). `web_fetch` now extracts the main content region and drops boilerplate: it uses
  BeautifulSoup (the new `web` extra) when available, with an improved regex reducer as the
  dependency-free fallback. A page's lead/summary now leads the observation.
- **`web_fetch` output is capped to a model-friendly size** (`[tools] web_max_chars`, default
  8000). A long article previously filled the context with ~25k tokens, so a small model
  fixated on whatever happened to sit at the truncation boundary (e.g. summarising a page's
  tail instead of answering). The lead/main content now dominates. Raise or disable (`0`) the
  cap in config.

## [0.5.1] - 2026-07-12

Semantic-search correctness and test coverage for the thin modules.

### Fixed

- **Semantic search now actually uses sqlite-vec when it's installed.** `search_memories` /
  `search_episodes` always ran the Python brute-force scan even when the `sqlite-vec` extension
  was loaded — so the extension did nothing and the "native `vec_distance_cosine`" docs were
  false. Search now uses sqlite-vec's native cosine distance (computed in C, sorted/limited in
  SQLite) when available, with the Python scan as the dependency-free fallback; both paths
  exclude mismatched-dimension rows. The scaling story is documented honestly (full linear
  scan, personal-scale; no ANN index — `vec0` is the upgrade path if ever needed). `sqlite-vec`
  is now a dev dependency so CI exercises the native path.

### Added

- **Integration tests for the REPL turn loop and the MCP client** — the two least-covered
  modules. The new `test_repl_turns.py` drives `_run_turn_rich` (worker-thread streaming, tool
  turns) and the plain loop end-to-end with fake providers (no TTY/network), locking in the
  v0.4.2/v0.4.3 render fixes; `test_mcp_client.py` covers `MCPTool` (spec/run/error) and the
  MCP degradation paths. `ui/repl.py` coverage 34% → 58%; overall 65% → 68%.

## [0.5.0] - 2026-07-12

Code-quality & type-safety release (from an external code review). No user-facing behavior
changes, but note the `Tool` base-class change below if you subclass it.

### Added

- **Coverage reporting.** `pytest-cov` is now a dev dependency and CI runs with
  `--cov --cov-report=term-missing` (plus `[tool.coverage]` config). Coverage is observable
  (currently ~65%), not yet gated — the report highlights the thin spots (the REPL loop, the
  MCP client, and the sandbox executors) for future test work.

### Fixed

- **Type safety in the REPL.** `_Repl.state` is now typed `AgentState` (it is never `None`
  past construction), clearing 9 mypy `union-attr`/`arg-type` errors in `ui/repl.py`.
- **mypy is now clean (24 → 0 errors), and CI enforces it.** The `Tool` base class is generic
  over its `Args` model (`Tool[TArgs]`), so each tool's `execute` is type-checked against its
  concrete argument type without the Liskov-substitution violations mypy was flagging across
  every built-in tool. The registry accepts `Sequence[Tool]` (fixing the `list[MCPTool]`
  invariance error), `MemoryStore` insert helpers handle `lastrowid`, and optional untyped
  backends are declared in `[tool.mypy]`. CI now runs `mypy src/agent86` alongside ruff.

### Changed

- **`docs/ARCHITECTURE.md` synced to the real source tree.** Corrected stale paths
  (`cognitive/pricing.py` not `budget.py`, `agents/subagent.py` not `agent.py`,
  `ui/status.py`+`spinner.py` not `render.py`), added files that existed but weren't listed
  (`memory/system.py`, `guardrails/scanners.py`, `tools/sandbox/executor.py`, the `memory`/
  `delegate`/`skills_tool` built-ins), and documented the Gateway (Tier 1) as intentionally
  thin — its responsibilities live in `cli.py`, `orchestration/`, and `guardrails/`.
- **`Tool` base class is now generic** (`Tool[TArgs]`). Built-in tools subclass
  `Tool["MyTool.Args"]`; a no-argument tool uses `Tool[EmptyArgs]`. The `Args = EmptyArgs`
  default was removed from the base — external tool subclasses must now declare an `Args`
  model (or bind `EmptyArgs`). Runtime behavior is unchanged for all built-in tools.

## [0.4.4] - 2026-07-12

### Fixed

- **`web_fetch` now works on sites that enforce a User-Agent policy (e.g. Wikipedia).** The old
  generic UA (`agent86/0.1 (+agentic-harness)`) got a blanket **HTTP 403** — and a spoofed
  browser UA is blocked too. `web_fetch` now sends a descriptive UA with a contact URL
  (`agent86/<version> (+https://github.com/tdfleming/agent86CLI)`), which those sites accept.
  Configurable via `[tools] web_user_agent`.

## [0.4.3] - 2026-07-12

### Changed

- The REPL now prints a blank line after each question and after each response (both the rich
  and plain loops), so turns are visually separated instead of running together.

## [0.4.2] - 2026-07-12

REPL polish & reliability release.

### Added

- **Quiet Hugging Face startup.** When the local embedding model is already cached, the harness
  now skips huggingface_hub's network update-check (sets offline mode), which removes the
  "unauthenticated requests to the HF Hub" warning and the model-load progress bar, and speeds
  startup. First-run downloads still work (offline is enabled only once the model is cached).
  Opt out with `[memory] hf_offline = false`.

### Fixed

- **Multi-line responses no longer get overwritten by the spinner.** In the rich REPL the
  processing spinner draws with a carriage return, and it was restarting whenever streamed
  output paused for >0.12s — which happens between tokens on slow local models — so its
  redraw overwrote the partial line of a multi-line response mid-stream. The spinner now
  animates only when the cursor is on a fresh line, and clears exactly the width it drew.
- **A failed tool no longer crashes the turn (and drops the rich UI).** `_summarize` did
  `(error or "").splitlines()[0]`, which raised `IndexError` when a tool failed with no error
  string — e.g. `web_fetch` on a non-2xx response (a site returning HTTP 403 to the bot
  User-Agent). `web_fetch` now sets an error on non-success, `_summarize` is defensive against
  an empty error, and the rich REPL reports an unexpected turn error inline instead of
  collapsing to the plain REPL for the rest of the session.

## [0.4.1] - 2026-07-12

Documentation release.

### Changed

- `docs/ARCHITECTURE.md` version bumped to 0.4.0 and its status line refreshed to reflect the
  v0.2–v0.4 additions (interactive REPL, memory management + retention, cloud providers, live
  model switching).

## [0.4.0] - 2026-07-11

Cloud providers & model switching release.

### Added

- **Automatic log retention.** The harness now auto-prunes the flight-recorder log to
  configurable caps at startup, so episodes and sessions can't grow unbounded. New
  `[memory]` settings: `retention_max_episodes` (default 1000), `retention_max_sessions`
  (default 500), and `retention_max_age_days` (default 0 = off); any cap set to 0 is
  disabled. Curated semantic facts are never auto-pruned. Prunes are logged to the flight
  recorder as a `memory/retention_prune` event.
- **First-class OpenAI-compatible cloud providers.** OpenRouter and Groq are now built-in
  provider prefixes (`openrouter:…`, `groq:…`) — just set their API-key env var. Any other
  OpenAI-compatible endpoint (Together, Fireworks, Azure OpenAI, vLLM, LM Studio, …) becomes
  a first-class prefix by adding a `[providers.<name>]` block with a `base_url`; a block with
  no `api_key_env` is treated as a keyless local endpoint. The provider factory falls back to
  the OpenAI-compatible client for any configured provider with a `base_url`, so multiple
  cloud gateways can be used side by side instead of sharing the single `openai` slot.
- **`/model <provider:model>` REPL command** — switch the active model mid-session without
  losing the conversation; the status line updates immediately. Pins the chosen model
  (overriding triage routing) for the rest of the session. Bare `/model` shows the current
  model; an unknown ref or missing API key is reported and leaves the model unchanged.

## [0.3.0] - 2026-07-11

Memory management release.

### Added

- `agent86 memory prune` — trim the flight-recorder log by age (`--older-than DAYS`) and/or
  count (`--keep-last N`). Episodes and sessions are pruned by default; curated semantic facts
  are left alone unless `--memories` is passed. Supports `--dry-run` and `--yes`.
- `agent86 memory forget <id>` — delete a single semantic fact by id (ids come from
  `memory search`), for surgically removing a bad memory.

## [0.2.2] - 2026-07-11

Memory discipline release.

### Changed

- The `remember` tool description and the system prompt now steer the model to persist only
  durable, user-specific facts (preferences, identity, lasting project constraints) — and to
  avoid remembering computed answers, transient state, or general knowledge. Small local
  models no longer over-eagerly write memories for one-off answers like "what is 2+2?".

## [0.2.1] - 2026-07-11

Embeddings robustness release.

### Fixed

- Semantic memory search skips rows whose stored embedding dimension differs from the current
  embedder, so switching embedders (e.g. hash fallback -> `sentence-transformers`) no longer
  produces meaningless cross-dimension similarity scores against pre-existing rows.
- Use `sentence-transformers`' renamed embedding-dimension method (with a fallback to the old
  name), silencing a `FutureWarning` on newer versions.

## [0.2.0] - 2026-07-11

Interactive UX release.

### Added

- **Rich interactive REPL** (prompt_toolkit): a persistent bottom **status line** (active model,
  context-fill %, output tokens, session cost, sandbox mode, approval mode); a **processing
  spinner** that animates through model latency and tool execution (turns run in a worker thread
  so dead air is never silent); and a **Shift+Tab** hotkey that cycles the approval mode live
  (also `/mode [ask|auto|deny]`). Per-model context windows drive the fill gauge, with
  `[model.context_window]` overrides and a new `[ui]` config section.
- **Automatic plain-REPL fallback** for terminals that can't host the rich UI (piped stdin,
  `--plain`, `AGENT86_PLAIN`, or a console prompt_toolkit can't initialize), so the REPL works
  in every terminal — PowerShell, cmd, Windows Terminal, and Git Bash/MinTTY.

### Fixed

- Interactive REPL reliability: streamed output is written with an explicit flush (empty turns
  show `(no response)`), and status notes are escaped so bracketed text like `agent86[local]`
  renders correctly (previously the install hint dropped `[local]`).
- The memory store opens its SQLite connection with `check_same_thread=False` so a turn can run
  in the rich REPL's worker thread without a `sqlite3.ProgrammingError` (access stays serialized).

## [0.1.0] - 2026-07-11

First release — a complete five-tier agentic harness that runs on remote or local models and
uses tools, skills, MCP servers, and sub-agents. A faithful, runnable implementation of the
architecture in *The Agentic Harness* (Tony Fleming, 2026). All optional heavy dependencies
degrade gracefully, so the harness runs anywhere.

### Added

- **Cognitive tier (Tier 3)** — one `ModelProvider` interface with four backends: Anthropic
  (Claude Messages API, native tool use, streaming), an OpenAI-compatible provider (OpenAI,
  Azure, Together, Groq, OpenRouter, vLLM, and local llama.cpp/LM Studio/Ollama `/v1`),
  Ollama, and llama.cpp/LM Studio. Streaming tool-call fragments are accumulated across
  chunks. Prompt compilation and token budgeting included.
- **Orchestration (Tier 2, Pillar 1)** — the Reason→Act→Observe loop with a finite-state
  machine, circuit breakers (per-turn bounds on steps, cost, wall-clock, and consecutive
  errors), and dynamic model routing (triage: cheap/local vs frontier by a complexity
  heuristic).
- **Tools (Tier 4, Pillar 3)** — a registry with built-in tools (`read_file`, `write_file`,
  `edit_file`, `list_dir`, `run_command`, `python_exec`, `web_fetch`), Pydantic-validated
  arguments, and a layered sandbox: a restricted subprocess by default (workspace path-jail,
  environment scrubbing so secrets never reach tool subprocesses, timeouts, output caps) or
  an opt-in Docker container executor (`--sandbox docker`: `--network none`, memory/CPU/PID
  caps, workspace bind-mount).
- **Guardrails & observability (Tier 5, Pillar 4)** — ingress scanning of user input and tool
  output (prompt injection / PII; suspicious tool output banded as untrusted data), egress
  scanning of model output (secret/PII leaks; redact mode), human-in-the-loop approvals
  (`auto`/`ask`/`deny`), an append-only JSONL flight recorder, and OpenTelemetry spans.
- **Memory (Pillar 2)** — working (sliding-window context trimming), episodic (per-turn
  task→outcome recall), and semantic (RAG via `remember`/`recall` tools) memory backed by
  SQLite + optional `sqlite-vec`; local `sentence-transformers` embeddings with a
  dependency-free hash-embedder fallback. Sessions persist and resume across runs.
- **Skills** — self-contained `SKILL.md` folders with progressive disclosure: only name +
  description are in context until the model calls `use_skill` to load full instructions.
- **MCP client** — spawns configured MCP servers over stdio, lists their tools, and mounts
  each as a first-class tool with the same schema, approval gating, and tracing as built-ins.
- **Multi-agent** — a `delegate(role, task)` tool for supervisor-topology sub-agent spawning
  (depth-guarded), structured `AgentMessage` envelopes, an in-process `MessageBus`, and a
  `SupervisorOrchestrator` for programmatic fan-out.
- **Gateway (Tier 1)** — session lifecycle and input sanitization.
- **CLI** — interactive REPL (`/help`, `/tools`, `/skills`, `/memory`, `/cost`, `/clear`) and
  one-shot `run`, plus `config`, `models`, `skills`, `mcp`, `memory`, and `trace` command
  groups. Layered TOML configuration (defaults → user → project → env → flags). UTF-8 output
  so a Windows console's legacy code page can't drop streamed model output.
- **Packaging & CI** — `uv` + `pyproject.toml` (src layout, `agent86` entry point) with
  optional extras (`anthropic`, `openai`, `local`, `mcp`, `otel`, `docker`, `all`); GitHub
  Actions running ruff and pytest on Ubuntu (3.11/3.12/3.13) and Windows (3.12). 93 tests.

[0.7.0]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.7.0
[0.6.0]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.6.0
[0.5.8]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.5.8
[0.5.7]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.5.7
[0.5.6]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.5.6
[0.5.5]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.5.5
[0.5.4]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.5.4
[0.5.3]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.5.3
[0.5.2]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.5.2
[0.5.1]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.5.1
[0.5.0]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.5.0
[0.4.4]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.4.4
[0.4.3]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.4.3
[0.4.2]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.4.2
[0.4.1]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.4.1
[0.4.0]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.4.0
[0.3.0]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.3.0
[0.2.2]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.2.2
[0.2.1]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.2.1
[0.2.0]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.2.0
[0.1.0]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.1.0
