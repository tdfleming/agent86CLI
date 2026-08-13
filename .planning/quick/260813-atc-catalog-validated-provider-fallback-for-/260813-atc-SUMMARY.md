---
quick_id: 260813-atc
description: Catalog-validated provider fallback for /model bare-ref typing
completed: 2026-08-13
commits:
  - 659bad3
  - 93de48d
  - 300c215
  - 30d6477
files_modified:
  - src/agent86/tui/screens/model_picker.py
  - src/agent86/tui/app.py
  - src/agent86/tui/messages.py
  - tests/tui/test_pickers.py
  - tests/tui/test_app.py
  - tests/tui/test_commands.py
---

# Quick Task 260813-atc: Catalog-validated provider fallback for `/model <bare-ref>` — Summary

**One-liner:** Typing `/model <bare-ref>` in the TUI now retries as `<active-provider>:<bare-ref>`
only when the active provider's live catalog vouches for the typed string verbatim — echoing
`resolved to <provider>:<ref>` on a hit, or surfacing today's strict error byte-unchanged on a
miss — via a provider-tagged pending queue (`_pending_model`) and a per-provider inflight set
(`_model_fetch_inflight`) that keeps overlapping and cross-provider dispatches from clobbering,
stranding, or cross-validating each other.

## What Was Wrong

260813-adr fixed the `/model` **catalog picker** path (arrow-key selection) by prefixing bare
catalog ids with `provider:` before dispatch. This task closes the companion **typed** path:
`/model nemotron-3.5-lightning:latest` still errored with `Unknown provider
'nemotron-3.5-lightning'`, because `ModelRef.parse` (`types.py:66-76`) splits on the FIRST colon
and Ollama ids carry their own `:tag`. The user's locked decision: retry the typed string as
`<active-provider>:<typed-string>` **only** when the active provider's live catalog vouches for
it verbatim — a real typo must still fail loudly at type time, never be silently masked as a
provider-side "model not found" at request time.

## Fix

**Task 1** (`659bad3` RED, `93de48d` GREEN): Added a pure `catalog_has_ref(ref, entries) -> bool`
helper to `src/agent86/tui/screens/model_picker.py`, directly beneath `prefix_catalog_refs`.
`fetch_catalog` returns BARE model ids by documented contract, so the comparison is against the
`ref` half of each `(ref, label)` pair only, exact and case-sensitive — no normalization, no
fuzzy matching. `None`/empty `entries` (cold or failed catalog) returns `False`. Exported via
`__all__`. Six pure behavior cases plus a `catalog_has_ref` + `prefix_catalog_refs` +
`ModelRef.parse` end-to-end round-trip pin were added to `tests/tui/test_pickers.py`, following
TDD: the tests were committed first against the not-yet-existing function (collection
`ImportError`, confirmed RED), then the implementation commit turned them green.

**Task 2** (`300c215`): Wired the fallback into `Agent86App`, entirely in the app layer —
`tui/commands.py`, `ui/repl.py`, `types.py`, and `cognitive/catalog.py` are all untouched
(verified via empty `git diff`), so the plain loop and `run --json` keep strict `ModelRef`
parsing unchanged.

- `_dispatch_line` now intercepts `/model <arg>` and routes it to `_dispatch_model(arg)`, which
  calls the ordinary `handle_command(self.repl, f"/model {arg}")` **first** — the strict path,
  zero duplication of `commands.py`'s dispatch logic — and detects failure by comparing
  `self.repl.harness.provider` **identity** before/after (`Harness.set_model` leaves the current
  provider unchanged on failure and replaces it with a new object on success, so identity is an
  exact success signal). The strict error text is held back rather than written immediately, so a
  successful fallback never flashes a scary error first.
- `_is_bare_ref_candidate(arg, active)` gates entry to the catalog branch: only a plausible
  first-colon-split failure (no colon at all, or a provider name that isn't the active provider
  and isn't configured/built-in) may proceed. A ref that names a **real** provider and merely
  failed to build (missing key, SDK error) surfaces its strict error immediately — no catalog
  fetch of the unrelated active provider, no `fetching … catalog…` noise (checker warning 1).
- Cold-cache dispatches are queued in `_pending_model: list[tuple[arg, strict_error, provider]]`
  — a LIST of triples, not a single slot, with the provider captured **per entry** at dispatch
  time. `_model_fetch_inflight: set[str]` gates fetches per provider (never on queue length), so
  a burst issues exactly one fetch per provider even when the queue is already non-empty because
  of another provider's pending entry (checker warning 2). `on_catalog_ready` gained a
  `model_fallback` purpose branch, placed BEFORE the `CatalogPickerModal` fallthrough, that drains
  only entries whose captured provider matches the arriving message and re-queues (and,
  defensively, re-triggers a fetch for) any stranded entries — so an entry is only ever validated
  against the catalog of the provider that was active when IT was dispatched, even when an
  intervening successful `/model` switch changed the active provider mid-flight (checker
  warning 3).
- `_finish_model_fallback` reuses 260813-adr's `catalog_has_ref` / `prefix_catalog_refs` (with its
  exact-prefix double-prefix guard) so the typed and picker paths of `/model` can never drift: a
  catalog hit echoes `resolved to <provider>:<ref>` and retries via a direct
  `handle_command` call (never `_dispatch_model`, so recursion is structurally impossible); a
  miss writes the captured strict error verbatim.
