## Project

**agent86 — Interactive Milestone (v0.6)**

agent86 is a Python agentic harness on the command line: it connects to remote or local
models (Anthropic, OpenAI, OpenRouter, Groq, Ollama, llama.cpp) and lets them use tools,
skills, and MCP servers. This milestone makes the interactive experience **Claude-Code-like** —
a full-screen TUI with menus, in-CLI configuration of model connections and MCP servers, and a
status line that stays live while a turn is processing.

**Core Value:** The user can run, configure, and steer the agent entirely from within an interactive terminal
app — switching models, wiring up MCP servers, and watching live progress — without hand-editing
TOML or restarting.

### Constraints

- **Performance**: Core deps are deliberately light so `agent86` starts fast. New deps
  (Textual, keyring, tomlkit) MUST be lazy-imported — `run` (one-shot) and `--plain` must not
  import them, and cold-start for scripting must not regress.
- **Compatibility**: The plain loop and `run --json` are the scripting/CI contract and must keep
  working unchanged. keyring absence (headless/CI) must silently fall through to env vars.
- **Tech stack**: Python ≥3.11, Textual (TUI), keyring (secrets), tomlkit (config write-back),
  prompt_toolkit (retained for plain loop), Rich, Typer, Pydantic v2.
- **Platform**: Primary dev/test on Windows 11 (console quirks already handled via UTF-8
  reconfigure in `cli.py`); must also work on macOS/Linux.

<!-- GSD:stack-start -->
## Technology Stack

| Layer | Choice | Notes |
|---|---|---|
| **Language** | Python ≥3.11 | `src/` layout, `pyproject.toml` |
| **CLI** | Typer + Rich | `cli.py`; REPL + one-shot `run` + inspection cmds |
| **TUI** | Textual | `src/agent86/tui/` — lazy-imported (must not affect `run`/`--plain`) |
| **Validation** | Pydantic v2 | Config, types, tool args |
| **Config** | TOML (tomlkit for comment-preserving write-back) | Layered: defaults → user → project → env → flags |
| **Secrets** | keyring | Graceful fallback to env vars on headless/CI |
| **Testing** | pytest, pytest-asyncio | `tests/unit/`, `tests/integration/`, `tests/tui/` |
| **Lint/Format** | Ruff (line-length 100) | `pyproject.toml` `[tool.ruff]` |
| **Type-check** | mypy | Optional SDKs ignored in CI via overrides |
| **Build** | hatchling | Console entry: `agent86` |

Install for dev: `uv pip install -e ".[dev]"`

<!-- GSD:conventions-start -->
## Conventions

### Code patterns
- **Pydantic models everywhere** — Config, tool args, types. Derive JSON Schema from the model; validate before execution.
- **ABCs for pluggable tiers** — `ModelProvider` (`cognitive/base.py`), `Tool` (`tools/base.py`), `Embedder` (`memory/embeddings.py`) are all abstract base classes with concrete implementations behind them.
- **Shared types in `types.py`** — `Message`, `Step`, `ToolCall`, `ToolResult`, `ToolSpec`, `ModelRef`, `Role`, `AgentPhase`, `ApprovalMode`. These are the lingua franca across tiers. Keep them provider-agnostic.
- **Tool args = Pydantic `Args` model** — each tool binds its own `Args` model to the generic `Tool[TArgs]`. `execute` is type-checked against it. Never let exceptions leak to the loop; always return a structured `ToolResult` error.
- **Lazy imports** — Textual, keyring, tomlkit MUST NOT be imported at module top-level. They live in function bodies so `run` (one-shot) and `--plain` don't pay the cost.
- **Config is read-only in `config.py`** — comment-preserving write-back lives in `config_writer.py`. This separation is intentional.

### Testing
- **Unit tests** in `tests/unit/` — test individual components with mock providers. Use `support.py` helpers (`TextProvider`, `ToolThenTextProvider`) for simulation.
- **Integration tests** in `tests/integration/` — simulated-world trajectory tests (no live network calls).
- **TUI tests** in `tests/tui/` — Textual screen/widget tests using `pytest-asyncio`.
- **Fixtures** — `_no_home_writes` in `conftest.py` prevents flight-recorder writes during tests. Monkeypatch `config_paths` to use `tmp_path`.
- **Test naming** — `test_<module>_<functionality>`, e.g. `test_config_writer.py`, `test_loop.py`.

### Naming
- Packages: `snake_case` (`guardrails`, `cognitive`, `orchestration`)
- Modules: `snake_case` (`loop.py`, `state.py`, `prompt.py`)
- Classes: `PascalCase` (`ModelProvider`, `Tool`, `AgentState`)
- Functions: `snake_case` (`load_config`, `run_repl`)

<!-- GSD:architecture-start -->
## Architecture

The authoritative contract lives in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**. Key facts:

