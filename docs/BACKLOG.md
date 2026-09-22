# agent86 — Backlog

Shelved ideas and design notes that aren't scheduled yet. Each entry is self-contained enough
to pick up later without re-deriving the analysis.

**Priority order, as of 2026-09-22:** § "999.0 — MCP integration work" first (**scoped
2026-09-22** — three workstreams, with phase 999.0a the conformance audit ready to promote), then
§ "Competitive gaps 2026-09-22" — seven items from a competitive read of Claude Code and
Antigravity, parked as phases 999.1–999.7 in `.planning/ROADMAP.md` § Backlog. Everything above
those two sections is older and unranked.

**A note on trusting this file:** on 2026-09-22 two entries were found still listed as open after
the work had shipped (the `Development Status` classifier flip, `06ca3a4`; the `test_mcp_live`
revival, `adae8df`) — one of them for a day, the other for three. Both are struck through below
with the commit that closed them. When picking an item up, **check the code before believing the
entry**; when closing one, close it here in the same commit.

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

> **Corrected 2026-09-22.** The original findings described the wrong machine — "no discrete GPU
> (Intel Arc iGPU…); 15.5 GB total RAM" — and every conclusion below followed from that. The
> reference box has a **24 GB Radeon RX 7900 XTX**. There *is* an Intel Iris Xe iGPU present
> alongside it, which is the likeliest source of the error. **The conclusion inverts: the full
> 256K trained context fits in VRAM.** Re-measured on the machine, ollama 0.34.2.

- **Model** — the entry named `qwen3.5:4b`, which is not installed; the nearest is
  `qwen3.5:latest`: 9.7B params, Q4_K_M, **6.6 GB** on disk, trained context **262,144 (256K)**,
  `block_count` 32. The *model* is not the constraint.
- **Hardware is not the constraint either** — **AMD Radeon RX 7900 XTX, 24 GB VRAM**, plus
  31.8 GB system RAM. Weights and a full-length KV cache both fit on the card with room to spare,
  so inference stays on the GPU and **prompt-processing speed**, not memory, is what bounds a
  large window.
- KV-cache cost ≈ **32 KB/token** (f16) — the right number in the original entry, by the wrong
  route. It was read as `32 layers × kv dim 256 × 2 × 2`. In fact `qwen35.attention.head_count_kv`
  comes back from `/api/show` as a **32-element array of `0` and `4`**: only **8 of the 32 layers
  carry a KV cache at all** (every fourth one), and those have 4 KV heads of
  `key_length` = `value_length` = 256. So `8 × 4 × (256+256) × 2 = 32,768` bytes/token. Caveat 3
  below was pointing straight at this.

  | num_ctx | KV cache | + 6.6 GB weights | Fits in 24 GB |
  |---|---|---|---|
  | 8,192 | 0.25 GB | 6.9 GB | ✅ |
  | 16,384 | 0.5 GB | 7.1 GB | ✅ |
  | 32,768 | 1 GB | 7.6 GB | ✅ |
  | 65,536 | 2 GB | 8.6 GB | ✅ |
  | 131,072 | 4 GB | 10.6 GB | ✅ |
  | 262,144 | 8 GB | 14.6 GB | ✅ ~9 GB headroom |

  **The model's full trained context fits on this card.** The question is no longer "how much can
  we afford?" but "how much is worth paying for?" — prompt processing is still O(context), so a
  256K window costs latency on every turn whether or not it is filled.

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

- **AMD** → `rocm-smi` — **the operative row for the reference machine**, and the one with a
  problem: `rocm-smi` is **not on PATH on Windows**, where ollama drives the card through its own
  ROCm runner. So the AMD path cannot depend on it, and on the primary dev platform there is no
  vendor CLI to ask. Ollama's own `/api/ps` (`size_vram` after a load) is the portable answer and
  is already what caveat 3 recommends verifying against.
- **NVIDIA** → `nvidia-smi --query-gpu=memory.free` (cleanest; VRAM is the true limit)
- **Apple Silicon** → unified memory = a fraction of total RAM
- **Intel iGPU / CPU** → shared system RAM via `psutil`, based on **total RAM − OS reserve**
  (not instantaneous "free", which is too volatile). Still the right path for users without a
  discrete card — it was simply never the reference machine's path.
- **More than one GPU in the box** — the reference machine has both the 7900 XTX and an Intel
  Iris Xe iGPU, and enumeration returns both. Detection has to pick the card ollama will actually
  use, not the first one listed. Reading VRAM needs care too: on Windows,
  `Win32_VideoController.AdapterRAM` reports the 24 GB card as 4 GB, because the field is 32-bit;
  the display-class registry value `HardwareInformation.qwMemorySize` gives the true figure.

### Caveats

1. **Ollama already fits memory itself** — over-asking silently offloads layers to CPU (slower)
   rather than erroring, so the estimate should target "fits *without* offload" and stay
   conservative. Unchanged by the correction, and still the reason auto-sizing cannot simply
   try a number and watch for an error.