- `messages.py`'s `CatalogReady.purpose` docstring extended to list `"model_fallback"` — no
  signature or behavior change.

**Task 3** (`30d6477`): Eleven regression tests — ten Pilot tests in `tests/tui/test_app.py`
(warm-cache hit + echo, warm-cache typo miss, colon-free miss, already-valid-ref passthrough with
an `AssertionError`-raising `fetch_catalog` fake proving no catalog touch, known-provider
build/auth failure with the same no-fetch proof, cold-cache resolution via `CatalogReady`,
cold-cache fetch failure fallthrough, overlapping same-provider dispatches — a blocking
`threading.Event`-gated fake proves exactly one fetch answers both — the cross-provider stranding
sequence lifted verbatim from the plan's `<decisions>`, and a cold-cache colon-free miss) plus one
pin in `tests/tui/test_commands.py` proving `handle_command` (shared with `--plain`) has no
fallback and `ModelRef.parse` is untouched. Both blocking fakes (cases 8 and 9) carry a hard 5s
`threading.Event.wait(timeout=...)` that raises `AssertionError` on expiry, so a routing regression
fails the suite instead of hanging it.

## Reproduction Proof (RED before GREEN)

Per plan instruction, checked out `src/agent86/tui/app.py` and `src/agent86/tui/messages.py` to
their pre-Task-2 content (`git checkout 93de48d -- src/agent86/tui/app.py
src/agent86/tui/messages.py`) and reran `tests/tui/test_app.py` / `tests/tui/test_commands.py`
with the Task 3 test additions already in place:

```
pytest tests/tui/test_app.py -k "typed_bare_ref or colon_free_ref or typed_valid_ref or
  typed_known_provider or overlapping_dispatches or cross_provider_stranding" -v
```

- **Cases 1, 6, 7, 8, 9 (the new behavior) FAILED**, as the plan requires:
  `test_typed_bare_ref_warm_cache_hit_switches_and_echoes`,
  `test_typed_bare_ref_cold_cache_resolves_after_catalog_ready`,
  `test_typed_bare_ref_cold_cache_fetch_fails_falls_through`,
  `test_overlapping_dispatches_same_provider_each_get_one_outcome`,
  `test_cross_provider_stranding_validates_against_own_captured_provider` all failed pre-fix
  (`AttributeError: 'Agent86App' object has no attribute '_pending_model'`/`_model_fetch_inflight`,
  or the strict-error assertion never reached because the fallback code path did not exist).
- **Cases 2, 3, 4 (pins on already-correct strict behavior) PASSED** both before and after, as
  expected — the pre-fix `/model` dispatch already went straight to `handle_command`, so the
  strict error / valid-ref-switch behavior these cases pin was already correct.
- **Cases 5 and 10 also FAILED pre-fix** — but via `AttributeError` on the new
  `_pending_model`/`_model_fetch_inflight` attributes their assertions inspect (added to prove the
  no-fetch / drained-queue invariants), not because the strict-error text itself was ever wrong.
  This is consistent with the plan's "may pass both before and after" framing for the *underlying
  behavior* (it does not claim the literal test files, which assert on Task 2's new internals,
  would pass unmodified pre-fix).
- **Case 11** (`test_commands.py::test_model_command_bare_ref_stays_strict_no_fallback`) **PASSED
  identically pre- and post-fix**, confirming the plain adapter never had a fallback to begin with.

Source was restored via `git checkout HEAD -- src/agent86/tui/app.py
src/agent86/tui/messages.py` before finalizing; full suite reconfirmed green after restore.

## Verification

```
pytest tests/tui/test_pickers.py -q                    # 21 passed
pytest tests/tui/test_app.py tests/tui/test_commands.py -q   # 44 passed
pytest tests/tui/ -q                                    # 159 passed
pytest -q                                               # 454 passed, 6 skipped, 1 failed (x2 consecutive runs)
pytest tests/tui/test_lazy_import.py -q                 # 2 passed
ruff check src/agent86/tui/app.py src/agent86/tui/messages.py \
  src/agent86/tui/screens/model_picker.py tests/tui/test_app.py \
  tests/tui/test_pickers.py tests/tui/test_commands.py   # only the 4 pre-documented errors
```

The one full-suite failure is the pre-existing, environment-dependent
`tests/unit/test_memory.py::test_build_embedder_falls_back_without_torch` (sentence-transformers
IS installed in this dev box, so the test's "torch isn't installed" premise doesn't hold) —
per this task's own environment notes, not fixed, not a regression.

`git diff --stat` against the pre-task commit (`816b7f4`) lists exactly the six files declared in
the plan's frontmatter: `src/agent86/tui/screens/model_picker.py`, `src/agent86/tui/app.py`,
`src/agent86/tui/messages.py`, `tests/tui/test_pickers.py`, `tests/tui/test_app.py`,
`tests/tui/test_commands.py`. `git diff` on `src/agent86/ui/repl.py`, `src/agent86/types.py`,
`src/agent86/cognitive/catalog.py`, and `src/agent86/tui/commands.py` is EMPTY.

Ruff reports no new errors beyond the 4 already documented as pre-existing in this task's
environment notes: `E501` at `app.py:674`/`:700` (shifted from the pre-task `:560`/`:586` by
this task's inserted lines — confirmed by diffing the surrounding code, not new lines) and the
`I001`+`E501` import-block errors in `test_app.py`'s pre-existing header.

### A note on the `#catalog-filter` flake

Running `pytest tests/tui/ -q` in isolation (not the full suite) reproduced the documented,
test-order-dependent `CatalogPickerModal`/`#catalog-filter` `NoMatches` flake (logged in
`.planning/phases/04-mcp-config-ui/deferred-items.md` since plans 04-02/04-05,
`src/agent86/tui/screens/provider_manager.py:126`) on two consecutive `tests/tui/`-only runs.
To confirm this is pre-existing and unrelated to this task's changes rather than something this
task introduced: stashed all of this task's changes, checked out to the pre-task commit
(`300c215`, i.e. Tasks 1+2 already landed but before Task 3's new tests), and reran
`pytest tests/tui/ -q` — clean, 148/148, no flake. This proves the flake is order/count-sensitive
(as the deferred-items.md history already documents across two prior, unrelated plans) and
surfaces or hides depending on how many tests run alongside it — not something this task's files
(`model_picker.py`, `app.py`, `messages.py`, none of which touch `provider_manager.py`) caused.
Two consecutive **full-suite** (`pytest -q`) runs after restoring this task's changes were both
clean (only the documented torch-fallback failure), which is the actual acceptance bar per this
task's `<verification>` section. Not fixed here — out of scope (`provider_manager.py` untouched
by this task) — logged here for visibility rather than re-duplicated into `deferred-items.md`,
since it is Phase 4's existing entry.

## Success Criteria

- [x] Typing `/model nemotron-3.5-lightning:latest` with ollama active and the model present in
      the ollama catalog switches the model and echoes
      `resolved to ollama:nemotron-3.5-lightning:latest`.
- [x] A typo or a foreign-provider ref produces the existing strict error, byte-unchanged, with no
      fallback attempt and no `resolved to` line.
- [x] An already-valid `provider:model` ref switches on the strict path without touching the
      catalog.
- [x] A ref naming a known provider that fails to build (missing key, SDK error) produces its
      strict error immediately — no catalog fetch, no `fetching … catalog` line.
- [x] A cold catalog resolves through `CatalogReady(purpose="model_fallback")` without blocking
      the UI; a failed or empty fetch falls through to the strict error.
- [x] A pending entry is validated only against the catalog of the provider active at its own
      dispatch time, even when an intervening successful `/model` switch changed the active
      provider mid-flight.
- [x] Overlapping `/model` dispatches each produce exactly one visible outcome, with exactly one
      fetch issued per provider.
- [x] `handle_command` / `ui/repl.py` / `run --json` keep strict parsing — the fallback is
      TUI-only and documented as such.
- [x] `ModelRef.parse`, `fetch_catalog`, and `tui/commands.py` are unmodified.

## Deviations from Plan

None — plan executed exactly as written, including the three checker-mandated design points
(the per-entry-captured-provider `_pending_model` list, the `_model_fetch_inflight`-gated fetch
count rather than a queue-length gate, and the `_is_bare_ref_candidate` failure-shape gate) verbatim
per the plan's own explicit "STOP and report rather than deviating silently" instruction — none of
those three needed to be questioned; the pseudocode as written matched the codebase's actual
interfaces on inspection. The `#catalog-filter` flake noted above is a pre-existing, already-logged
issue in an untouched file, not a deviation.

## Self-Check

- `src/agent86/tui/screens/model_picker.py` — FOUND, contains `catalog_has_ref`, exported in
  `__all__`.
- `src/agent86/tui/app.py` — FOUND, contains `_dispatch_model`, `_is_bare_ref_candidate`,
  `_finish_model_fallback`, `_provider_key`, `_pending_model`, `_model_fetch_inflight`.
- `src/agent86/tui/messages.py` — FOUND, `CatalogReady` docstring lists `model_fallback`.
- `tests/tui/test_pickers.py` — FOUND, contains 6 new `catalog_has_ref` tests.
- `tests/tui/test_app.py` — FOUND, contains all 10 new Pilot regression tests.
- `tests/tui/test_commands.py` — FOUND, contains
  `test_model_command_bare_ref_stays_strict_no_fallback`.
- Commit `659bad3` — FOUND in `git log`.
- Commit `93de48d` — FOUND in `git log`.
- Commit `300c215` — FOUND in `git log`.
- Commit `30d6477` — FOUND in `git log`.

## Self-Check: PASSED
