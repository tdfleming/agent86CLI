---
phase: quick-260813-atc
verified: 2026-08-13T00:00:00Z
status: passed
score: 10/10 must-haves verified
---

# Quick Task 260813-atc: Catalog-validated provider fallback for `/model <bare-ref>` Verification Report

**Task Goal:** Catalog-validated provider fallback for bare `/model` refs. When a typed ref like
`/model nemotron-3.5-lightning:latest` fails strict resolution in the TUI, look up the whole typed
string in the ACTIVE provider's model catalog; on a match retry as `<active-provider>:<typed-string>`
and echo a confirmation to the transcript; on a miss surface the existing strict error UNCHANGED.
TUI-only by design — the plain loop (`src/agent86/ui/repl.py`) and `run --json` keep strict parsing.

**Verified:** 2026-08-13
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Typed bare-ref (`nemotron-3.5-lightning:latest`) with ollama active + catalog hit switches model and echoes `resolved to ollama:nemotron-3.5-lightning:latest` | VERIFIED | `app.py:319` writes `f"[dim]resolved to {full}[/dim]"`; test `test_typed_bare_ref_warm_cache_hit_switches_and_echoes` PASSED |
| 2 | Typo not in catalog surfaces existing strict `Unknown provider ...` error, byte-unchanged, no fallback | VERIFIED | `_finish_model_fallback` (`app.py:306-311`) writes `strict_error` verbatim on `catalog_has_ref` miss; test `test_typed_bare_ref_warm_cache_typo_miss_keeps_strict_error` PASSED |
| 3 | `gpt-4o` while ollama active surfaces strict `must be 'provider:model'` error unchanged | VERIFIED | `_is_bare_ref_candidate` returns True for no-colon args (`app.py:250-253`), routed through same strict-error path; test `test_typed_colon_free_ref_miss_keeps_strict_error` PASSED |
| 4 | Already-valid ref (`anthropic:claude-opus-4-8`) switches on strict path, never consults catalog | VERIFIED | `_dispatch_model` returns early on provider-identity success (`app.py:271-275`) before any catalog code runs; test `test_typed_valid_ref_switches_without_consulting_catalog` PASSED |
| 5 | Known-provider ref failing for unrelated reason (missing key) surfaces strict error immediately, no catalog fetch | VERIFIED | `_is_bare_ref_candidate` returns False when `parsed.provider == active` or is configured/built-in (`app.py:254-259`); test `test_typed_known_provider_failure_skips_catalog_fetch` PASSED |
| 6 | Cold catalog cache resolves after `CatalogReady` arrives without blocking UI | VERIFIED | `_dispatch_model` queues to `_pending_model` + `_ensure_catalog_fetch` on cold cache (`app.py:285-288`); `on_catalog_ready` `model_fallback` branch drains it (`app.py:787-807`); test `test_typed_bare_ref_cold_cache_resolves_after_catalog_ready` PASSED |
| 7 | Pending entry validated only against the provider active at its own dispatch time, even across an intervening provider switch | VERIFIED | `_pending_model` is a list of `(arg, strict_error, provider)` triples with per-entry captured provider (`app.py:127-132`); `on_catalog_ready` filters by `provider == message.provider` and re-queues stranded entries (`app.py:796-801`); test `test_cross_provider_stranding_validates_against_own_captured_provider` PASSED |
| 8 | Overlapping bad-ref dispatches each produce exactly one visible outcome; exactly one fetch per provider | VERIFIED | `_ensure_catalog_fetch` gated on `_model_fetch_inflight` set, not queue length (`app.py:290-300`); test `test_overlapping_dispatches_same_provider_each_get_one_outcome` PASSED |
| 9 | Failed/empty catalog fetch falls through to strict error, never silent retry/drop | VERIFIED | `catalog_has_ref` returns False on empty entries (`model_picker.py:68`), driving `_finish_model_fallback`'s strict-error branch; test `test_typed_bare_ref_cold_cache_fetch_fails_falls_through` PASSED |
| 10 | `handle_command` and the plain loop keep strict `ModelRef` parsing — fallback is TUI-app-layer only | VERIFIED | `git diff` on `src/agent86/tui/commands.py` and `src/agent86/ui/repl.py` against pre-task commit `816b7f4` is EMPTY; `test_model_command_bare_ref_stays_strict_no_fallback` PASSED |

