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
