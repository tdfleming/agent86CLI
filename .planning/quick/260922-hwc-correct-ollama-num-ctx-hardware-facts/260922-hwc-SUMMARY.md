# Quick Task 260922-hwc — SUMMARY

**Completed:** 2026-09-22
**Scope:** `docs/BACKLOG.md` § "Auto-size the Ollama context window (`num_ctx`) to the hardware"

## What was wrong

The § "Key findings (from the reference dev machine)" block described hardware the machine does
not have: "no discrete GPU (Intel Arc iGPU sharing system RAM, CPU/iGPU inference); 15.5 GB total
RAM". The box has a **24 GB Radeon RX 7900 XTX** and 31.8 GB of system RAM. An Intel **Iris Xe**
iGPU is also present, which is the likeliest source of the original error — enumeration returns
both adapters.

This was not a cosmetic error. The entry's feasibility table, two of its four caveats, and the
ranking of its three options were all derived from the wrong machine.

## What changed

1. **Key findings rewritten.** Corrected GPU, RAM and model, with a dated note saying plainly
   that the original described the wrong machine.
2. **Feasibility table inverted.** Was `262,144 → ~8 GB → ❌`, with a "practical sweet spot" of
   16K–32K. Now every row up to and including the model's full 262,144 trained context fits:
   8 GB KV + 6.6 GB weights = 14.6 GB, with ~9 GB of headroom on the card.
3. **Platform-detection bullets reordered and extended.** AMD → `rocm-smi` is the operative row,
   and `rocm-smi` is **not on PATH on Windows** — so the primary dev platform has no vendor CLI
   to query. Added a multi-GPU bullet, and the finding that
   `Win32_VideoController.AdapterRAM` reports the 24 GB card as 4 GB (32-bit field);
   `HardwareInformation.qwMemorySize` in the display-class registry key is correct.
4. **Caveats 2 and 3 rewritten.** Caveat 2's conclusion survives but its reasoning does not —
   the cap it argues for is a latency cap, not a memory one. Caveat 3 was *right*, and is now
   marked as having been a warning about the very block above it.
5. **Options re-ranked.** A now under-serves the reference box as a default; B is simply correct
   on this machine; C is the one that pays off, and the correction strengthens its case.

## The KV finding, which is worth keeping

The entry's `~32 KB/token` is correct — by coincidence. It was derived as
`32 layers × kv dim 256 × 2 × 2`. Measured via `POST /api/show` on ollama 0.34.2,
`qwen35.attention.head_count_kv` is a **32-element array of `0` and `4`**: `qwen3.5` is a hybrid
architecture in which only **8 of 32 layers carry a KV cache** (every fourth), each with 4 KV
heads of `key_length` = `value_length` = 256. So `8 × 4 × (256+256) × 2 = 32,768` bytes/token.

Two errors cancelled: a formula over `block_count` overstates cost by 4×, and reading
`key_length` as the entire KV width understates it by 4×. Any implementation of option C must
treat `head_count_kv` as a per-layer array and validate against `/api/ps` `size_vram`, exactly as
caveat 3 said.

## Verification

Facts measured on the machine, not inferred:

- `Get-CimInstance Win32_VideoController` → both adapters; registry
  `HardwareInformation.qwMemorySize` → 24 GB
- `Win32_ComputerSystem.TotalPhysicalMemory` → 31.8 GB
- `ollama list` → `qwen3.5:4b` absent; `qwen3.5:latest` present at 6.6 GB
- `ollama show qwen3.5:latest` → 9.7B, Q4_K_M, context length 262,144
- `POST /api/show` → `block_count` 32, `head_count_kv` `[0,0,0,4, …]` ×8, `key_length` 256

## Not done

The entry stays **shelved**. This corrects the analysis; it does not build option A, B or C.
Nothing in `src/` changed — the shipped default is still `num_ctx = 8192`.
