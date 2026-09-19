# agent86 — Backlog

Shelved ideas and design notes that aren't scheduled yet. Each entry is self-contained enough
to pick up later without re-deriving the analysis.

---

## Auto-size the Ollama context window (`num_ctx`) to the hardware

**Status:** Shelved (2026-07-12). Analysed, not built. Current behaviour: `num_ctx` is a fixed
config value (`[providers.ollama] num_ctx`, default `8192`), shipped in v0.5.3.

### Motivation

Ollama defaults to a small context window (~4k), which a `web_fetch` observation can fill,
truncating the response — fixed in v0.5.3 by sending an explicit `num_ctx`. But `8192` is a
conservative fixed value; capable hardware could use far more, and low-RAM machines might want
less. The idea: detect the model's ceiling and the hardware budget and pick `num_ctx`
automatically.

### Key findings (from the reference dev machine)

- **Model `qwen3.5:4b`** — trained context **262,144 (256K)**; 32 layers; Q4_K_M (~2.8 GB
  weights); KV key/value dim 256. The *model* is not the constraint.
- **Hardware is the constraint** — no discrete GPU (Intel Arc iGPU sharing system RAM, CPU/iGPU
  inference); 15.5 GB total RAM. On a no-GPU box, **speed** (prompt processing is O(context)) is
  as limiting as memory.
- KV-cache cost ≈ **~32 KB/token** (f16) for this model:

  | num_ctx | KV cache | Feasible here |
  |---|---|---|
  | 8,192 | ~256 MB | ✅ |
  | 16,384 | ~512 MB | ✅ |
  | 32,768 | ~1 GB | ✅ (free some RAM) |
  | 65,536 | ~2 GB | ⚠️ tight + slow |
  | 262,144 | ~8 GB | ❌ |

  Practical sweet spot on this machine: **16K–32K**. 256K is off the table (needs ~8 GB KV + a
  fast GPU).

### The calculation

```
kv_bytes_per_token = 2(K+V) × n_layers × kv_dim × kv_elem_bytes   # from /api/show model_info
budget             = available_mem × 0.8 − model_weight_bytes − overhead
max_ctx_by_memory  = budget / kv_bytes_per_token
num_ctx            = clamp( floor_to_1024( min(model_ctx, max_ctx_by_memory) ), 4096, cap )
```

Model-side inputs are free to read from Ollama's `POST /api/show` (`block_count`,
`context_length`, key/value lengths, on-disk size). The hard part is `available_mem`, which is
platform-specific:

- **NVIDIA** → `nvidia-smi --query-gpu=memory.free` (cleanest; VRAM is the true limit)
- **Apple Silicon** → unified memory = a fraction of total RAM
- **AMD** → `rocm-smi`
- **Intel iGPU / CPU** → shared system RAM via `psutil`, based on **total RAM − OS reserve**
  (not instantaneous "free", which is too volatile)

### Caveats

1. **Ollama already fits memory itself** — over-asking silently offloads layers to CPU (slower)
   rather than erroring, so the estimate should target "fits *without* offload" and stay
   conservative.
2. **Memory ≠ usability on CPU** — a memory-feasible 64K on a no-GPU box makes every turn crawl.
   "Max we *can*" ≠ "max we *should*"; auto-sizing needs a speed-aware hard cap.
3. **KV/token has model-config ambiguity** (GQA head count). A robust implementation should
   verify against Ollama's actual reported memory (`/api/ps` reports `size_vram` after load)
   rather than trust the formula blindly.
4. **`limits.max_context_tokens` (=8000) must move with `num_ctx`** — it's the working-memory
   *input* budget. Raising `num_ctx` alone only adds output headroom; input is still trimmed to
   8k. Link them (e.g. `max_context_tokens = num_ctx − generation_reserve`).

### Options (increasing effort)

- **A — Raise the fixed value.** Make `num_ctx` easy to set; bump default to 16384; link
  `max_context_tokens`. Predictable, no detection risk. *Best value/effort for CPU/low-RAM
  hardware.*
- **B — `context = "max"`.** Query `/api/show` and use the model's trained max, capped. Simple,
  but dangerous on low-RAM/CPU boxes.
- **C — `context = "auto"`.** The memory-aware formula with platform detection + a speed cap +
  `/api/ps` validation. Most capable, most moving parts (cross-platform memory detection is the
  fragile bit). Pays off mainly on machines with real GPUs and large headroom.

---

## Review findings 2026-09-19 (deferred beyond v0.7)

Raised during the v0.6.0 release review. None of these block a release; all of them are things a
Claude-Code-like harness eventually wants. The v0.7 "trustworthy harness" items live in
`.planning/PROJECT.md`; this list is what sits *behind* them.

### Context & cost

- **Context compaction / summarization** — working memory trims by sliding window. A long
  session should summarize the dropped span instead of forgetting it outright.
- **Prompt caching** — the Anthropic provider doesn't mark cache breakpoints, so a stable system
  prompt + tool schema block is re-billed every turn.
- **Parallel tool calls** — the loop executes a turn's tool calls one at a time; independent
  calls could run concurrently.
- **`max_tokens` continuation** — a response truncated at the output cap currently just ends.
  Detect the stop reason and continue.

### TUI

- **Markdown rendering in the transcript** — model output is written as escaped plain text; code
  fences, lists, and tables deserve real rendering.
- **Diff preview in the approval modal** — approving a `write_file`/`edit_file` should show the
  diff being approved, not just the tool name and arguments.
