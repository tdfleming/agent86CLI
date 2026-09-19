---
phase: 07-context-and-cost
subsystem: orchestration/memory/cognitive/ui
tags: [context-window, compaction, summarization, continuation, parallel-tools, prompt-cache, pricing, turn-summary, status-footer]
requirements: [CTX-01, CTX-02, CTX-03, CTX-04, COST-01, COST-02, COST-03]
status: complete
completed: 2026-09-19
---

# Phase 7 — Context & Cost

**Goal:** spend the context window and the token budget well, rather than merely reporting them
accurately. v0.7 made the harness's numbers honest; every number it then reported honestly was
*bad* — a flat 8000-token conversation budget on a 200k window, the oldest turns silently
forgotten, a stable prompt prefix re-billed every turn, a long answer cut off mid-sentence, and
five file reads taken one at a time.

**Requirements:** CTX-01 (real window budget), CTX-02 (summarizing compaction), CTX-03
(`max_tokens` continuation), CTX-04 (parallel tool calls), COST-01 (prompt caching), COST-02
(cache-aware pricing), COST-03 (per-turn cost line).

Like Phases 5 and 6, this phase was executed as a review-driven pass rather than a numbered plan
set: every item was a finding from the v0.6/v0.7 release reviews, recorded in `PROJECT.md`
§ "Next milestone candidates" and `docs/BACKLOG.md` § "Context & cost", not new surface area.
Nothing here changes the scripting contract — `run` and `--plain` are untouched, and `run --json`
only *gains* a key. Work is grouped below by workstream; commits are listed oldest-first within
each group.

---

## Workstream 1 — Loop & context (CTX-01…CTX-04)

**The budget was a constant.** `WorkingMemory(config.limits.max_context_tokens)` was a flat 8000
tokens for every model: on a 200k Claude window it threw away ~96% of the context the user is
paying for; on a 4k local model it *overspent* and the provider answered with a context-length
400. Either way it ignored the two things that are in the request before any history — the
compiled system prompt and the tool schemas. The budget is now derived:

```
window       = capabilities.context_window_for(model_ref, config)
conversation = window − (system prompt + tool schemas)
                      − limits.context_reserve_tokens
                      − capabilities.max_output_tokens_for(model_ref, config)
               …floored, then clamped by limits.max_context_tokens when one is set
```

`context_window_for` resolves in priority order: a `[model.context_window]` override (full
`provider:model` ref, then bare id) → the **provider**, where the *server* rather than the model
owns the window (Ollama serves `[providers.ollama] num_ctx`; llama.cpp's `-c` is a launch flag
that is not discoverable over the OpenAI-compatible API, so 8192 is the only honest answer) → a
built-in family table (Claude 4.x/5.x 200k; `gpt-5` 400k, `gpt-4.1` 1,047,576, `gpt-4o` 128k,
o-series 200k; common open-weights ids) → 8192. The reserve is clamped to half the window so a
small local model is not starved, and `max_context_tokens` is applied *after* the floor so an
explicitly typed hard cap is never overruled by it. `Harness._context_budget` recomputes the whole
thing before every request — skills, MCP servers and the episodic recall note all change the
overhead at runtime — and publishes it on the shared `WorkingMemory`, so sub-agents trim to the
same number. `ModelProvider.count_tokens` also had to learn to count tool-call arguments and tool
names: a step whose entire payload was a large tool argument measured as **zero** tokens, which is
exactly the shape most likely to blow the window.

