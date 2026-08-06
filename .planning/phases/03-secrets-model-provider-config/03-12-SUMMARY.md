---
phase: 03-secrets-model-provider-config
plan: 12
subsystem: cognitive
tags: [anthropic, openai, sampling-params, capability-gating, uat-gap-closure]

# Dependency graph
requires:
  - phase: 03-secrets-model-provider-config
    provides: "AnthropicProvider/OpenAIProvider streaming implementations and the /config model default of anthropic:claude-opus-5 (03-09)"
provides:
  - "src/agent86/cognitive/capabilities.py — single per-model capability seam (SAMPLING_PARAMS, supports_sampling_params, apply_sampling_params, mark_sampling_unsupported, is_sampling_rejection, normalize_model)"
  - "AnthropicProvider.stream gates temperature/top_p/top_k by model and self-corrects (learns + retries once) on a real API rejection"
  - "OpenAIProvider.stream routed through the same seam, behaviour-identical for OpenAI/Groq/OpenRouter today"
affects: [cognitive, model-provider-config, uat]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Capability seam module (stdlib-only, no agent86 imports) queried by every provider before building request kwargs — mirrors pricing.py's table-driven, conservative-default shape"
    - "Session-scoped learned set + one-shot retry for self-correcting against models released after a hardcoded family list was written"

key-files:
  created:
    - src/agent86/cognitive/capabilities.py
    - tests/unit/test_capabilities.py
    - tests/unit/test_sampling_params.py
  modified:
    - src/agent86/cognitive/anthropic_provider.py
    - src/agent86/cognitive/openai_provider.py

key-decisions:
  - "Gate is on the model, never on the value — CompletionRequest.temperature defaults to 0.0, a real value that must still be sent everywhere it's legal; only supports_sampling_params(model) decides omission."
  - "Self-correction only fires before any text has been emitted on the current attempt, so a rejection mid-stream (after partial output) still surfaces as a ProviderError rather than silently retrying and duplicating output."
  - "OpenAI-compatible path routed through the identical apply_sampling_params seam rather than a parallel gate, so a gateway (e.g. OpenRouter) proxying an Anthropic model through an OpenAI-compatible endpoint gets correct behaviour for free."

requirements-completed: [MODEL-01]

# Metrics
duration: 6min
completed: 2026-08-06
---

# Phase 03 Plan 12: Anthropic sampling-params gating (UAT gap 5 closure) Summary

**Anthropic requests for Claude Opus 5, Opus 4.8, Opus 4.7, Sonnet 5, and Fable 5 no longer send `temperature`/`top_p`/`top_k` (which those models reject with HTTP 400), via a shared `capabilities.py` seam that both providers query and that self-corrects for any future model the API itself rejects.**

## Performance

- **Duration:** 6 min (22:54–23:00 local time across three task commits)
- **Started:** 2026-08-05T22:53:xx-04:00 (approx, first commit 22:54:28)
- **Completed:** 2026-08-06T02:57:12Z (SUMMARY authored)
- **Tasks:** 3/3 completed
- **Files modified:** 5 (2 created source, 1 created + used by 2 tasks test file, 2 modified providers)

## Accomplishments
- Closed UAT gap 5 (blocker): a turn against `anthropic:claude-opus-5` — the model `/config model` now selects by default — completes instead of returning `400 temperature is deprecated this model`.
- Introduced one seam (`capabilities.py`) that both `AnthropicProvider` and `OpenAIProvider` query, so the fix (and any future capability fact) lives in exactly one place.
- Added a self-correcting fallback: a model released after `_NO_SAMPLING_FAMILIES` was written learns from its own first rejection and never fails on that parameter again for the session.
- OpenAI/Groq/OpenRouter requests remain byte-identical in practice (no OpenAI-family model is in the removed-parameter list); the existing `test_openai_provider.py` module was left completely untouched and still passes.

## Task Commits