**Score:** 10/10 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/agent86/tui/screens/model_picker.py` | Pure `catalog_has_ref(ref, entries)` alongside `prefix_catalog_refs` | VERIFIED | Present at line 55-68, exported in `__all__` (line 127); `prefix_catalog_refs`/`model_choices`/`ModelPickerModal` diff shows only the added function + `__all__` line |
| `src/agent86/tui/app.py` | `_dispatch_model` / `_is_bare_ref_candidate` / `_finish_model_fallback` / `_provider_key`, provider-tagged `_pending_model` queue + `_model_fetch_inflight` set, `model_fallback` purpose | VERIFIED | All present, exact shapes confirmed by direct read (lines 127-135, 240-323, 398-401, 787-807) |
| `tests/tui/test_app.py` | Pilot regression tests for the 9 documented scenarios | VERIFIED | All 10 new tests present and passing (`grep` + direct pytest run) |
| `tests/tui/test_commands.py` | Strict-parsing pin | VERIFIED | `test_model_command_bare_ref_stays_strict_no_fallback` present (line 228), passing |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `_dispatch_line` | `_dispatch_model` | `entry.name == '/model' and arg` interception | WIRED | `app.py:222-224`, confirmed before `handle_command(self.repl, line)` fallthrough |
| `_dispatch_model` | `handle_command` | strict attempt first, provider-identity comparison | WIRED | `app.py:268-275`, identity check `self.repl.harness.provider is not before` |
| `_dispatch_model` | `_is_bare_ref_candidate` | gate before catalog branch | WIRED | `app.py:277`, called and its False return short-circuits to strict-error write with no catalog code reached |
| `_dispatch_model` | `_request_catalog` (via `_ensure_catalog_fetch`) | `purpose='model_fallback'`, gated by `_model_fetch_inflight` | WIRED | `app.py:290-300` |
| `on_catalog_ready` | `_finish_model_fallback` | `purpose == "model_fallback"` branch, placed BEFORE `CatalogPickerModal` fallthrough | WIRED | `app.py:787` branch precedes the `push_screen(CatalogPickerModal(...))` fallthrough at `app.py:808` |
| `_finish_model_fallback` | `catalog_has_ref` | catalog vouches before retry | WIRED | `app.py:306` |

### Checker-Mandated Design Points (explicit re-check per verification emphasis)

| Point | Status | Evidence |
|-------|--------|----------|
| `_pending_model` is a per-entry-captured-provider 3-tuple list, not a single slot | VERIFIED | `self._pending_model: list[tuple[str, Any, str]] = []` (`app.py:132`); appended as `(arg, result.render, provider)` (`app.py:287`); drained/filtered by per-entry `provider` in `on_catalog_ready` (`app.py:796-801`) |
| Catalog fetches gated by per-provider `_model_fetch_inflight` set, not queue length | VERIFIED | `_ensure_catalog_fetch` checks `if provider in self._model_fetch_inflight: return` (`app.py:297-298`) — queue length never consulted |
| `_is_bare_ref_candidate` failure-shape gate exists and is consulted before the catalog branch | VERIFIED | `app.py:240-259` (definition), `app.py:277` (call site, gates entry to catalog-cache lookup at line 281) |

### Protected-File Byte-Unchanged Check

Diffed against pre-task commit `816b7f4` (parent of first task commit `659bad3`):

| File | `git diff 816b7f4 HEAD` | Status |
|------|--------------------------|--------|
| `src/agent86/ui/repl.py` | empty | VERIFIED unchanged |
| `src/agent86/types.py` | empty | VERIFIED unchanged |
| `src/agent86/cognitive/catalog.py` | empty | VERIFIED unchanged |
| `src/agent86/tui/commands.py` | empty | VERIFIED unchanged |

### Locked Decision Check (catalog MISS → strict error unchanged, no fuzzy matching)

`catalog_has_ref` (`model_picker.py:68`): `return any(entry_ref == ref for entry_ref, _label in entries or [])` — exact equality only, no `startswith`, no normalization, no case-folding. `_finish_model_fallback` writes `strict_error` verbatim on a miss (`app.py:309-311`) and never attempts a second retry or best-effort match. VERIFIED.

### `_BUILTIN_PROVIDERS` Mirror Check

`app.py:70`: `_BUILTIN_PROVIDERS = frozenset({"anthropic", "openai", "openai-compatible", "ollama", "llamacpp"})`.

`cognitive/base.py::_build_provider` dispatch chain (lines 77-108) resolves exactly: `anthropic`, `ollama`, `openai`/`openai-compatible`, `llamacpp`, then falls through to a `base_url`-gated OpenAI-compatible branch (not a named provider) before raising `Unknown provider`. Named-provider set matches `_BUILTIN_PROVIDERS` exactly. VERIFIED — exact mirror, no drift.

### Behavioral Spot-Checks (full test suite, run directly)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite baseline | `python -m pytest -q` | `454 passed, 6 skipped, 1 failed` (the one failure is the documented out-of-scope `test_build_embedder_falls_back_without_torch`) | PASS — matches SUMMARY's claimed numbers exactly |
| TUI-specific suite | `pytest tests/tui/test_pickers.py tests/tui/test_app.py tests/tui/test_commands.py -q` | `65 passed` | PASS |
| New fallback tests only | `pytest tests/tui/test_app.py -k "typed_bare_ref or colon_free or typed_valid_ref or typed_known_provider or overlapping_dispatches or cross_provider_stranding"` | `10 passed` | PASS |
| Lazy-import regression | `pytest tests/tui/test_lazy_import.py -q` | `2 passed` | PASS |
| Ruff on touched files | `ruff check src/agent86/tui/app.py src/agent86/tui/messages.py src/agent86/tui/screens/model_picker.py tests/tui/test_app.py tests/tui/test_pickers.py tests/tui/test_commands.py` | Exactly 4 errors: E501 `app.py:674`, E501 `app.py:700`, I001 + E501 `test_app.py` header | PASS — matches the 4 pre-documented pre-existing errors (line numbers shifted from `:560`/`:586` due to inserted code, confirmed by reading the surrounding lines — they are the same two pre-existing long comment/constructor lines, not new) |

### Requirements Coverage

Quick task; `requirements: [QUICK-260813-atc]` is a self-referential ID for this ad-hoc task and has no separate `.planning/REQUIREMENTS.md` entry to cross-reference (expected for quick tasks). No orphaned requirements.

### Anti-Patterns Found

None. `git diff 816b7f4 HEAD` on the three source files (`app.py`, `screens/model_picker.py`, `messages.py`) was scanned for TODO/FIXME/XXX/HACK/placeholder/"not implemented" markers — no matches.

### Human Verification Required

None. All must-haves are verifiable via static code inspection, git diff, and automated test execution; the task ships with a comprehensive Pilot-based regression suite that already exercises the actual TUI behavior end-to-end (warm/cold cache, overlapping dispatch, cross-provider stranding), so no additional manual UI testing is needed to confirm goal achievement.

### Gaps Summary

None. All 10 observable truths verified, all artifacts exist/substantive/wired, all key links wired, both checker-mandated design points (per-entry `_pending_model` triples, inflight-set-gated fetches) and the failure-shape gate are present and consulted exactly as specified, the four protected files are byte-unchanged since the pre-task commit, the locked catalog-miss-surfaces-strict-error decision holds with exact-match-only comparison, `_BUILTIN_PROVIDERS` is an exact mirror of `_build_provider`'s dispatch chain, and the full test suite reproduces the SUMMARY's claimed `454 passed, 6 skipped, 1 failed` with the one failure being the documented out-of-scope environment issue.

---

*Verified: 2026-08-13*
*Verifier: Claude (gsd-verifier)*