2. **Memory ≠ usability** — still true, but for a different reason than this entry first gave.
   The original claim was that a memory-feasible 64K "on a no-GPU box makes every turn crawl";
   on a 24 GB discrete card memory stops binding long before speed does. Prompt processing is
   O(context) regardless of where it runs, so a 256K window that fits is still a 256K window the
   machine pays for on every turn. "Max we *can*" ≠ "max we *should*" survives the correction
   intact — the cap it argues for is a **latency** cap, not a memory one.
3. **KV/token has model-config ambiguity** (GQA head count) — **this caveat was right, and the
   entry above it was the thing it was warning about.** `qwen3.5` is a hybrid architecture where
   three of every four layers hold no KV cache at all, so a formula over `block_count` overstates
   the cost by 4×; it only agreed with reality here because a second error (reading `key_length`
   as the whole KV width) cancelled it. A robust implementation must verify against Ollama's
   reported memory (`/api/ps` gives `size_vram` after load) rather than trust the formula — and
   should treat `head_count_kv` as a per-layer array, not a scalar.
4. **`limits.max_context_tokens` (=8000) must move with `num_ctx`** — it's the working-memory
   *input* budget. Raising `num_ctx` alone only adds output headroom; input is still trimmed to
   8k. Link them (e.g. `max_context_tokens = num_ctx − generation_reserve`).

### Options (increasing effort)

Re-ranked 2026-09-22 — the original ranking assumed the reference machine could not afford a
large window, which was the thing that was wrong.

- **A — Raise the fixed value.** Make `num_ctx` easy to set; bump default to 16384; link
  `max_context_tokens`. Predictable, no detection risk, and since v0.8 a one-line change whose
  effect propagates to the whole conversation budget. Still the best value/effort *for users on
  iGPU or low-RAM hardware* — but on the reference machine 16384 leaves ~22 GB of a 24 GB card
  unused, so as a **default** it now under-serves the box it was tuned on.
- **B — `context = "max"`.** Query `/api/show` and use the model's trained max, capped. On this
  machine that is simply the correct answer: 262,144 fits with ~9 GB to spare. The danger it was
  marked with is real but belongs to *other people's* hardware, which is an argument for making
  it opt-in, not for leaving it unbuilt. Cheapest path to actually using the card.
- **C — `context = "auto"`.** The memory-aware formula with platform detection + a speed cap +
  `/api/ps` validation. Most capable, most moving parts, and the fragile bit — cross-platform
  memory detection — is now known to be fragile in a specific way: two GPUs in one box, no
  `rocm-smi` on Windows, and a 32-bit `AdapterRAM` field that reports 24 GB as 4 GB. **This is
  the option that pays off on the reference machine**, and the correction strengthens rather than
  weakens the case for it, because the speed cap it carries is now the *only* thing standing
  between "fits" and "sensible".

---

## Review findings 2026-09-19 (all sections closed: § Context & cost in v0.8; §§ TUI and Skills & tools in v0.9; §§ Observability and Release in v1.0)

Raised during the v0.6.0 release review. None of these blocked a release; all of them were things
a Claude-Code-like harness eventually wants. **Every original entry in every section below has now
shipped** — v0.7 "trustworthy harness", v0.8 "context & cost", v0.9 "coding-agent UX" and v1.0
"release", all recorded in `.planning/PROJECT.md`. What remains below is only what the shipped
work opened behind it:

| Open | Section | Why it is not done |
|---|---|---|
| A compaction-quality eval | Context & cost | The summarizer is tested for shape, never for what it preserves |
| A `trace show` view of what a compaction summarized | Context & cost | The data is archived; nothing reads it back |
| Click-to-toggle tool-call blocks | TUI | Needs a widget-based transcript; a `RichLog` can't host interactive children |
| History *navigation* in the plain loop | TUI | Needs `readline` on exactly the path kept dependency-free |
| A read/write split in the sandbox jail | Skills & tools | `allow_paths` is one list, so a skill root granted for reading is writable |

§ Release is now **closed too** — the `Development Status` classifier flip shipped in `06ca3a4`
(2026-09-21) and was left listed as open here until 2026-09-22.

Plus § "Auto-size the Ollama context window (`num_ctx`)" above, and the v0.7 leftovers below.

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

**✅ Shipped in v0.9.0 (2026-09-21)** — all six original entries in this section are built; see
`.planning/phases/08-coding-agent-ux/SUMMARY.md`:

- ~~Markdown rendering in the transcript~~ → re-rendered once on completion, `[ui] markdown` (UX-01)
- ~~Diff preview in the approval modal~~ → `Tool.preview`, on the modal *and* the plain loop (UX-06)
- ~~Prompt history and multi-line input~~ → `PromptInput` + `PromptHistory`, shared file (UX-03)
- ~~`@file` mentions~~ → jail-resolved, bounded, with palette completions (UX-04)
- ~~Session picker~~ → named sessions, `/sessions`, `/resume`, `SessionPickerModal` (UX-05)
- ~~Tool-call collapsing~~ → one block per call, `Ctrl+O` / `Ctrl+Shift+O` (UX-02)