1. **Task 1: Create the capabilities seam** - `622ac9d` (feat) — `capabilities.py` + `test_capabilities.py`, 26 tests
2. **Task 2: Gate Anthropic kwargs and self-correct on a real rejection** - `9785920` (feat) — `anthropic_provider.py` rewrite + `test_sampling_params.py` (Anthropic tests), 11 tests
3. **Task 3: Route the OpenAI-compatible path through the same seam** - `c35e3f3` (feat) — `openai_provider.py` payload change + remaining `test_sampling_params.py` (OpenAI tests), 6 tests

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/agent86/cognitive/capabilities.py` - the capability seam: `SAMPLING_PARAMS`, `_NO_SAMPLING_FAMILIES` (prefix-matched, case-insensitive), a session-scoped `_LEARNED_NO_SAMPLING` set, `supports_sampling_params`, `mark_sampling_unsupported`, `is_sampling_rejection`, `apply_sampling_params`, `normalize_model`
- `src/agent86/cognitive/anthropic_provider.py` - `stream()` rewritten: builds `base_kwargs` without sampling params, applies them via `apply_sampling_params(dict(base_kwargs), self.model, temperature=request.temperature)`, and wraps the actual API call in a two-attempt loop that retries once (with `base_kwargs`, no sampling params) if the first attempt's `APIError` text is a sampling-param rejection and no text was emitted yet. `complete()` remains inherited from `ModelProvider`, unchanged.
- `src/agent86/cognitive/openai_provider.py` - `payload` dict literal no longer includes `"temperature": request.temperature`; `apply_sampling_params(payload, self.model, temperature=request.temperature)` is called immediately after construction. All other payload keys (`max_tokens`, `tools`, `tool_choice`, headers, SSE accumulation) unchanged.
- `tests/unit/test_capabilities.py` - 26 tests: the full removed/unaffected model matrix, `apply_sampling_params` value/None semantics, learned-set behaviour and normalization, `is_sampling_rejection` message matching.
- `tests/unit/test_sampling_params.py` - 17 tests: Anthropic gating for all 5 removed families, unaffected model keeps temperature, `complete()` inherits gating, self-correcting retry (2 calls, second omits params, learned set populated), unrelated error raises without retry (1 call), `max_tokens`/`system`/`tools` unchanged; OpenAI-compatible payload keeps temperature for `gpt-4o`, omits it for `claude-opus-5` routed through the same endpoint, and all other payload keys unchanged.

## Decisions Made
- Gate is strictly on the model id, never on the `temperature` value, because `CompletionRequest.temperature` defaults to `0.0` — a real, legal value for every provider except the five removed-parameter families.
- The one-shot retry only triggers if no text has been emitted yet on the failing attempt, so a mid-stream rejection (unlikely, but possible with a provider that streams partial output before erroring) surfaces as a normal `ProviderError` rather than silently retrying and risking duplicated output.
- Routed `OpenAIProvider` through the identical `apply_sampling_params` call rather than adding a parallel gate, since the interfaces file explicitly calls out this module as "correct for OpenAI/Groq/OpenRouter TODAY and must stay behaviourally identical" — a gateway proxying Anthropic through an OpenAI-compatible endpoint now gets the correct omission automatically.

## Deviations from Plan

None - plan executed as written for all three tasks. One informational note below (not a deviation, no fix applied):

- **Out-of-scope observation, not fixed:** `src/agent86/cognitive/ollama_provider.py` (not in this plan's `files_modified`) also builds `options = {"temperature": request.temperature}` unconditionally. This is not a bug: Ollama serves only local model families (e.g. `llama3.1:8b`), none of which are in `_NO_SAMPLING_FAMILIES`, so no request currently 400s. It is flagged here only because the plan's automated verification bullet `grep -rn '"temperature": request.temperature' src/` technically also matches this unrelated file; the plan's task list and interfaces section scoped the fix to `anthropic_provider.py` and `openai_provider.py` only, so per the deviation rules' scope boundary this was left untouched rather than auto-fixed.

## Self-Check: PASSED

All created/modified files confirmed present on disk; all three task commit hashes (622ac9d,
9785920, c35e3f3) confirmed present in `git log`. Full suite (`python -m pytest tests/ -q`)
confirmed green: 331 passed, 0 failed.
