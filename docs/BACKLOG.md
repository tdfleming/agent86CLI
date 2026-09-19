# agent86 — Backlog

Shelved ideas and design notes that aren't scheduled yet. Each entry is self-contained enough
to pick up later without re-deriving the analysis.

---

## Auto-size the Ollama context window (`num_ctx`) to the hardware

**Status:** Shelved (2026-07-12). Analysed, not built. Current behaviour: `num_ctx` is a fixed
config value (`[providers.ollama] num_ctx`, default `8192`), shipped in v0.5.3.

> **Updated 2026-09-19 (v0.8).** This entry now has a second consumer.
> `cognitive.capabilities.context_window_for` reads `[providers.ollama] num_ctx` as *the* Ollama
> context window — the server, not the model name, owns it — and the conversation budget is
> derived from that window (§8 of `docs/ARCHITECTURE.md`). So **caveat 4 below is resolved by
> construction**: `max_context_tokens` no longer needs to be moved in step with `num_ctx`, because
> it is no longer the budget (it defaults to `0` = no cap, and is only an optional hard cap on
> top). Raising `num_ctx` now widens the *input* budget automatically. That makes Option A cheaper
> than it was — bumping the default is a one-line change whose effect propagates — and makes
> Options B/C more valuable, since an auto-sized window is immediately spent rather than merely
> made available. What has not changed: Ollama silently offloads to CPU rather than erroring when
> over-asked, so any auto-sizing must target "fits *without* offload" and carry a speed-aware cap.

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

## Review findings 2026-09-19 (deferred beyond v0.7; § Context & cost closed in v0.8)

Raised during the v0.6.0 release review. None of these block a release; all of them are things a
Claude-Code-like harness eventually wants. The v0.7 "trustworthy harness" items and the v0.8
"context & cost" items are done and live in `.planning/PROJECT.md`; what remains below is the v0.9
and v1.0 surface.

### Context & cost

**✅ Shipped in v0.8.0 (2026-09-19)** — all four original entries in this section are built; see
`.planning/phases/07-context-and-cost/SUMMARY.md`:

- ~~Context compaction / summarization~~ → `[limits] compaction = "summarize"` (CTX-02)
- ~~Prompt caching~~ → Anthropic `cache_control` on the stable prefix (COST-01), priced apart
  from input (COST-02)
- ~~Parallel tool calls~~ → reads concurrent, writes sequential and in order (CTX-04)
- ~~`max_tokens` continuation~~ → up to 3 continuations per turn, each a breaker step (CTX-03)

What that work *opened*, still not built:

- **A compaction-quality eval.** The summarizer is tested for shape and placement — the header,
  the merge into the next user message, the four invariants (tool pairs never split, the last 6
  messages and the current turn never compacted, once per step, never raises), and the drop
  fallback. None of that asks the only question that matters in practice: **does the digest
  actually preserve what the rest of the session needs?** The shape of an eval: a fixture set of
  long real sessions with a known fact planted early (a path, a decision, a user constraint), a
  compaction forced at a known point, and an assertion that a follow-up turn which depends on that
  fact still answers correctly — scored across the cheap and frontier summarizer models, since the
  digest is written by whichever the router picks. Worth pairing with a token-budget regression
  check: a digest that reliably runs long is a budget bug, not a quality one.
- **Compaction is invisible in the trace UI.** The `compaction` recorder event and
  `TurnSummary.compactions` exist, and the transcript shows a dim notice, but `agent86 trace show`
  has no view of *what* was summarized. The originals are archived verbatim to episodic memory
  (`kind="compaction"`), so the data is there; what's missing is a way to read it back.
- **See also** § "Auto-size the Ollama context window (`num_ctx`) to the hardware" above, whose
  relationship to the context budget changed in v0.8.

### TUI

*The v0.9 "coding-agent UX" candidate set — see `.planning/PROJECT.md` § "Next milestone
candidates".*

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

*Also v0.9.*

- **Agent Skills convention + `allowed-tools` enforcement** — align the `SKILL.md` frontmatter
  with the wider convention, and actually enforce a skill's declared tool allowlist while it is
  loaded (today it is documentation, not a gate).

### Observability

*Candidates for v1.0, the release milestone.*

- **OTel exporter wiring** — spans are emitted but there is no configured exporter, so nothing
  leaves the process.
- **Trace redaction and rotation** — the flight recorder is append-only, unbounded, and
  unredacted; it should scrub secrets on write and roll over by size/age.

### Release

*Also v1.0.*

- **PyPI release workflow** — a tagged release should build and publish (trusted publishing),
  rather than the project being install-from-source only.

---

## v0.7 review leftovers

Raised during the v0.7.0 release review. None of them blocked the release; each is a decision
deferred rather than a defect left open. The older, larger deferred list is above in
§ "Review findings 2026-09-19". Two of the four were closed by v0.8 and are struck through below,
with what shipped and where it departed from the analysis recorded here.

### ~~The status footer wraps below ~127 columns~~

**Status: ✅ Done in v0.8.0** (`607595f`, with the keyed-segment groundwork in `9222a29`).
`fit_status_line` fits the line to the widget's own width and sheds **whole segments** in a fixed
order — the `[Shift+Tab]` hint, then the token counts, then the ctx gauge — rather than truncating
the line or dropping sub-parts of a field. Tests cover 80/100/120/140 columns (one row, protected
segments present, worst-case unpriced model), the resize round-trip, and the shed order itself.

Two departures from the analysis recorded here in v0.7, both deliberate:

- **Whole segments, not the window denominator.** Shedding `(3.4k/8k)` out of `ctx 42% (3.4k/8k)`
  keeps a partial field on screen for a few characters of savings and needs its own render path;
  shedding the gauge outright is simpler and frees more width at once.
- **`sbx <mode>` is never shed.** It was fourth on the v0.7 shed list, but it belongs with the
  approval mode: both say what the next tool call is allowed to reach. The protected set is model,
  cost, approval mode, and the working/phase indicator, plus the sandbox mode.

The v0.7 rule that drove it survived intact: **never shed the approval mode.**

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

### ~~Per-turn cost in the footer and `/cost`~~

**Status: ✅ Done in v0.8.0** (`a87a4fa`, `32b7224`) as COST-03 — with one design change worth
recording. The v0.7 sketch was a *second figure in the footer* (`$0.0041 turn / $0.19 session`).
That was rejected: it adds width to the line the section above was trying to narrow, and the
per-turn number is most useful **after** the turn, not during it. What shipped instead is
`TurnSummary` on `state.last_turn` — published at turn start so a surface can watch it fill, and
closed at every exit — rendered as one dim line when the turn ends, on the TUI, the plain loop and
`agent86 run`'s stderr:

```
— 3 steps · 2 tools · 4.1k in / 612 out (1.9k cached) · $0.0123 · 8.2s
```

The footer keeps the session total (plus the cached-token parenthetical), `/cost` gained cumulative
cache reads/writes and savings, and `run --json` carries the summary under an additive `turn` key.

Still open: **a `/cost` breakdown *by turn*** — the original entry asked for one and only the
*last* turn is retained. A per-session list would need turn summaries kept in state (or read back
from the flight recorder, which already has the data) rather than a single `last_turn` slot.

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