**The budget was enforced by forgetting.** `WorkingMemory.fit` dropped the oldest messages
silently, so the first thing a long session lost was the user's original ask — and the agent
carried on confidently pursuing a goal it could no longer see. `[limits] compaction = "summarize"`
now replaces the oldest prefix with a model-written digest (GOAL / DECISIONS / FACTS / OPEN,
instructed to reproduce paths, identifiers and numbers verbatim, ~600 tokens), written by the
cheap route model when routing is on and the current provider otherwise. The digest rides on a
**USER** message headed `[Conversation summary — earlier turns compacted]` — no new `Role`,
nothing for four provider adapters to learn — and is *merged* into the following turn when that is
also a USER message, because consecutive user messages are a shape some providers reject (and
Anthropic's `_to_messages` renders `TOOL` results as `user` as well). Four invariants: an
assistant `tool_calls` message is never separated from its `TOOL` results (the cut walks back off
any `TOOL` message it lands on); the last 6 messages and the whole current user turn are never
compacted; compaction runs at most once per step and never re-entrantly; and it **never raises** —
a failed or empty summary falls back to the old drop and records
`compaction status="failed"|"empty" fallback="drop"` in the trace. The compacted `state.messages`
is persisted immediately so a resume sees the compacted history, and the originals are archived
verbatim to episodic memory (`record_compaction`, `kind="compaction"`), held out of `recall` so a
new turn is never handed a raw transcript. `compaction = "drop"` keeps the old behaviour exactly.

**A truncated answer just ended.** `stop_reason == "max_tokens"` was read as a finished answer, so
a long answer stopped mid-sentence and the turn closed `status="done"`. When a completion stops for
length with no tool calls the harness now appends the partial assistant text, asks the model to
continue exactly where it left off, and calls again — up to 3 times per turn, **each one a full
step the circuit breaker counts and budgets**, because a turn that continues three times really is
four model calls. The pieces stream as they arrive and are stitched into one assistant message, so
neither the partials nor the harness's own continuation prompts survive into the history to be
imitated next turn. A truncated step that then calls a tool abandons the stitching: those tool
results have to attach to the assistant message that actually requested them.

**Five reads took five round-trips.** A step's tool calls now execute under the simplest rule that
is safe: approvals for the whole step resolved **first, sequentially, on the orchestrator's
thread** (the gate may prompt a human, and must be asked exactly once per call); then read-only
calls together in a `ThreadPoolExecutor(max_workers=min(4, n))`; then side-effecting calls one at a
time in the order the model asked for them — two writes racing could interleave edits to one file,
and a write racing a read could hand the model a half-written file. Results are observed in **call**
order regardless of completion order, so the `TOOL` messages line up with the assistant's
`tool_calls` for every provider, and the `[tool] name(...)` start lines go out for the whole batch
up front rather than claiming an ordering that isn't real. A cancel landing mid-batch skips the
calls that have not started and gives them a `Not executed: cancelled` result — stricter than the
old path, which simply stopped and could leave a `tool_use` no `tool_result` answered.
`Tool.parallel_safe` (default `True`) is the opt-out; `delegate` sets it, because a nested agent
loop has approval prompts of its own and two racing for one terminal is not something the gate can
untangle. Thread-safety of what a concurrent read touches was checked rather than assumed:
`ToolContext` is read-only for every built-in, the sandbox executor holds no per-call state,
`MCPManager.call_tool` marshals onto its own background loop, and the sub-agent usage accumulator
is now lock-guarded because `acc = acc + usage` is a read-modify-write reachable from a worker
thread.

- `a87a4fa` feat(context): add TurnSummary and the v0.8 context/cost config surface — also lands
  the config fields the rest of the milestone reads, and demotes `max_context_tokens` from *the
  budget* (8000) to an optional hard cap (`0` = none)
- `88c2829` feat(context): budget the conversation against the model's real window
- `c3e08f3` feat(context): summarize the compacted prefix instead of dropping it
- `d0b487e` feat(loop): continue a completion that stopped for length
- `41cbbfb` feat(tools): run a step's read-only tool calls in parallel

## Workstream 2 — Providers (COST-01, COST-02, and the seams they needed)

**Two gaps at the provider seam had to close first.** An output cap the caller asked for was
reaching only some endpoints, and every provider reported its own dialect of "why did you stop" —
so "was this answer truncated?" needed a different test per provider, and nothing in the harness
could ask it generically (which is exactly what CTX-03 needs). `types.StopReason` is the normalized
vocabulary (`end_turn | tool_use | max_tokens | stop_sequence | other`); `Completion.stop_reason`
stays `str | None`, so it is additive and `None` still means "the provider said nothing". Anything
unrecognised — `pause_turn`, `refusal`, whatever is added next — becomes `other` rather than being
read as a finished turn, and a compatible server reporting a plain `stop` on a turn that emitted
tool calls maps to `tool_use`, because the turn is not over, a tool is about to run. On the cap:
the OpenAI-compatible adapters send `max_completion_tokens` (OpenAI's current name) and swap
**once** to the older `max_tokens` on a 400 that names the parameter, memoised per endpoint for the
session — most compatible endpoints (Groq, OpenRouter, vLLM, llama.cpp) only know the old name and
nothing in the base URL says which. That retry is a deterministic correction, not a flaky endpoint,
so it deliberately does not come out of the transient-failure budget and still works with
`max_retries = 0`. Ollama sends `options.num_predict`. Both send **no** cap when nobody asked for
one: they front local servers, where a guessed ceiling truncates a generation that runs free today.
`stream_options: {include_usage: true}` was already requested and is now pinned by a test — without
it a streamed run has no tokens at all and every cost reads zero.

**Every turn re-sent the whole system prompt and tool list at full input price**, though neither
changes across a session. Anthropic's prompt cache exists for exactly that shape. Caching is a
prefix match over tools → system → messages, so a breakpoint on the **last tool** caches the whole
tool list and one on the **system block** caches tools + system; both are stable while the
conversation after them is not, which is the split caching pays for. At most two of the four
available breakpoints are used, leaving room for a caller that marks message content. A marker is
placed only when the prefix it closes clears that model's minimum cacheable length — below it the
API silently ignores the marker and returns `cache_creation_input_tokens: 0`, spending a breakpoint
for nothing — and that minimum is **not monotonic across generations** (512 on the newest models
but 4096 on Opus 4.6/4.5 and Haiku 4.5), so it is a per-family table with a conservative 4096
fallback for a model released after it was written. Eligibility is estimated at ~4 chars/token
rather than spending a `count_tokens` round trip per turn on a decision whose only cost when wrong
is an ignored marker. The system string is converted to the block-list form only when it is being
marked, so an unmarked request goes out byte-identical to before.

**Caching was invisible to the cost meter, in both directions.** A fully-cached turn is a tenth of
the price and a cache write a 25% premium, so billing every prompt token at the input rate made
`limits.max_cost_usd` read a number caching had already made wrong. `Price.cost()` now bills the
three classes apart — reads at 0.1×, 5-minute writes at 1.25×, the uncached remainder at the input
rate — with a per-model override table (Claude Fable 5.1's cheaper reads; Claude Mythos 5.1
deliberately left at the standard rate, because over-charging an estimate beats under-charging a
circuit breaker) and optional explicit `cache_read_per_mtok` / `cache_write_per_mtok` so a config
override can state a rate instead of inheriting the multiplier. Passing zeros reduces exactly to the
old arithmetic, and every existing call site is unchanged.

One contract decision runs through all of it: **`Usage.input_tokens` is the whole prompt, with
`cache_read_tokens` / `cache_creation_tokens` a breakdown *of* it.** Anthropic reports
`input_tokens` as the uncached *remainder*, so the adapter sums them — otherwise a well-cached turn
would look like it barely used any context, and the ctx gauge would lie in the other direction.
`pricing.py` subtracts the breakdown back out to bill each part at its own rate. OpenAI's
`prompt_tokens_details.cached_tokens` follows the same convention.

- `eace8c0` feat(types): add cache token fields to Usage — `Usage.__add__` folds both, so per-step
  and sub-agent accumulation carries the breakdown instead of dropping it
- `b610628` feat(pricing): price prompt-cache reads and writes apart from input
- `3b0c733` feat(cognitive): honour request.max_tokens and normalize stop_reason
- `d7259cb` feat(anthropic): cache the stable prompt prefix and account for it — also raises the
  adapter's default `max_tokens` from a fixed 4096 to 8192, matching `limits.max_output_tokens`

## Workstream 3 — UI (COST-03, and making the new state legible)

The per-turn read-out is the visible payoff of the whole milestone, so it goes through **one**
formatter: `ui.status.format_turn_summary` owns the format and `format_last_turn` owns the
`getattr` probe, so the TUI transcript, the plain loop and `agent86 run` (stderr, non-JSON) cannot
drift.

```
— 3 steps · 2 tools · 4.1k in / 612 out (1.9k cached) · $0.0123 · 8.2s
```

An unpriced model reads `cost n/a (unpriced model)` rather than a fabricated `$0.0000` (the v0.7
rule, held), the cached parenthetical is dropped when nothing was cached, and a state with no
summary prints nothing at all. It is written on the **error path** too — the loop publishes a fresh
summary at the start of each turn and closes it on every exit, so the line always describes the turn
that just ended, and a turn that failed halfway still spent tokens. `run --json` grows an additive
`turn` key; every existing key is untouched, so the scripting contract holds.

The status line became **keyed segments** (`status_segments` / `join_segments`, with
`format_status_line` joining them all) — the same line, but a surface can now reason about its
parts. That is what makes two things possible: the tokens segment becoming `tok <in>/<out>` and
growing `(1.9k cached)` only when the session has prompt-cache traffic (providers without a cache
say nothing about one), and the footer *shedding* rather than wrapping. Measured before the change,
the idle footer was two rows at 80 and 100 columns and only settled at one row from ~127 — a wasted
transcript row that appeared and vanished as the numbers changed. `fit_status_line` now fits the
line to the widget's own width and sheds whole segments in a fixed order: the `[Shift+Tab]` hint
first (it is in `/help` too), then the token counts (one `/cost` away), then the ctx gauge. The
model name, the cost, the approval mode and the working/phase indicator are **never** shed — they
say what is running, what it costs, and whether it can act without asking; a footer that silently
drops `mode: auto` at 80 columns is exactly the quiet omission v0.7 existed to remove. The footer
re-fits on `Resize`, so widening the terminal brings the shed segments straight back. The plain loop
still renders the whole line: it has no widget width to fit to.

`/cost` gained a cumulative `cache read N  written N tok` line plus `saved $X` where the pricing
module can compute it — probed defensively, so an unknown signature degrades to the counts instead
of raising.

Finally, the harness acquired a *voice* distinct from the model's. `[compacted N messages into a
summary]`, `[compaction failed; dropped N messages]` and `[continuation k/3]` reach the UI as
ordinary text deltas, but they are the harness talking *about* the conversation, not the model
answering. Both surfaces classify them by prefix through one shared helper (`ui.repl.notice_text`)
and render them dim on their own line — escaped, like every other untrusted string in the
transcript. The TUI carries them as a new `TurnNotice` message so the app can flush the live stream
first and keep transcript order; the plain loop breaks the current stream line before printing, so a
notice can never be glued onto the model's sentence. `[tool]` keeps winning the classification (it
carries a status-footer label), and model prose that merely opens with a bracket
(`[see docs/ARCHITECTURE.md]`) is **not** a notice and still renders as the answer.

- `32b7224` feat(ui): print a per-turn cost line on every surface
- `9222a29` feat(ui): make the footer and /cost cache- and context-aware
- `607595f` feat(tui): keep the status footer to one row under width pressure
- `e64a713` feat(ui): set the harness's mid-turn notices apart from model speech

## Workstream 4 — Integration

Two fixes that only exist because the other three workstreams landed together.

`ui.status.context_window_for` kept a **second, older window table**. Where the two disagreed the
ctx bar lied: an Ollama session read `ctx 13% (1.1k/33k)` while the loop was compacting against 8k,
because the server — not the model name — owns that window. The gauge now delegates to
`cognitive.capabilities.context_window_for`, the same resolution `_context_budget` uses, keeping its
own table only as a fallback for a tree without that module, and a test pins the two together so
they cannot drift again. The general lesson is the one CTX-01 is built on: one lookup, asked by
everybody.

And `hasattr` narrowing on `last_turn.model_dump` left mypy with `Any | None` and an error on the
call; grabbing the bound method first types cleanly with identical behaviour (a summary that is not
a Pydantic model is serialised as-is, `None` stays `null`).

- `31e30f6` fix(cli): read `last_turn.model_dump` through a bound-method lookup
- `a464ad7` fix(ui): resolve the ctx gauge's window the way the harness budgets it

---

## What this phase deliberately did not do

- **No eval for compaction *quality*.** The summary is tested for shape, placement, the four
  invariants and the drop fallback — not for what it actually preserves across a long session.
  Tracked in `docs/BACKLOG.md` § "Context & cost".
- **No auto-sizing of Ollama's `num_ctx`.** The long-standing backlog entry now has a second
  consumer: `context_window_for` reads `num_ctx` as the Ollama window, so auto-sizing it would move
  the conversation budget with it — which is precisely what that entry's caveat 4 asked for, now
  without needing to touch `max_context_tokens` at all.
- **No change to the scripting contract.** `run` and `--plain` are untouched; `run --json` only
  gains a key.

## Release

CHANGELOG `[0.8.0] - 2026-09-19`; README status block, a new "Context management" section and an
extended "Cost tracking" (prompt caching, cache pricing, the per-turn line);
`docs/ARCHITECTURE.md` synced to 0.8.0 (§5 loop, §6 cognitive, §8 memory, §11 config, and four
rows removed from the §15 "not built" table); `docs/BACKLOG.md` pruned of what shipped; version
bumped to 0.8.0 in `pyproject.toml` and `src/agent86/__init__.py`. 868 tests collected.
