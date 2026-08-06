---
phase: 03-secrets-model-provider-config
plan: 13
subsystem: cognitive
tags: [anthropic, provider-error, sdk-guard, uat-gap-closure]

# Dependency graph
requires:
  - phase: 03-secrets-model-provider-config
    provides: "AnthropicProvider construction path and run_repl's `except ProviderError` fail-soft branch (03-11), the capability seam and default model:anthropic:claude-opus-5 (03-12)"
provides:
  - "AnthropicProvider.__init__ SDK-version guard: raises ProviderError before anthropic.Anthropic(**kwargs) is ever called when the installed SDK is below the declared anthropic>=0.40 floor"
  - "tests/unit/test_anthropic_sdk_guard.py — 10 regression tests proving both the guard itself and the full run_repl fail-soft path"
affects: [cognitive, model-provider-config, uat]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Version-floor guard mirroring the existing missing-package ImportError path: same ProviderError type, same 'name the exact fix' tone, raised before any SDK object is constructed"
    - "Tolerant version parser (_version_tuple) that stops at the first non-numeric character per dot-segment, so pre-release suffixes (e.g. 1.0.0b1) never block startup"

key-files:
  created:
    - tests/unit/test_anthropic_sdk_guard.py
  modified:
    - src/agent86/cognitive/anthropic_provider.py

key-decisions:
  - "Guard raises ProviderError, never TypeError/RuntimeError, so it passes through both plan 03-11's catch-all in provider_for_ref (unchanged) and run_repl's existing `except ProviderError` branch (unchanged) with its wording intact — no changes needed to base.py or repl.py."
  - "An empty/unparseable version tuple is explicitly never compared as less than the floor — an unknown version must not block a working install (Test 4/5 in the plan)."
  - "pyproject.toml's anthropic>=0.40 floor was left untouched (verified via `git diff --stat`); this plan is code-level hardening only, per the plan's explicit instruction not to treat the environment fix (already applied by the user, anthropic 0.120.2 installed) as a deliverable."

requirements-completed: [MODEL-01]

# Metrics
duration: 12min
completed: 2026-08-06
---

# Phase 03 Plan 13: Anthropic SDK-version guard (UAT gap 3 closure) Summary

**`AnthropicProvider.__init__` now detects a stale `anthropic` SDK (< 0.40) and raises a `ProviderError` naming the version found, the version needed, and the exact `pip install -U "anthropic>=0.40"` upgrade command — before `anthropic.Anthropic(**kwargs)` is ever called — so `run_repl` prints "Cannot start:" instead of an opaque `TypeError` traceback from inside httpx.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-08-06
- **Tasks:** 2/2 completed
- **Files modified:** 2 (1 modified source, 1 created test file)

## Accomplishments

- Closed UAT gap 3 (blocker): an `anthropic` SDK below the declared `anthropic>=0.40` floor (which passes `proxies=` to `httpx.Client`, removed in httpx 0.28) now fails with a one-line, actionable `ProviderError` instead of an opaque `Client.__init__() got an unexpected keyword argument 'proxies'` `TypeError` surfacing from inside httpx.
- Guard mirrors the existing missing-package (`ImportError`) path exactly in tone, formatting, and exception type — one consistent "here's what's wrong, here's the fix" experience for both failure modes.
- Proved end-to-end through `run_repl`: both an opaque `TypeError` (simulating the real httpx incompatibility) and a genuine stale-SDK `ProviderError` produce "Cannot start:" with no `Traceback (most recent call last)` anywhere in the output, and the resolved API key never appears in that output either (cross-checked against plan 03-11's redaction).
- No dependency pin or `pip install` was part of this deliverable — the dev environment's `anthropic` is already 0.120.2, well above the floor; this plan is purely code-level hardening for the next person's stale/shared environment.

## Task Commits

1. **Task 1: Add an SDK-version guard that names the fix** - `61ea58a` (test) — `anthropic_provider.py` guard + `_version_tuple` helper, `test_anthropic_sdk_guard.py` created with 6 tests
2. **Task 2: Prove startup fails soft instead of dumping a traceback** - `1b4fde1` (test) — 4 more tests appended to the same file, driving the guard through `run_repl` end to end

## Files Created/Modified

- `src/agent86/cognitive/anthropic_provider.py` — added `_MIN_ANTHROPIC_VERSION = (0, 40)` and `_version_tuple(raw: str) -> tuple[int, ...]` (stops at the first non-numeric character per `.`-segment) near `_DEFAULT_MAX_TOKENS`; `AnthropicProvider.__init__` now checks `getattr(anthropic, "__version__", None)` immediately after the `try: import anthropic / except ImportError` block and before `key_env = ...`, raising `ProviderError` with the found/needed versions, the upgrade command, and a note about shared-environment stale pins (e.g. `anthropic-tools`) if the parsed version is below the floor. Nothing else in `__init__` changed.
- `tests/unit/test_anthropic_sdk_guard.py` (new, 10 tests) — Task 1 (6 tests): stale version raises `ProviderError` with the exact wording required (version found, version needed, upgrade command); the guard fires before `anthropic.Anthropic(...)` is ever constructed (a recording stub records zero calls); the real installed version (0.120.2) constructs normally; a missing `__version__` attribute does not block startup; a non-numeric pre-release suffix (`1.0.0b1`) is tolerated; the existing missing-package `ImportError` path is unchanged byte-for-byte. Task 2 (4 tests): `run_repl` with an `AnthropicProvider.__init__` monkeypatched to raise the real opaque `TypeError` returns normally and prints "Cannot start:" with the resolved key never appearing in output; the same output contains no `Traceback (most recent call last)`; with `anthropic.__version__` forced to `0.25.9`, `run_repl` prints the exact `pip install -U "anthropic>=0.40"` command; and a combined assertion confirms no traceback and no key leak on that same path.

## Decisions Made

- The guard raises `ProviderError` (never `TypeError`/`RuntimeError`) specifically so it passes through plan 03-11's `_build_provider`/`provider_for_ref` catch-all (which re-raises `ProviderError` untouched) and `run_repl`'s existing `except ProviderError` branch with its wording intact — zero changes needed to `cognitive/base.py` or `ui/repl.py`.
- `found and found < _MIN_ANTHROPIC_VERSION` — an empty tuple (from an unparseable version string) is explicitly excluded from the comparison, so an unknown/future version format never blocks a working install.
- Left `pyproject.toml` completely untouched; verified via `git diff --stat pyproject.toml` (empty) that this plan changed no dependency pin, matching the plan's explicit instruction that the environment fix (already applied out-of-band) is not this plan's deliverable.

## Deviations from Plan

None — plan executed exactly as written for both tasks. One informational note (not a deviation, no fix needed): a full-suite run mid-session showed one unrelated TUI test (`test_switch_is_immediate_persist_is_separate`) fail once, then pass in isolation and in two subsequent full-suite reruns — a pre-existing flake, not caused by this plan's changes (confirmed not touching any file this plan modified).

## Self-Check: PASSED

Confirmed on disk: `src/agent86/cognitive/anthropic_provider.py` contains `_MIN_ANTHROPIC_VERSION` (3 occurrences) and `_version_tuple` (2 occurrences); `tests/unit/test_anthropic_sdk_guard.py` exists with 10 tests. Both commit hashes (`61ea58a`, `1b4fde1`) confirmed present in `git log --oneline`. Full suite (`python -m pytest tests/ -q`) confirmed green across two consecutive runs: 341 passed, 0 failed (up from 331 before this plan). `python -c "import anthropic; print(anthropic.__version__)"` reports `0.120.2` in the dev environment, recorded here as context only.