What that work *opened*, still not built:

- **Click-to-toggle tool-call blocks.** A block is a *renderable that changes shape*, and the log
  is re-rendered when it does, so toggling is keyboard-driven (`Ctrl+O` for the last,
  `Ctrl+Shift+O` for all) rather than click-driven. That is a consequence of the transcript widget,
  not of the block: a `RichLog` renders its content to strips and **cannot host interactive
  children**, so there is nothing to attach a click handler to. Making a block clickable means a
  widget-based transcript — a `VerticalScroll` of entry widgets, each a real `Collapsible` — and
  the cost is not the migration itself but the surface area around it: every screen, test and
  command that queries `#transcript` does so *as a `RichLog`* (`.write()`, `.clear()`), and the
  streaming path appends a delta per token, which a widget per entry has to absorb without
  reflowing the world. The shape of the change: keep an entry-widget container behind the same
  `#transcript` id with a `RichLog`-compatible facade for the streaming writes, migrate the
  finished-entry re-render to child widgets, and keep the keyboard bindings as the accessible path.
  Worth doing when the transcript grows a second interactive element (an inline diff to approve,
  say); not worth it for toggling alone.
- **History *navigation* in the plain loop.** Both surfaces write the same `[ui] history_file`, and
  the plain loop appends to it faithfully — but it can only append. Stdlib `input()` has no line
  editor, so there is no Up-arrow there at all: the shared history is a record the TUI can walk and
  the plain loop can only contribute to. Fixing it means `readline` (or `pyreadline3` on Windows,
  which is a third-party dependency on the *plain* path — exactly the path kept dependency-free so
  `run` and `--plain` start fast). A decision, not an implementation: either accept an optional
  import that is absent more often than not, or accept that the plain loop is append-only. It is
  documented as append-only today.

### Skills & tools

**✅ Shipped in v0.9.0 (2026-09-21)** — the original entry in this section is built:

- ~~Agent Skills convention + `allowed-tools` enforcement~~ → frontmatter parsed to the convention
  (a `---` line, block scalars, space-delimited `allowed-tools`, PyYAML optional), a five-root
  first-root-wins search order, and `ToolRegistry.dispatch` refusing anything outside a non-empty
  allowlist for the duration of the turn (SKILL-01)

What that work *opened*, still not built:

- **The sandbox jail has no read/write split.** `skill_roots()` is granted to the policy so a
  skill's bundled resources — which for a user skill live outside the workspace — are readable
  instead of a jail error on the first "see `reference.md`". But the grant goes into
  **`allow_paths`**, and `allow_paths` is one list: a path on it is readable *and writable*. So
  `~/.agent86/skills` and `~/.claude/skills` are now write-targets for `write_file`, `edit_file`
  and `run_command`, which means a model can edit the instructions it is about to be given — and
  `~/.claude/skills` is shared with another tool entirely. The intent was read-only, and the policy
  has no way to express it. The shape of the fix: `SandboxPolicy` grows separate read and write
  sets (`allow_read_paths` / `allow_write_paths`, with today's `allow_paths` seeding both for
  compatibility), `skill_roots()` feeds only the read set, and the executor checks the set matching
  the operation. Until then the exposure is bounded by the approval gate — every one of those tools
  is side-effecting, so a write there is a call the user is asked about — but a user in `auto` mode
  has no such protection.

### Observability

**✅ Shipped in v1.0.0 (2026-09-21)** — both original entries in this section are built; see
`.planning/phases/09-release/SUMMARY.md`:

- ~~OTel exporter wiring~~ → the tracer builds its own `TracerProvider` with a `Resource`, an
  exporter chosen by `[observability] otel_exporter` and a `BatchSpanProcessor`, honours the
  standard `OTEL_*` env vars, and deliberately does *not* become the global provider (OBS-03)
- ~~Trace redaction and rotation~~ → `redact_event` gates every event (the guardrail tier's own
  regexes, `***REDACTED***`, inherited truncation at `max_field_chars`, never raises) (OBS-01),
  and the live file rotates at `max_trace_bytes` keeping `keep_traces` generations, renaming
  *between* events so nothing is half-written (OBS-02)
