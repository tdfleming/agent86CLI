---
phase: 03-secrets-model-provider-config
plan: 09
subsystem: ui
tags: [textual, keyring, tomlkit, model-catalog, config-write-back]

# Dependency graph
requires:
  - phase: 03-secrets-model-provider-config
    provides: "agent86.secrets (03-02), agent86.config_writer (03-03), agent86.cognitive.catalog (03-04), /config model registry entry (03-05), KeyEntryModal/ConnectionTestModal (03-06), SaveDiffModal (03-07), ProviderManagerModal/CatalogPickerModal/provider_rows (03-08)"
provides:
  - "The complete /config model chain: provider list -> key entry (when needed) -> live catalog -> connection test -> save diff, wired into Agent86App"
  - "CatalogReady message + Agent86App._catalog_cache (session-scoped, one fetch per provider)"
  - "model_choices(cfg, extra=...) — the /model picker enriched with the live catalog (closes Phase 2 D-12)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bare (argument-less) needs_choice commands typed directly into the prompt Input now route through _run_or_chain via a find_command_for_line lookup in _dispatch_line, not just palette selections — so \"/config model\"/\"/model\"/\"/mode\" behave identically whether typed or picked"
    - "Catalog cache population happens only inside on_catalog_ready (UI thread), never inside the worker, so the dict is never mutated from two threads (RESEARCH Open Question 3 answered: the cache lives on Agent86App, not on _Repl/Harness)"
    - "The key entered in KeyEntryModal is held in self._pending_key (memory only) and passed straight into the catalog fetch and the connection test; store_api_key is called from exactly one place (_on_test_done), gated on outcome.ok or outcome.override (D-14)"

key-files:
  created: []
  modified:
    - src/agent86/tui/messages.py
    - src/agent86/tui/app.py
    - src/agent86/tui/screens/model_picker.py
    - tests/tui/test_app.py
    - tests/tui/test_provider_manager.py
    - tests/tui/test_pickers.py

key-decisions:
  - "_dispatch_line gained a find_command_for_line lookup so a bare needs_choice command typed and submitted directly (not just picked from the palette) also opens its picker/chain — required because the Wave-0 chain tests type \"/config model\" straight into the prompt Input and press Enter, never opening the palette (multi-word commands are deliberately excluded from palette display since a literal space closes it)"
  - "test_save_anyway_override (Wave 0, owned by this plan) needed its exact key-press choreography filled in, plus mocks for agent86.cognitive.catalog.fetch_catalog and agent86.tui.screens.connection_test.provider_for_ref so the failing-test-then-override path never makes a real network call — the Wave-0 comment (\"exact key bindings owned by 03-08/03-09\") explicitly left this to this plan"
  - "The provider catalog picker is source of truth (D-04); switching the active model applies immediately via _dispatch_line(f\"/model {ref}\") right after a passing test, before SaveDiffModal is even shown — persisting model.default is the separate, optional diff-confirm step"

requirements-completed: [MODEL-01, MODEL-02, SEC-01]

# Metrics
duration: ~90min
completed: 2026-08-06
---

# Phase 3 Plan 9: Full-App /config model Chain + Live-Catalog /model Picker Summary

**Wires provider-manager, key-entry, connection-test, and save-diff modals into one continuous `/config model` flow on `Agent86App`, and enriches the arrow-key `/model` picker with each provider's live catalog (session-cached, one fetch per provider) — closing Phase 2's deferred D-12.**

## Performance

- **Duration:** ~90 min
- **Tasks:** 3/3
- **Files modified:** 6 (3 source, 3 test)

## Accomplishments

- `CatalogReady` message (`src/agent86/tui/messages.py`) carries a provider's fetched (or failed)
  catalog back to the UI thread, tagged with `purpose` (`"manager"` | `"model_picker"`).
- `Agent86App` gains a per-session `_catalog_cache`, `_request_catalog` (cache-or-fetch entry
  point), and a `@work(thread=True)` `_fetch_catalog` worker that never re-fetches a provider
  already cached this session; `on_catalog_ready` populates the cache on the UI thread only.
