# Changelog

All notable changes to agent86 are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.0]: https://github.com/tdfleming/agent86CLI/releases/tag/v0.1.0