- **Five tiers**: Gateway (Tier 1) → Orchestration/State (Tier 2) → Cognitive (Tier 3) → Tools (Tier 4) → Guardrails/Observability (Tier 5)
- **Four pillars**: Orchestration (Pillar 1), Memory (Pillar 2), Tool Interfaces (Pillar 3), Evaluation/Guardrails (Pillar 4)
- **Core principle**: The model is untrusted — it only *proposes* steps. The deterministic harness validates, executes, and persists.
- **ReAct loop** in `orchestration/loop.py` — perceive → reason → act → observe, with FSM state transitions and error correction at every boundary.
- **Provider ABC** (`cognitive/base.py`) unifies Anthropic, OpenAI-compatible (OpenRouter, Groq, Azure, vLLM), Ollama, and llama.cpp.
- **Tools** bind Pydantic `Args` → JSON Schema → validate → sandbox execute → structured result. Sandbox: subprocess (default) or Docker (opt-in).
- **Memory**: working (context window) + episodic (flight data recorder) + semantic (SQLite + sqlite-vec, sentence-transformers embeddings).

**Package map** (abbreviated):
```
agent86/
├── cli.py              # Typer entry point
├── config.py           # Layered config resolution
├── types.py            # Shared types (Message, ToolCall, etc.)
├── orchestration/      # Tier 2: loop, state FSM, router, circuit breakers
├── cognitive/          # Tier 3: provider adapters, prompt compilation
├── tools/              # Tier 4: built-ins, MCP client, sandbox
├── memory/             # Pillar 2: working, episodic, semantic
├── guardrails/         # Tier 5: ingress/egress/policy
├── skills/             # Progressive skill discovery
└── tui/                # Textual TUI (lazy-imported)
```

### Key files to understand first
| File | Why |
|---|---|
| `src/agent86/types.py` | Shared types across all tiers — read before adding new shared types |
| `src/agent86/config.py` | Layered config resolution — understanding this avoids config bugs |
| `src/agent86/cli.py` | CLI entry point — global options, lazy import boundaries |
| `src/agent86/orchestration/loop.py` | The ReAct execution loop — the heart of the harness |
| `src/agent86/cognitive/base.py` | ModelProvider ABC — adding providers goes here |
| `src/agent86/tools/base.py` | Tool ABC — adding built-in tools goes here |
| `tests/support.py` | Test helpers (`TextProvider`, `ToolThenTextProvider`) |

### Build & test commands
```bash
uv pip install -e ".[dev]"       # or pip install -e ".[dev]"
ruff check .                     # lint
ruff format .                    # format (line-length 100)
mypy src/agent86                 # type-check
pytest                           # run all tests
pytest tests/unit/               # unit tests only
pytest tests/tui/                # TUI tests
pytest tests/integration/        # integration tests
agent86 --model ollama:qwen2.5   # quick interactive REPL
agent86 run "hello"              # one-shot run (scripting/CI contract)
```

### Pitfalls & gotchas
- **Never import Textual/keyring/tomlkit at module top-level.** They MUST be lazy-imported inside functions so `agent86 run` and `--plain` don't pay the import cost. If adding a new dep that's not needed by the one-shot loop, keep it lazy.
- **`types.py` is the lingua franca.** New shared types go here. Keep them provider-agnostic — never leak a provider-specific type into types.py.
- **Tool execution must never raise.** Always wrap in try/except and return a `ToolResult` error the model can self-correct from. An unhandled exception crashes the ReAct loop.
- **Windows console Unicode** — `cli.py` calls `sys.stdout.reconfigure(encoding="utf-8")` on startup. Don't remove this; streaming output on Git Bash/MinTTY depends on it.
- **API keys are never stored in config.** Config only names `api_key_env` (the env var holding the key). The provider reads the key at call time. This is a hard security rule.
- **`config.py` is read-only.** Comment-preserving TOML write-back lives in `config_writer.py`. Never write TOML from `config.py`.
- **`_no_home_writes` fixture** in `conftest.py` blocks flight-recorder writes during tests. Use it when testing code paths that would normally touch `~/.agent86`.

### Adding a new provider
1. Subclass `ModelProvider` in `src/agent86/cognitive/base.py` — implement `stream()`, `models()`
2. Register in `config.py` default providers dict with `api_key_env` and `base_url`
3. Add test in `tests/unit/` using `TextProvider` or a mock HTTP server
4. Add a CLI prefix in `cognitive/catalog.py` if desired (e.g. `openrouter:`)

### Adding a new tool
1. Subclass `Tool[TArgs]` in `src/agent86/tools/` — bind a Pydantic `Args` model to `TArgs`
2. Implement `execute(self, args: TArgs, ctx: ToolContext) -> ToolResult` — wrap in try/except
3. Register via `ToolRegistry` in `tools/registry.py`
4. Add unit test — construct `ToolContext` with `tmp_path`, call `execute`, assert result

<!-- GSD:workflow-start -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.

## SAGE — Persistent Memory

Your brain is powered by SAGE MCP. You have persistent institutional memory.

### Boot Sequence (MANDATORY)
1. Call `sage_inception` as your VERY FIRST action in every new conversation
2. Do NOT respond to the user before booting — your memories must load first
3. Follow the instructions returned by inception (they adapt to the user's settings)

### If SAGE MCP is not connected
Start the node: `sage-gui serve`
MCP config is in `.mcp.json` at project root. Restart your session after starting.
