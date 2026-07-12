# agent86 v0.2 — Interactive UX

**Status: shipped in v0.2.0.** All three features and the plain-REPL fallback are implemented,
tested, and verified live. This document is kept as the design record.

Goal: make the REPL feel alive — never dead air, permission control at your fingertips, and a
persistent readout of what's going on. Three features, one UI foundation.

**Decisions (locked):**
- **UI layer:** `prompt_toolkit`, integrated correctly this time — a live `Application` with a
  `bottom_toolbar`, `key_bindings`, and `patch_stdout` so streamed output renders *above* the
  prompt (this is also the proper fix for the streaming bug that made us drop it in v0.1).
- **Permissions:** a single global mode cycled by a hotkey and shown in the status bar.

**Version:** ships as `0.2.0`.

---

## 1. Persistent session status line (bottom toolbar)

A line pinned below the prompt for the whole session, e.g.:

```
qwen2.5:3b · ctx 14% (1.1k/8k) · 320 out · $0.0000 · sbx subprocess · mode: ask  [Shift+Tab]
```

- **Content:** active model · context filled % (used/window) · output tokens · session cost ·
  sandbox mode · approval mode · hotkey hint.
- **Context %:** `used` = input tokens of the most recent model call (from `model_call` usage),
  or `provider.count_tokens(current messages)` between turns; `window` from a context-window
  lookup — a small table (Claude 200k, GPT-4o 128k, common Ollama models) + `[model.context_window]`
  config overrides + Ollama `/api/show` when available.
- **Refresh:** after every model call (tokens/cost), on mode change, and on a timer (for the
  spinner, see §2).

## 2. Processing animation

- Agent turns run in a worker thread (`loop.run_in_executor`); the prompt_toolkit app stays
  live so the toolbar keeps refreshing while the model works.
- **While a turn is in flight**, the toolbar shows a spinner frame (`⠋⠙⠹⠸…`) plus the current
  phase: `thinking…`, `running tool: python_exec`, `waiting for approval`.
- Streamed tokens print above the prompt via `patch_stdout`; idle → toolbar shows stats only.
- Requires a lightweight phase signal from the loop — `run_turn` will emit status events (e.g.
  a `CompletionDelta` variant or a callback) marking model-call-start / tool-start so the UI
  can label the spinner. The harness stays synchronous; only the UI layer is async.

## 3. Settable permission levels + hotkey

- `ApprovalGate.mode` becomes **runtime-mutable**.
- **Hotkey** (default `Shift+Tab`, configurable) cycles `ask → auto → deny → ask`; also a
  `/mode <ask|auto|deny>` command. The status bar reflects the current mode immediately and
  approval prompts honor it live.
- Session-scoped by default; `/mode <x> --save` writes it to `~/.agent86/config.toml`.
- (Granular per-tool allowlists are explicitly deferred to a later version.)

---

## Reliability & fallback (non-negotiable)

- Keep the v0.1 `input()`-based REPL as a **fallback**. Detect a non-interactive or
  incompatible terminal (piped stdin, no console) → use the plain REPL automatically.
- `AGENT86_PLAIN=1` / `--plain` forces the simple REPL. Bare Git Bash/MinTTY that can't host
  the app gets a one-line hint to use `winpty agent86` or `--plain`.
- This preserves the v0.1 "works in every terminal" win while adding the rich UI where supported.

## Testability

prompt_toolkit apps can't be driven in headless CI, so the wiring stays thin and the logic is
pulled into pure, unit-tested functions:

- `cycle_mode(mode) -> mode`
- `context_window_for(model, config) -> int`
- `context_percent(used, window) -> int`
- `format_status_line(state) -> str`
- spinner frame sequencing
- runtime `ApprovalGate.mode` mutation + `/mode` parsing

## Config additions

```toml
[ui]
status_line = true
spinner = true
mode_cycle_key = "s-tab"     # prompt_toolkit key name

[model.context_window]       # optional overrides for the context-% gauge
"ollama:qwen2.5:3b" = 32768
```

## Build order

1. Context-window lookup + context-% + status-line formatter (pure logic + tests).
2. Runtime-mutable approval mode + `/mode` command + cycle logic (tests).
3. prompt_toolkit app skeleton: `bottom_toolbar` (static stats) + `patch_stdout` streaming.
   Manual verify across PowerShell / Windows Terminal / cmd / Git Bash (+winpty).
4. Worker-thread turns + spinner/phase labels in the toolbar (processing animation).
5. Shift+Tab keybinding → mode cycle; status reflects it live.
6. Plain-REPL fallback + terminal detection; docs; bump to `0.2.0`.

## Dependencies

- Re-add `prompt_toolkit>=3.0` (removed in v0.1). No other new runtime deps.
