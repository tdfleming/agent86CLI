# Milestones

## v1.0 Interactive to Release (Shipped: 2026-09-21)

**Phases:** 1-9 (v0.6 through v1.0) · **Plans:** 30 across phases 1-4; phases 5-9 ran as
direct execution passes · **Published:** agent86 1.0.0 on PyPI, GitHub Release v1.0.0

**Scope:** 299 commits, 281 files, +60,135/-1,198 lines over 2026-07-19 -> 2026-09-21.
17,055 lines of `src/`, 21,085 lines of `tests/`. 42/42 requirements complete.

**Key accomplishments:**

- **A full-screen Textual TUI as the default interactive surface** — scrollable transcript, live
  status footer that updates mid-turn, `/` command palette, arrow-key pickers, and modal tool
  approvals — with the plain loop and `run --json` preserved untouched as the scripting contract.
- **Configuration from inside the app.** Model providers and MCP servers are added, tested and
  saved without hand-editing TOML or restarting: masked key capture into the OS keyring, a live
  connection test before anything is written, and comment-preserving write-back behind a diff.
- **A harness that keeps its promises.** The advertised cost cap, egress redaction, retry policy
  and sandbox isolation were all partly or wholly unwired; v0.7 made each one real — priced
  models, validated config enums, backoff on transient failures, an SSRF guard on `web_fetch`,
  a cross-platform env allowlist, and MCP subprocesses that no longer inherit API keys.
- **Context and cost under control.** Budgeting against the model's real context window,
  summarizing compaction instead of silent truncation, `max_tokens` continuation, parallel
  read-only tool calls, Anthropic prompt caching billed as cache, and a per-turn cost line.
- **Coding-agent ergonomics.** Markdown transcript with syntax highlighting, collapsible
  tool-call blocks, a multi-line prompt with persistent history, `@file` mentions, named sessions
  with a picker, exact-match `edit_file` whose unified diff is shown *before* approval, and the
  Agent Skills convention with `allowed-tools` enforced per turn.
- **Shipped.** agent86 1.0.0 is on PyPI, published by a tag-driven workflow using trusted
  publishing, alongside trace redaction and rotation and a real OpenTelemetry exporter.
  CI is green on every job: 1,231 tests plus 14 packaging tests against the built wheel.