- The full `/config model` chain is wired: `ProviderManagerModal` → (`KeyEntryModal` only if the
  row has no key and isn't keyless) → catalog fetch/cache → `CatalogPickerModal` →
  `ConnectionTestModal` → on pass or "Save anyway" override, `store_api_key` is called exactly
  once (`_on_test_done`, D-14 gate), the model switch applies immediately via
  `_dispatch_line(f"/model {ref}")`, then `SaveDiffModal` is shown; confirming calls
  `config_writer.apply_edit` and replaces `self.repl.cfg`.
- `_dispatch_line` now routes any bare (argument-less) `needs_choice` command typed directly into
  the prompt — not just palette-selected — through `_run_or_chain`, so `/config model` works
  identically whether typed or picked (multi-word commands never appear in the palette dropdown
  since a literal space hides it, per the existing `_sync_palette` design).
- `model_choices(cfg, extra=None)` appends live catalog `(ref, label)` pairs after the three role
  slots, deduped by ref; the `/model` picker (`_run_or_chain`'s `"model"` branch) is now
  cache-aware — a cached catalog opens the picker immediately, a miss kicks off one lazy fetch and
  opens from `on_catalog_ready(purpose="model_picker")` via the new `_open_model_picker` helper,
  which still falls back to the `"/model "` prefill when nothing is available at all. `/model`
  remains switch-only (D-15) — `_on_model_picked` is unchanged.
- CSS added for the five new dialog ids (`#provider-manager-dialog`, `#catalog-picker-dialog`,
  `#key-entry-dialog`, `#connection-test-dialog`, `#save-diff-dialog`), matching the existing
  `#palette` density.
- Removed all 3 chain-wiring `xfail` markers from `tests/tui/test_provider_manager.py`; filled in
  `test_save_anyway_override`'s exact key-press choreography (provider select → key entry submit
  → catalog pick → connection-test failure → Save-anyway) with `catalog.fetch_catalog` and
  `connection_test.provider_for_ref` mocked so no real network call is made. Added
  `test_escape_dismisses_catalog_picker_not_palette` (priority-binding `SkipAction` regression,
  same footgun class as 02-02/02-04), 3 catalog-cache tests in `test_app.py`, 3 `/model`-picker
  cache-awareness tests in `test_app.py`, and 3 `model_choices(extra=...)` tests in
  `test_pickers.py`.
- Full suite green: **275 passed, 0 xfailed, 0 xpassed, 0 failed** (up from the 262 passed / 2
  xfailed / 1 xpassed baseline — the 2 xfailed were exactly the tests this plan un-marks, and the
  1 xpassed was the third).

## Task Commits

1. **Task 1: CatalogReady message + session catalog cache + catalog fetch worker** - `5fb6b62` (feat)
2. **Task 2: Wire the /config model chain end to end** - `c9234ac` (feat)
3. **Task 3: Enrich the /model picker with the live catalog (closes Phase 2 D-12)** - `6ea50c1` (feat)

**Plan metadata:** (this commit) `docs(03-09): complete full-app chain + /model catalog plan`

## Files Created/Modified

- `src/agent86/tui/messages.py` — `CatalogReady` message
- `src/agent86/tui/app.py` — catalog cache/fetch worker, `on_catalog_ready`, the full
  `/config model` chain (`_open_provider_manager`, `_on_provider_row`, `_on_key_entered`,
  `_on_catalog_picked`, `_on_test_done`, `_persist_changes`, `_on_save_confirmed`), cache-aware
  `/model` branch + `_open_model_picker`, `_dispatch_line`'s bare-needs_choice routing, new CSS
- `src/agent86/tui/screens/model_picker.py` — `model_choices(cfg, extra=None)`, docstring updated
  (Phase 3's job is no longer future tense)
- `tests/tui/test_app.py` — 3 catalog-cache tests, 3 `/model`-picker cache tests, 1 escape/
  SkipAction regression test
- `tests/tui/test_provider_manager.py` — xfail markers removed from the 3 chain tests;
  `test_save_anyway_override` given its real key-press choreography and network mocks
- `tests/tui/test_pickers.py` — 3 `model_choices(extra=...)` tests

## Decisions Made

See `key-decisions` in frontmatter. In short: bare needs_choice commands now chain from typed
input as well as the palette (required by the Wave-0 test contract); `test_save_anyway_override`'s
exact navigation was left to this plan by design and implemented with network-safe mocks; the
model switch is applied to the session immediately, independent of whether the user confirms the
config-file save.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Typed (non-palette) `/config model` did not open the provider manager**
- **Found during:** Task 2, running the pre-written `test_no_key_provider_chains_to_key_entry` /
  `test_save_anyway_override` tests (which set `prompt.value` directly and press Enter, never
  opening the palette)
- **Issue:** `_dispatch_line` only ever called `handle_command`, which returns the `/config
  model` entry's non-TUI fallback text; only `_select_palette` called `_run_or_chain`. A directly
  typed `/config model` (or bare `/model`/`/mode`) therefore never chained into a modal.
- **Fix:** `_dispatch_line` now looks up the line via `find_command_for_line`; if the matched
  entry has `needs_choice` set and no argument was given, it calls `_run_or_chain(entry)` instead
  of `handle_command`. Behavior for commands *with* an argument (e.g. `/model openai:gpt-4o`)
  and for commands without `needs_choice` is unchanged.
- **Files modified:** `src/agent86/tui/app.py`
- **Verification:** `pytest tests/tui/test_provider_manager.py tests/tui/test_app.py
  tests/tui/test_palette.py -q` — all pass, no regression to the palette-driven chaining tests.
- **Committed in:** `c9234ac` (Task 2 commit)

**2. [Rule 3 - Blocking] `test_save_anyway_override`'s Wave-0 body under-specified its navigation**
- **Found during:** Task 2
- **Issue:** The Wave-0 scaffold's `test_save_anyway_override` pressed Enter only twice and
  asserted the final screen was `SaveDiffModal`, but the actual chain (provider select → key
  entry → catalog pick → failing connection test → Save-anyway) needs several more interactions,
  and its own comment says the exact bindings are "owned by 03-08/03-09". Running it unmodified
  landed on `KeyEntryModal`, not `SaveDiffModal`.
- **Fix:** Filled in the missing steps: clear provider-key env vars, mock
  `agent86.cognitive.catalog.fetch_catalog` (fixed one-entry catalog) and
  `agent86.tui.screens.connection_test.provider_for_ref` (raises immediately) so the whole path
  runs with no real network call, type a throwaway key into `KeyEntryModal`, select the faked
  catalog entry, wait for the connection test's failure buttons, and press Enter on the focused
  "Save anyway" button.
- **Files modified:** `tests/tui/test_provider_manager.py`
- **Verification:** `pytest tests/tui/test_provider_manager.py -q` — 12 passed, 0 xfailed.
- **Committed in:** `c9234ac` (Task 2 commit)

**3. [Rule 1 - Bug] Task 1's own catalog-cache test broke once Task 2 wired `on_catalog_ready`**
- **Found during:** Task 2, running the full `tests/tui` suite
- **Issue:** `test_catalog_cache_fetches_once_per_provider` (added in Task 1) issued two
  back-to-back `_request_catalog` calls with `purpose="manager"`; once `on_catalog_ready` started
  pushing `CatalogPickerModal` (Task 2), the second call pushed a second modal while the first was
  still mounting, and Textual's `query_one("#catalog-filter", ...)` raised `NoMatches` inside the
  second modal's `on_mount`.
- **Fix:** The test now pops the first pushed screen (and pauses) before issuing the second
  `_request_catalog` call, so the two pushes never race.
- **Files modified:** `tests/tui/test_app.py`
- **Verification:** `pytest tests/tui/test_app.py -q` — all pass.
- **Committed in:** `c9234ac` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (1 bug in `_dispatch_line`'s routing, 1 blocking gap in a
Wave-0 test's own choreography, 1 bug in Task 1's own test surfaced by Task 2's wiring)
**Impact on plan:** All three were necessary to satisfy the plan's own acceptance criteria and the
pre-written Wave-0 test contract. No scope creep — no new command surface, dialog, or config
behavior was invented beyond what the plan specified.

## Issues Encountered

None beyond the three auto-fixed items above.

## User Setup Required

None for automated verification. Per `03-VALIDATION.md`'s Manual-Only section, three items remain
for a human pass in Windows Terminal before this phase is declared fully done (not part of this
plan's automated scope):
1. Launch the TUI, run the full `/config model` flow against a real provider, confirm the key
   lands in Windows Credential Manager (service `agent86`), survives an app restart, and clears.
2. Back up `~/.agent86/config.toml`, run the flow, diff before/after, confirm every hand-written
   comment survived.
3. Live-verify the OpenRouter/Groq catalog response shapes against the real endpoints (Groq's
   shape is still unverified per 03-04-SUMMARY.md).

## Next Phase Readiness

Phase 3 (`03-secrets-model-provider-config`) is now feature-complete: all 9 plans done, full suite
green (275 passed, 0 xfailed, 0 failed), `agent86 --plain` / `run --json` verified unchanged, and
`tests/tui/test_lazy_import.py` confirms `keyring`/`tomlkit`/`textual` are still absent from
`sys.modules` after `import agent86.cli`. `.planning/phases/03-secrets-model-provider-config/
deferred-items.md` is removed — every failure it logged was a transient parallel-wave artifact,
already resolved by the time this plan ran (confirmed by the clean full-suite baseline before
Task 1). No blockers for Phase 4 (MCP Config UI), which can reuse the same modal-chain /
`config_writer` / `secrets` seams established across this phase.

---
*Phase: 03-secrets-model-provider-config*
*Completed: 2026-08-06*

## Self-Check: PASSED

All files listed under Files Created/Modified confirmed present on disk (`src/agent86/tui/messages.py`,
`src/agent86/tui/app.py`, `src/agent86/tui/screens/model_picker.py`, `tests/tui/test_app.py`,
`tests/tui/test_provider_manager.py`, `tests/tui/test_pickers.py`). All three task commits
(`5fb6b62`, `c9234ac`, `6ea50c1`) confirmed in git history via `git log --oneline --all`.