- **Prompt history and multi-line input** — up-arrow recall and a soft-wrap multi-line composer.
- **`@file` mentions** — path autocomplete in the prompt that inlines a file's content.
- **Session picker** — sessions persist and resume, but only by id on the command line; the app
  should list and pick them.
- **Tool-call collapsing** — long tool observations should fold to a one-line summary that can be
  expanded.

### Skills & tools

- **Agent Skills convention + `allowed-tools` enforcement** — align the `SKILL.md` frontmatter
  with the wider convention, and actually enforce a skill's declared tool allowlist while it is
  loaded (today it is documentation, not a gate).

### Observability

- **OTel exporter wiring** — spans are emitted but there is no configured exporter, so nothing
  leaves the process.
- **Trace redaction and rotation** — the flight recorder is append-only, unbounded, and
  unredacted; it should scrub secrets on write and roll over by size/age.

### Release

- **PyPI release workflow** — a tagged release should build and publish (trusted publishing),
  rather than the project being install-from-source only.

---

## v0.7 review leftovers

Raised during the v0.7.0 release review. None of them blocked the release; each is a decision
deferred rather than a defect left open. The older, larger deferred list is above in
§ "Review findings 2026-09-19".

### The status footer wraps below ~127 columns

**Status:** Measured, not fixed (2026-09-19). Pre-existing — the wrap is not new in v0.7, but
v0.7's `cost n/a (unpriced model)` label makes the widest case wider.

`format_status_line` renders, on one line:

```
<model> · ctx <n>% (<used>/<window>) · <out> out · <cost> · sbx <mode> · mode: <approval>  [Shift+Tab]
```

Measured on the reference machine: **2 rows at 80 columns, 2 rows at 100 columns**, 1 row from
roughly 127 columns up. A two-row footer costs a transcript line and makes the live status jitter
as the phase label changes length during a turn.

The fix is to shed fields as the terminal narrows, not to truncate the whole line. Suggested
order to shed, widest-first:

1. The window denominator — `ctx 42% (3.4k/8k)` → `ctx 42%`. The percentage is the number being
   watched; the absolute pair is reference material.
2. `<out> out` — output tokens are also in `/cost` and the transcript.
3. The `[Shift+Tab]` hint — discoverability, not state; the TUI footer has its own key display.
4. `sbx <mode>` — it changes rarely and only by explicit flag.

**Never shed the approval mode.** It is the field that tells the user whether the next tool call
will stop and ask them. A footer that silently drops `mode: auto` at 80 columns is exactly the
kind of quiet omission v0.7 exists to remove. If only one field can survive, it is that one.

Note that the *unpriced* case (`cost n/a (unpriced model)`) is ~20 characters wider than
`$0.0000`; an abbreviated `cost n/a` at narrow widths is a cheap partial win.

### `web_fetch` is not approval-gated, by design

**Status:** Decided, revisit on user feedback (2026-09-19).

`WebFetchTool.side_effecting = False`, so a fetch never raises the approval modal even in `ask`
mode. That is deliberate: the SSRF guard (scheme restriction, DNS-resolved refusal of
loopback/private/link-local/reserved addresses, manually re-vetted redirects capped at 5 hops, a
2 MB pre-decode body cap, a content-type check) is the mitigation, and `[tools]
web_allow_private` is the documented opt-out. A read that cannot reach anything private is a
read, and gating every fetch would train users to approve blindly — which degrades the approvals
that *do* matter.

Revisit if users ask for it. The shape of the change is a per-tool approval override
(`[guardrails.approval_overrides] web_fetch = "ask"`) rather than flipping `side_effecting`,
which would also change tracing and policy semantics for a tool that still has no side effects.
Egress considerations argue the same way: a fetched page is untrusted *input*, already covered by
`[guardrails] scan_observations`.

### Per-turn cost in the footer and `/cost`

**Status:** Not built (2026-09-19). Small, and the natural follow-on to REL-01.

The footer and `/cost` show the **session** total. The number a user actually watches while
deciding whether to hit Escape is *this turn's* spend — a session total that has been climbing
for an hour tells them nothing about whether the current turn is running away. `Step` already
carries usage and `run_turn` already folds sub-agent usage into it, so the data is there; what is
missing is a per-turn accumulator reset at turn start, a second figure in the footer
(`$0.0041 turn / $0.19 session`), and a `/cost` breakdown by turn. Worth pairing with the
narrow-terminal work above, since it adds width to the same line.

Tracked as a v0.8 "context & cost" candidate in `.planning/PROJECT.md`.

### `test_mcp_live` status

**Status:** In flight at the time of writing (2026-09-19).

`tests/integration/test_mcp_live.py` exercises the real stdio transport against
`tests/integration/live_mcp_server.py`. v0.6.0 moved `mcp` into the dev extra specifically so
this test would run in CI rather than skip. v0.7 changed two things underneath it — MCP stdio
subprocesses now receive `SandboxPolicy.scrubbed_env()` instead of the host environment
(SEC-04), and `Tool.inputSchema` is read defensively across the `mcp` 2.0 `input_schema` rename
— so the live test is the check that a real server still mounts under both.

If the concurrent revival of this test has landed, this entry can be closed. If it has not, the
open question is only whether the live server needs anything added to `sandbox.env_passthrough`
to start under the scrubbed environment (on POSIX it should not: `PATH`, `HOME`, `TMPDIR` and the
locale family are all in the allowlist), and whether the test should assert the scrubbing
directly — a server that echoes its own environment back would pin SEC-04 end-to-end rather than
by unit test alone.
