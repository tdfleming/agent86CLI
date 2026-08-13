---
quick_id: 260813-adr
description: Make /model catalog picker insert the active provider prefix
completed: 2026-08-13
commits:
  - 2a63ada
  - dc160eb
files_modified:
  - src/agent86/tui/screens/model_picker.py
  - src/agent86/tui/app.py
  - tests/tui/test_pickers.py
  - tests/tui/test_app.py
---

# Quick Task 260813-adr: Make the `/model` catalog picker insert the active provider prefix — Summary

**One-liner:** Added a pure `prefix_catalog_refs(provider, entries)` helper (mirroring
`CatalogPickerModal._catalog_ref`) and wired it into `_open_model_picker` so both `/model` catalog
paths — session-cache hit and fresh fetch — send full `provider:model` refs into `model_choices`,
fixing broken dispatch for every provider, not just the reported Ollama case.

## What Was Wrong

`/model` opens `ModelPickerModal`; selecting a live-catalog entry dispatched a broken ref.
`fetch_catalog` (`cognitive/catalog.py`) returns **bare** model ids by documented contract — the
caller is supposed to prefix `provider:`. The `/config model` path (`CatalogPickerModal._catalog_ref`)
already did this correctly, but `Agent86App._open_model_picker` passed catalog entries straight
into `model_choices` unprefixed, so `_on_model_picked` dispatched `/model <bare-id>`.

