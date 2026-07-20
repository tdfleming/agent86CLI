# Changelog

All notable changes to agent86 are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
