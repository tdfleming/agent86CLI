# Quick Task 260922-hwc — Correct the Ollama `num_ctx` hardware facts

**Created:** 2026-09-22
**Type:** Documentation correction
**File:** `docs/BACKLOG.md` § "Auto-size the Ollama context window (`num_ctx`) to the hardware"

## Problem

The § "Key findings (from the reference dev machine)" block describes hardware the reference
machine does not have. Reported by the user 2026-09-22: the box has a 24 GB Radeon RX 7900 XTX.

The entry says "no discrete GPU (Intel Arc iGPU sharing system RAM, CPU/iGPU inference); 15.5 GB
total RAM" and concludes the full 262,144-token context is infeasible (❌ in the table), with a
"practical sweet spot" of 16K–32K. **Every downstream judgement in the entry rests on that**, so
this is not a one-line fix: the feasibility table, the caveats about CPU inference, and the
relative ranking of options A/B/C are all skewed by it.

## Measured on the machine (2026-09-22)

| Fact | Entry says | Actually |
|---|---|---|
| GPU | None discrete; Intel Arc iGPU | **AMD Radeon RX 7900 XTX, 24 GB** (+ an Intel Iris Xe iGPU) |
| System RAM | 15.5 GB | **31.8 GB** |
| Model | `qwen3.5:4b`, ~2.8 GB weights | `qwen3.5:4b` is not installed; nearest is `qwen3.5:latest` — 9.7B, Q4_K_M, **6.6 GB** |
| KV per token | ~32 KB, from "32 layers × kv dim 256" | **32 KB — right number, wrong derivation** (see below) |
| 262,144 context | ❌ infeasible | **✅ 8 GB KV + 6.6 GB weights = 14.6 GB, fits in 24 GB** |

VRAM read from the display-class registry key `HardwareInformation.qwMemorySize` (24 GB);
`Win32_VideoController.AdapterRAM` under-reports it as 4 GB because that field is 32-bit.

KV derivation, from `POST /api/show` on ollama 0.34.2: `block_count` is 32, but
`qwen35.attention.head_count_kv` is a **32-element array of `0` and `4`** — only **8 of the 32
layers carry a KV cache** (every fourth). With `key_length` = `value_length` = 256:
`8 × 4 × (256+256) × 2 = 32,768` bytes/token. The entry's 32 KB is correct by coincidence — it
read the figure as `32 layers × 256 × 2 × 2`. The entry's own caveat 3 ("KV/token has
model-config ambiguity (GQA head count)") was pointing straight at this.

## Tasks

1. Rewrite § "Key findings" — GPU, RAM, model, and the feasibility table, with the corrected
   conclusion that the full trained context fits.
2. Fix the platform-detection bullets in § "The calculation": the operative row is **AMD →
   `rocm-smi`**, and record that `rocm-smi` is **not on PATH** on this Windows box, so the AMD
   path cannot rely on it.
3. Rewrite caveats 1–3 — caveat 2 ("memory ≠ usability on CPU") no longer describes this machine;
   the binding constraint becomes prompt-processing latency, not memory.
4. Re-rank § "Options": A now leaves most of the card unused; B is simply correct here; C is the
   one that pays off.
5. Keep every general caveat intact — the feature ships to users on iGPUs and low-RAM boxes. Only
   the *reference machine* facts and the conclusions drawn from them change.
6. Update the "Analysed in full" cell in the published backlog doc.

## Out of scope

Building any of options A/B/C. This corrects the analysis; the entry stays shelved.