`ModelRef.parse` splits on the **first** colon via `partition(":")`. For an Ollama id that already
contains a colon (`nemotron-3.5-lightning:latest`), the bare dispatch produced provider
`nemotron-3.5-lightning`, model `latest` — the exact "Unknown provider" error the user reported.
For colon-free ids (openai `gpt-4o`), the bare dispatch failed `ModelRef.parse` outright ("must be
'provider:model'"). The catalog section of the `/model` picker was broken for every provider.

## Fix

**Task 1** (`2a63ada`): Added `prefix_catalog_refs(provider, entries)` as a module-level pure
function in `model_picker.py`, exported via `__all__`. For each `(ref, label)` pair it prefixes the
ref with `f"{provider}:"` unless it already carries that **exact** prefix (an exact-prefix match
only — "contains a colon" is explicitly rejected as an already-prefixed test, since a bare Ollama
id legitimately contains one; that ambiguity was the bug). The label is prefixed alongside the ref
only when the provider supplied no distinct display name (`label == ref`), so a real
provider-supplied name (e.g. OpenRouter's `data[].name`) survives untouched. Returns a new list —
never mutates the input, since the caller's list may be `Agent86App._catalog_cache`.

`app.py`'s `_open_model_picker` now resolves `self.repl.harness.provider.name` and calls
`prefix_catalog_refs(provider, extra)` **before** passing `extra` into `model_choices`, so
`model_choices`'s role-slot dedupe compares full refs against full refs (role slots — `model.default`,
`route.cheap`, `route.frontier` — are already full refs and pass through untouched; only the
catalog `extra` list is prefixed). This single change point covers both call sites: the
session-cache hit and the fresh-fetch path via `on_catalog_ready(purpose="model_picker")`.

`src/agent86/cognitive/catalog.py` was left untouched (verified via `git diff --stat`), so
`fetch_catalog`'s bare-id contract — and the `/config model` `CatalogPickerModal` path that already
prefixes correctly — keep working unchanged.

**Task 2** (`dc160eb`): Added 5 pure tests to `tests/tui/test_pickers.py` (colon-bearing Ollama id
prefix, `ModelRef.parse` round trip on the prefixed ref, colon-free id prefix + parse, no-double-
prefix guard for both an already-prefixed ref and a provider-supplied display label, and a
`model_choices` role-slot dedupe test proving a catalog entry duplicating a role slot is still
deduped away after prefixing) plus one end-to-end Pilot test in `tests/tui/test_app.py`
(`test_model_picker_prefixes_cached_ollama_catalog_entry`) reproducing the exact reported bug:
seeds `app._catalog_cache["ollama"]` with the bare `nemotron-3.5-lightning:latest` entry, sets the
active provider to `"ollama"`, opens `/model`, and asserts `"ollama:nemotron-3.5-lightning:latest"`
is among the modal's option values while the bare id is not.

## Reproduction Proof (RED before GREEN)

Per plan instruction, confirmed the new tests fail against the pre-fix source before finalizing:
temporarily swapped `model_picker.py`/`app.py` back to their pre-Task-1 content (commit `48a671b`)
and reran.

```
python -m pytest tests/tui/test_pickers.py tests/tui/test_app.py -q
```

- `tests/tui/test_pickers.py`: **collection ImportError** — `cannot import name 'prefix_catalog_refs'
  from 'agent86.tui.screens.model_picker'` (function did not exist yet).
- `tests/tui/test_app.py::test_model_picker_prefixes_cached_ollama_catalog_entry`: **FAILED** —
  `AssertionError: assert 'ollama:nemotron-3.5-lightning:latest' in
  ['ollama:qwen3.5:latest', 'ollama:llama3.1', 'anthropic:claude-opus-4-8',
  'nemotron-3.5-lightning:latest']` — the bare id was present, the prefixed one was not.

Source files were then restored to the fixed content and both suites passed.

## Verification

```
python -m pytest tests/tui/test_pickers.py tests/tui/test_app.py -q   # 27 passed
python -m pytest tests/tui/ -q                                         # 135 passed
python -m pytest -q                                                    # 436 passed, 6 skipped, 1 failed
```

The one full-suite failure is the pre-existing, environment-dependent
`tests/unit/test_memory.py::test_build_embedder_falls_back_without_torch` (sentence-transformers IS
installed in this dev box, so the test's "torch isn't installed" premise doesn't hold) — unrelated
to this task, not fixed, not a regression (confirmed pre-existing per the task's environment notes).

One full-`tests/tui/` run during the RED/GREEN comparison also hit the documented,
test-order-dependent `CatalogPickerModal`/`#catalog-filter` `NoMatches` flake
(`tests/tui/test_app.py::test_catalog_failure_yields_empty_entries_with_error`, logged in
`.planning/phases/04-mcp-config-ui/deferred-items.md` since plans 04-02/04-05) — cleared on
immediate rerun; unrelated to `model_picker.py`/`app.py`'s catalog-picker-adjacent-but-distinct
code path this task touches.

## Success Criteria

- [x] Selecting an Ollama catalog entry via `/model` dispatches
      `/model ollama:nemotron-3.5-lightning:latest`, not the bare id.
- [x] `ModelRef.parse("ollama:nemotron-3.5-lightning:latest")` → provider `ollama`, model
      `nemotron-3.5-lightning:latest`.
- [x] A colon-free catalog id (`gpt-4o`) becomes `openai:gpt-4o` and parses.
- [x] Config role-slot refs are byte-identical in the picker — never double-prefixed — and a
      catalog entry duplicating a role slot is still deduped away.
- [x] `src/agent86/cognitive/catalog.py` is unmodified.
- [x] Full suite passes except the known pre-existing, unrelated
      `test_build_embedder_falls_back_without_torch` failure.

## Deviations from Plan

None — plan executed exactly as written. Both tasks completed per spec; the two full-suite
observations above (pre-existing torch-fallback failure, pre-existing `#catalog-filter` flake) were
already known and explicitly out of scope per the plan's own success-criteria wording and
`deferred-items.md`.

## Self-Check

- `src/agent86/tui/screens/model_picker.py` — FOUND, contains `prefix_catalog_refs`, exported in
  `__all__`.
- `src/agent86/tui/app.py` — FOUND, `_open_model_picker` imports and calls `prefix_catalog_refs`.
- `tests/tui/test_pickers.py` — FOUND, contains 5 new `prefix_catalog_refs`/`model_choices` tests.
- `tests/tui/test_app.py` — FOUND, contains
  `test_model_picker_prefixes_cached_ollama_catalog_entry`.
- Commit `2a63ada` — FOUND in `git log`.
- Commit `dc160eb` — FOUND in `git log`.

## Self-Check: PASSED