- Beyond the two: `agent86 trace export` (`jsonl` / `json` / `otlp-json`, the last reconstructing
  a span tree from the recorder's own events) and `trace show --kind/--since` with token and cost
  columns (OBS-04)

Still not built — **carried from § "Context & cost" above**: `trace show` has no view of *what* a
compaction summarized. The `compaction` event and the archived originals exist; reading them back
from the CLI does not. It is now the only observability row left in `docs/ARCHITECTURE.md` §15.

### Release

**✅ Shipped in v1.0.0 (2026-09-21)** — the original entry in this section is built:

- ~~PyPI release workflow~~ → `.github/workflows/release.yml` on a `v*` tag: pre-flight
  (`scripts/check_release.py`) → `uv build` → `twine check` → the packaging tests → **trusted
  publishing** through the `pypi` environment (OIDC, no token in the repo) → a GitHub Release
  carrying that version's CHANGELOG section, with a `workflow_dispatch` TestPyPI rehearsal
  (PKG-02). Complete PyPI metadata, the MIT `LICENSE` file, allowlisted artifacts and
  `tests/packaging/` asserting the built wheel came with it (PKG-01). The procedure is
  `docs/RELEASING.md`.

What that work opened is **also shipped** — this section is closed:

- ~~**The `Development Status` classifier flip.**~~ **✅ Done in `06ca3a4` (2026-09-21).**
  `pyproject.toml:11` now reads `Development Status :: 5 - Production/Stable`, with the reason
  inline as a comment (`# 1.0.0 is live on PyPI (2026-09-21)`).

  The v1.0 analysis, kept because the *reasoning* is reusable at the next 2.0: 1.0 was tagged
  `4 - Beta` on purpose, because the classifier is a claim about a *published* artifact and
  nothing is published at the moment a tag is cut. The trigger was the first release after
  1.0.0 went live on PyPI, and it was taken at the next commit rather than spent as a release of
  its own. **This entry stayed listed as open here for a day after it shipped** — closed
  2026-09-22.

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

### ~~`test_mcp_live` status~~

**Status: ✅ Closed 2026-09-22.** The revival this entry was waiting on landed in `adae8df`
("test(mcp): revive the live transport test against the mcp 2.0 server API"). The test now probes
`mcp.server.mcpserver` (not the removed `mcp.server.fastmcp`) plus `uvicorn` via
`pytest.importorskip`, so it runs on a `.[dev]` install and skips cleanly where the extra is
absent — which was the original point of moving `mcp` into the dev extra in v0.6.0. The entry's
own closing condition ("if the concurrent revival of this test has landed, this entry can be
closed") was met on 2026-09-19 and went unnoticed until 2026-09-22.

Its one open sub-question is **not** closed and is worth keeping: the test does not assert
`SandboxPolicy.scrubbed_env()` end-to-end. A live server that echoed its own environment back
would pin SEC-04 in the real transport rather than by unit test alone. Small, and the fixture
already exists.

The v0.7 analysis, retained:

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

---

---

## 999.0 — MCP integration work (scoped 2026-09-22)

**Status:** Scoped 2026-09-22; phase **999.0a** (conformance audit + ADRs) is ready to promote,
999.0b–d unwritten by design. **Ranked above every other open item in this document**, including
all seven competitive gaps below — that priority is a standing instruction, recorded here so it
survives the conversation it was given in.

**The scope was given, not inferred.** Opened 2026-09-22 as a deliberate blank ("do not prioritise
[the competitive gaps] over MCP integration", with no scope attached); the four rulings below —
which workstreams are in, that server mode is out, conformance as the driver, demand as the
ceiling — were answered by the requester the same day. Read "What this actually means" before
planning, and do not widen it by inference: the audit's job is to propose, not to assume.

### What already exists (so this is not rebuilt by accident)

MCP is **built and complete against `docs/ARCHITECTURE.md`** as a *tool* client — which is why
the scope below is about depth, auth and lifecycle rather than building a client, and why the
scope was never inferable from the code alone:

- `tools/mcp_client.py` (463 lines) — an `MCPManager` mounting external server tools into the
  registry, over all three transports: **stdio** (default, via `command`), **SSE**, and
  **streamable HTTP** (ARCHITECTURE §928).
- `tui/screens/mcp_manager.py` (473 lines) + `tui/screens/mcp_test.py` — in-app add/remove/test
  with tool enumeration, shipped as v0.6 Phase 4.
- `agent86 mcp [list|add|remove]` on the CLI (§946).
- Security: stdio servers get `SandboxPolicy.scrubbed_env()` rather than the host environment
  (SEC-04, v0.7); `${VAR}` references in MCP config entries resolve at call time rather than
  storing secrets (§816); `MCPManager.call_tool` marshals onto its own loop (§317).
- Trust: a tool whose annotations carry `readOnlyHint` mounts `side_effecting = False` and is not
  approval-gated (§584, §683).
- Collisions: `ToolRegistry.try_register` records a duplicate name instead of raising, and the
  collision list is logged at startup.

### What this actually means

**Scope set 2026-09-22.** Three workstreams in, one non-goal, one spike promoted.

| | Workstream | Tier | Covers |
|---|---|---|---|
| A | Client depth | 4 (+3 fallout) | Resources and prompts as first-class. Sampling / elicitation / roots **audited and ruled on**, not assumed in — see the ADR rows below. |
| B | Remote auth | 4 + secrets | OAuth 2.0 for hosted servers: discovery, authorization, refresh, tokens in the existing keyring. |
| C | Context & lifecycle | 3/4 | Schema deferral, per-server timeouts, result caps, reconnect, `list_changed` handling. |

**Non-goal: MCP server mode.** agent86 stays a client; it does not become mountable by other
harnesses. Recorded in `docs/ARCHITECTURE.md` §15 so the slot is not reopened by inference.

**Driver is conformance; the ceiling is demand.** The client half of the MCP spec is the
*measuring stick* — the audit sweeps all of it, so nothing is missed by accident. The corpus is
the *trigger* — a feature ships when a corpus server exercises it. Anything the spec defines and
no corpus server uses becomes a written non-goal in §15 **with its reasoning**: a conformance
statement, not a silent gap.

**Standing constraints (unchanged, and B strains them hardest).** The `mcp` extra stays optional
with graceful degradation; `run --json` keys are additive-only; no new core dependencies and the
cold-start budget holds. An OAuth flow that must work both interactively and headless in CI is a
design decision, not a library choice.

### 999.0a — Conformance audit + ADRs (the only phase to promote)

No implementation. Three deliverables:

1. **The conformance matrix** — every client-side spec capability × {implemented / partial /
   absent} × {exercised by corpus / not} × {in / out, with reasoning}.
2. **The pinned corpus**, below.
3. **An ADR per contract-touching ruling** — at minimum the four named below.

Phases 999.0b–d are written only after the matrix is ruled on.

**The corpus** (pinned by version; DocIngest is explicitly out — common examples only):

| Server | Why it's in |
|---|---|
| `@modelcontextprotocol/server-everything` | The conformance instrument: tools + resources + prompts in one place. **First audit task:** determine whether it also drives sampling, elicitation and progress — that answer decides whether those three are demand-triggered or stay non-goals. |
| `@modelcontextprotocol/server-filesystem` | Realistic stdio tools; the roots question. |
| `mcp-server-git` | Second realistic stdio server; the natural bridge to 999.5. |
| `tests/integration/live_mcp_server.py`, extended to echo its own environment | Pins **SEC-04 end-to-end**, closing the first adjacent thread below. Local, no network, already in CI. |
| GitHub's remote MCP server (`github/github-mcp-server`, hosted) | Workstream B's target. The archived `modelcontextprotocol/servers` reference server is *not* the one — use the externally maintained hosted product, so OAuth, streamable HTTP and refresh are exercised against something real. |

**ADRs the audit must produce:**

- **Sampling is an inversion of control, not a tool.** Implementing it makes agent86 the model
  provider for a *server's* request: third-party spend inside our turn, against
  `limits.max_cost_usd`, with the completion visible to the server. If it ships at all it is
  **opt-in per server**, and it needs an approval gate and an egress pass of its own.
- **Elicitation is a Tier 1 surface.** A server prompting our user through our gateway is a
  phishing vector. Who renders it, and what it may not ask for, precede any decision to support it.
- **Schema deferral changes the prompt contract.** Names + server instructions in the system
  prompt, full schema on first use, means the prompt no longer lists every callable tool. That
  interacts with `allowed-tools` gating (the prompt currently names the boundary so a refusal does
  not cost a step) and with `context_budget`'s fixed-overhead computation (§8).
- **Result caps have no home yet.** `_content_to_text` joins every content part uncapped, while
  the flight recorder clips at `max_field_chars`. Decide where the prompt-side cap lives and
  whether it is per-server.

**Audit head start** — found by reading `tools/mcp_client.py` on 2026-09-22; nine matrix rows
already grounded:

- `ClientSession(read, write)` is built with **no callbacks** — sampling, elicitation and roots
  are structurally absent, not merely uncalled. Any one of them is a constructor change.
- `initialize()` → `list_tools()` and nothing else: no `list_resources`, `read_resource`,
  `list_prompts`, `get_prompt`.
- **No `message_handler`, so every server notification is dropped.** A server that changes its
  tool list mid-session is invisible until restart — and `list_changed` is the mechanism
  `/config mcp`'s live mount already wants.
- Timeouts are hardcoded and asymmetric: 30 s connect (`start_server`), **120 s per tool call**
  (`call_tool`). `MCPConfig` carries only `enabled`, so neither is configurable; a slow legitimate
  server and a hung one are indistinguishable.
- `_content_to_text` applies **no size cap** — a large resource dump goes straight into the budget.
- **Only `.text` content is read.** Image, audio and embedded-resource blocks fall through to
  `str(chunk)`, so a base64 blob lands in the prompt verbatim.
- **Likely defect, confirm before fixing:** `_serve`'s `finally` pops `self._sessions[name]` but
  leaves `self._server_tools[name]` populated, while `call_tool` indexes `self._sessions[server]`.
  A stdio server that dies mid-session appears to leave registered tools pointing at nothing.
- **No reconnect path at all** — `_serve` awaits `close_event`; a dropped transport ends the task.
- Auth is `headers` + `${VAR}` only: no discovery, no refresh, no token storage. The keyring
  plumbing from `/config model` is reusable as-is.

That distribution suggests **C is larger than A, and materially larger than B** — worth knowing
before the phases are sized.

### MCP-adjacent threads that *are* concrete

These exist independently of 999.0's three workstreams and should not be folded into them
silently — though the first is now *scheduled* by 999.0a, which pins SEC-04 through the corpus
server it extends:

- **SEC-04 is not asserted end-to-end.** `tests/integration/test_mcp_live.py` exercises the real
  stdio transport but never checks that the scrubbed environment actually reached the server. A
  live server that echoed its own environment back would pin it. Carried from § "v0.7 review
  leftovers" below, where the rest of that entry is now closed.
- **`web_search` is a non-goal *because* of MCP.** `docs/ARCHITECTURE.md` §15 answers the missing
  `web_search` built-in with "use an MCP search server". That reasoning is sound, and it is worth
  re-reading against **999.1** below: the same argument does *not* extend to `grep`/`glob`, since
  orienting in the local repo is not something a user should have to mount a server to do.

## Competitive gaps 2026-09-22

Raised after v1.0 shipped, from a read of Claude Code and Antigravity. These are not defects
against `docs/ARCHITECTURE.md` — the harness is complete against that contract — they are
**table stakes both competitors ship that the contract never asked for**. None of them requires
abandoning the five-tier model; each lands inside an existing tier.

**Standing constraint: none of this outranks MCP integration work.** MCP sits above the whole
block. Within the block:

| # | Phase | Item | Tier | Why this order |
|---|---|---|---|---|
| 1 | 999.1 | `grep` / `glob` built-ins | 4 (Tools) | Highest value per line of code in the whole list; ~200 lines; unblocks every "where is X" question |
| 2 | 999.2 | `PreToolUse` / `PostToolUse` hooks | 5 (Guardrails) | The missing extension point; also the deterministic policy gate Tier 5 wants |
| 3 | 999.3 | Declarative sub-agents (`.agent86/agents/*.md`) | 2 (Orchestration) | Makes `delegate` reproducible and check-in-able |
| 4 | 999.4 | Plan-mode gate | 1/2 (Gateway/Orchestration) | A strategic approval above the tactical per-call one |
| — | 999.5 | Git awareness | 4 | Unordered; partly a prerequisite for isolated sub-agents (999.3) |
| — | 999.6 | Network control around `run_command` | 4/5 | Unordered; a verified hole, see below |
| — | 999.7 | Model-based injection classifier | 5 | Unordered; lowest confidence of payoff, see the ceiling note |

---

### 999.1 — Codebase intelligence: `grep` and `glob` built-ins

**Status:** Shelved (2026-09-22). Not built. **Highest-value item in this section.**

The built-in tool set is exactly seven (`tools/registry.py` `_BUILTINS`): `read_file`,
`write_file`, `edit_file`, `list_dir`, `run_command`, `python_exec`, `web_fetch`. There is no
search primitive. Every "where is this defined?" therefore routes through `run_command`, which is:

- **approval-gated** — a side-effecting tool, so it prompts, for what is a pure read;
- **platform-variable** — the primary dev platform is Windows 11, so `grep`/`rg`/`find` may not
  exist, and the invocation differs between PowerShell and POSIX;
- **quoting-expensive** — a whole step burned on shell escaping, then another on the retry.

Claude Code ships `Glob`, `Grep` and an LSP tool as **no-permission** tools precisely because
search is how an agent orients in a repo. The read-only classification matters as much as the
tool: it makes search free of the approval loop *and* eligible for the parallel read-only batch
built in v0.8 (CTX-04).

**Shape of the work.** Two `Tool[TArgs]` subclasses in `tools/builtin/`, both
`side_effecting = False`, both parallel-safe:

- `glob` — a pattern and an optional root; resolve through `SandboxPolicy` so matches cannot
  escape the jail; return paths sorted by mtime (the ordering that makes "what changed" cheap).
- `grep` — a regex, an optional path/glob filter, and an output mode (files-with-matches /
  content / count) with a head limit. Pure Python (`re` + `os.scandir`) keeps it dependency-free
  and identical on Windows and POSIX; shelling out to `rg` when present is an optimisation, not
  the contract, and must not become one.

Both must honour the jail (`policy.resolve_path`) and skip binaries and `.git`. Estimated ~200
lines plus tests. Worth pairing with `docs/ARCHITECTURE.md` §15, which currently has no row for
search.

**Open question:** whether a read/write split in `allow_paths` (already in this backlog, §
"Skills & tools") should land first, so a search root can be granted read-only.

---

### 999.2 — A `PreToolUse` / `PostToolUse` hook event

**Status:** Shelved (2026-09-22). Not built. There is **no extension point between the loop and
the outside world at all** — `grep -rln hook src/agent86` matches one file, and that is
`cognitive/pricing.py` talking about something else.

Claude Code has 33 hook events across five handler types. Antigravity has five — `PreToolUse`,
`PostToolUse`, `PreInvocation`, `PostInvocation`, `Stop` — and routes *all* custom observability
and audit logging through them. agent86 has the flight recorder, which is excellent and
in-process, but nothing a user can wire their own behaviour into without editing the package.

**Why this is a Tier 5 story and not just a convenience.** The guardrails today are
`guardrails/scanners.py` — regex. A `PreToolUse` hook that can return *deny with a reason*,
*allow*, or *allow with modified args* is the deterministic policy hook the Tier 5 narrative
already implies: a user can block `run_command` matching a pattern, force a tool's args through
a linter, or require a second signal before a write, without the harness having to guess at a
regex for it.

**Shape of the work.** Start with the two tool-boundary events only; `PreInvocation`,
`PostInvocation` and `Stop` can follow.

- Config: `[[hooks]]` entries naming an event, an optional tool-name matcher, and a command.
- Contract: the hook receives a JSON document on stdin (event, tool name, validated args, the
  workspace root) and answers with an exit code plus optional JSON on stdout — exit 0 allow,
  non-zero deny, with the reason fed back to the model as a `ToolResult` error it can
  self-correct from. **This must never raise into the loop** (the standing rule for tool
  execution applies to hooks verbatim).
- Execution: through the existing `SandboxPolicy` — a hook is user-authored code, but it runs
  with the harness's trust, so its env must still be scrubbed. Timeout mandatory.
- The hook's decision belongs in the flight recorder as its own event, so an audit shows *why*
  a call was denied.

**Ordering note:** doing this before 999.6 is deliberate — a `PreToolUse` deny is a cheap
partial mitigation for the unguarded shell while a real network control is designed.

---

### 999.3 — Declarative sub-agents: `.agent86/agents/*.md`

**Status:** Shelved (2026-09-22). Not built. `delegate` is **dynamic-only**.

`tools/builtin/delegate.py` takes two free-text strings — `role` (default `"assistant"`) and
`task` — and spawns a sub-agent through `ctx.spawn`. That is powerful and it works, but it is
**unreproducible**: the role is invented per call by the model, so a colleague cannot check in
"the researcher agent", cannot review what tools it may use, and cannot pin it to a cheaper
model. Two runs of the same prompt need not produce the same sub-agent.

Both competitors define sub-agents as **Markdown + YAML front matter on disk** —
`.claude/agents/` and `.agents/agents/` — carrying per-agent model, tool allowlist, permission
mode and workspace isolation. Both then bundle skills + agents + rules + MCP + hooks into
installable plugins with marketplaces.

**Shape of the work.** The skill loader (`skills/`) already does progressive discovery of
Markdown-with-front-matter from disk, and v0.9 already enforces `allowed-tools` as a gate — so
this is substantially a second consumer of machinery that exists.

- `.agent86/agents/<name>.md`: front matter for `description`, `model` (a `ModelRef`),
  `tools` (an allowlist, enforced by the same gate as a skill's `allowed-tools`),
  `approval` (an `ApprovalMode`), and later `isolation` (see 999.5); body is the system prompt.
- `delegate` gains an optional `agent` argument naming a discovered definition; the free-text
  `role` path stays, so nothing regresses.
- A per-agent `model` means a definition can pin the cheap model for a bounded subtask, which
  interacts directly with the v0.8 cost work and the router.
- Discovery must be lazy and must not cost the one-shot `run` path anything when the directory
  is absent.

**Deliberately out of scope for a first pass:** a plugin/marketplace format. Get the on-disk
definition right first; bundling is a distribution problem, not a harness one.

---

### 999.4 — A plan-then-execute gate

**Status:** Shelved (2026-09-22). Not built.

v0.9 made approval *good*: per-call, showing the actual change as a diff, better presented than
most. But it is a **tactical** gate. Approving forty diffs one at a time is a different product
from approving one plan.

Antigravity's whole UX bet is that plans, task lists and walkthroughs are "easier for users to
validate than raw tool calls", reviewed with inline comments before any file changes. Claude Code
has plan mode plus a read-only Plan sub-agent.

**Shape of the work.**

- A new `AgentPhase` (or an `ApprovalMode` sibling — `types.py` owns both) in which the loop
  admits only non-`side_effecting` tools. Once 999.1 lands, that mode is genuinely useful, because
  the agent can search, read and reason without being able to write.
- The phase ends with a structured plan the model emits; the harness renders it and asks once.
  Approve → the loop leaves plan mode with the plan in context. Reject → the rejection text is
  fed back and planning continues.
- Surfaces: a `/plan` command and a palette entry in the TUI, a `--plan` flag on `run`. **The
  plain loop and `run --json` must keep working unchanged** — this is additive to the scripting
  contract, never a change in its default behaviour.
- Inline comments on a rendered plan are the Antigravity-grade version and are a TUI project of
  their own; a whole-plan accept/reject is the honest first step.

**Interaction with 999.3:** a read-only Plan agent is the obvious first entry in
`.agent86/agents/`, which is an argument for doing 999.3 first — as ordered.

---

### 999.5 — Git awareness: checkpoint/rewind, worktree isolation, a diff surface

**Status:** Shelved (2026-09-22). Not built. Unordered within this section.

There is no checkpoint/rewind, no worktree isolation for sub-agents, and no diff/stage/commit
surface. Both competitors treat **the worktree as the unit of agent isolation**: Antigravity
branches sub-agents into isolated worktrees; Claude Code has `isolation: worktree` in sub-agent
front matter.

Today agent86's `delegate` sub-agents **share the workspace jail** (`SandboxPolicy` is built per
workspace, and `spawn` does not vary it). That is the cap on how parallel delegation can safely
get: two sub-agents editing the same tree race, and nothing in the harness notices.

Three separable pieces, in rising order of cost:

1. **A diff surface** — a read-only `git_status` / `git_diff` capability so the agent can see its
   own changes without `run_command`. Cheapest, and it composes with 999.1's read-only class.
2. **Checkpoint/rewind** — a marker before a turn's first write and a way back. Needs a real
   answer for a dirty tree and for untracked files; a stash-based implementation is tempting and
   is how this usually goes wrong.
3. **Worktree isolation for sub-agents** — `git worktree add` per delegated agent, the jail
   rebased onto it, and a merge-back story. This is the piece that raises the parallelism
   ceiling, and it is the one with a real design cost: what happens when a sub-agent's worktree
   conflicts on merge is a product decision, not an implementation detail.

Piece 3 is what `isolation:` in 999.3's front matter would select.

---

### 999.6 — Network control around `run_command`

**Status:** Shelved (2026-09-22). Not built. **Verified hole**, not a theoretical one.

`SandboxPolicy` carries a `network: bool` (default `True`) and a `require_network()` guard — and
`require_network()` has **exactly one call site in the codebase**: `tools/builtin/web.py:172`.
So the SSRF guard protects `web_fetch` only, and `curl 169.254.169.254` from `run_command` is
unguarded. `python_exec` likewise. The Docker executor is the exception and does the right thing
(`--network none` unless `docker_network` is set, `docker_exec.py:62`), but Docker is opt-in and
the default is subprocess.

The env allowlist and the process-tree kill (v0.7) are real controls; this is the gap beside
them. Both competitors put a network deny/allowlist around **the shell itself** — Antigravity via
nsjail/AppContainer, Claude Code via a filtering proxy with per-command domain approval.

**Shape of the work.** `docs/ARCHITECTURE.md` lists gVisor and WASM as non-goals, and that stays
true — but OS-native primitives are not the same tier of effort:

- **Windows** (the primary platform, and the one where Claude Code has *no* sandbox at all — so
  this is a differentiator, not catch-up): AppContainer, or a WFP/firewall rule scoped to the
  child process.
- **Linux**: a user namespace plus an empty network namespace for the child.
- **macOS**: `sandbox-exec` is deprecated but present; otherwise a proxy.
- **Portable fallback**: route the child through a loopback filtering proxy with an allowlist and
  scrub the proxy-bypass env vars. Weaker — it is defeated by anything that ignores
  `HTTP(S)_PROXY` — but it is the same mechanism on every platform and it composes with the
  existing env scrubbing.

**Minimum honest first step, if the full thing is too big:** make `require_network()` actually
mean something for the shell — refuse to launch `run_command` at all when `network = false`, and
document that `network = true` grants the child unrestricted egress. Today the flag reads as a
control it is not.

---

### 999.7 — A model-based prompt-injection classifier

**Status:** Shelved (2026-09-22). Not built. Unordered, and the **lowest-confidence** item here.

`guardrails/ingress.py` and `egress.py` run `scanners.py`, which is regex. Claude Code runs a
second model over proposed actions in auto mode. The shape for agent86 is available cheaply: the
router already picks between a cheap and a frontier model, sub-agent accounting already exists
(v0.7), and 999.2's `PreToolUse` is the natural mount point — so a classifier is a hook handler
rather than a new tier.

**State the ceiling honestly, in the entry and in any docs that come out of it.** Nobody has
solved this:

- Antigravity shipped a prompt-injection → RCE that bypassed its **most restrictive** mode
  (patched Feb 2026, disclosed April).
- Claude Code carries CVE-2026-39861, a symlink sandbox escape.

So agent86 is not *behind* on this problem so much as **un-defended on a problem the others are
also losing**. That is an argument for doing it — regex is a weaker floor than a model — and
equally an argument against selling it as a solution. A classifier that adds latency and cost to
every auto-mode action while advertising safety it cannot deliver is worse than an honest regex
plus a good `PreToolUse` deny rule, which is why this sits below 999.2 and 999.6.

**Prerequisite:** 999.2. Build the mount point first; do not special-case a classifier into the
loop.
