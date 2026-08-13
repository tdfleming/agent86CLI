---
quick_id: 260813-adr
description: Make /model catalog picker insert the active provider prefix
mode: quick
created: 2026-08-13
files_modified:
  - src/agent86/tui/screens/model_picker.py
  - src/agent86/tui/app.py
  - tests/tui/test_pickers.py
  - tests/tui/test_app.py
---

# Quick Task 260813-adr: Make the `/model` catalog picker insert the active provider prefix

## Objective

In the TUI, `/model` opens `ModelPickerModal`; selecting a **live-catalog** entry dispatches a
broken ref. Reproduced by the user: picking the Ollama entry `nemotron-3.5-lightning:latest`
produces

    Unknown provider 'nemotron-3.5-lightning'. Built-in: anthropic, openai, ollama, llamacpp. ...

Root cause chain (all verified against the source):

1. `fetch_catalog` returns **bare** model ids by design — documented at
   `src/agent86/cognitive/catalog.py:19`: *"Returned pairs are `(ref, label)` where `ref` is the
   bare model id; the caller prefixes `provider:`."*
2. The `/config model` path prefixes correctly: `CatalogPickerModal._catalog_ref`
   (`src/agent86/tui/screens/provider_manager.py:171`) returns `f"{self._provider}:{model}"`.
   **This is the convention to mirror.**
3. The `/model` path does **not** prefix. `Agent86App._open_model_picker`
   (`src/agent86/tui/app.py:291`) passes the bare catalog entries straight into
   `model_choices(self.repl.cfg, extra=extra)`, so the option value is the bare id and
   `_on_model_picked` (`app.py:287`) dispatches `/model <bare-id>`.
4. `ModelRef.parse` (`src/agent86/types.py:66-76`) uses `partition(":")` — it splits on the
   **first** colon. `nemotron-3.5-lightning:latest` → provider `nemotron-3.5-lightning`,
   model `latest`.

**Severity is broader than Ollama.** For providers whose ids contain no colon at all (openai
`gpt-4o`), the dispatched `/model gpt-4o` fails `ModelRef.parse` outright with *"Model reference
'gpt-4o' must be 'provider:model'"*. The `/model` picker's catalog section is currently broken
for **every** provider; fixing it generally is what fixes the reported Ollama case.

## Fix

Prefix catalog-sourced refs with the **active provider** inside `_open_model_picker` — that one
function covers both call sites: the session-cache hit at `app.py:275` and the fresh-fetch path
via `on_catalog_ready(purpose="model_picker")` at `app.py:667`.

Implement the prefixing as a small pure helper in `model_picker.py` (mirroring
`CatalogPickerModal._catalog_ref`, but pure so it is unit-testable without a Pilot app), and call
it from `_open_model_picker` **before** `model_choices`, so `model_choices`'s dedupe against role
slots (`src/agent86/tui/screens/model_picker.py:49-54`) compares like against like.

Explicitly **out of scope**: do NOT change `fetch_catalog` to return prefixed refs — its bare-id
contract is relied on by `CatalogPickerModal`, and changing it would double-prefix the
`/config model` path.

## Tasks

### Task 1: Add `prefix_catalog_refs` and wire it into `_open_model_picker`

- **files**: `src/agent86/tui/screens/model_picker.py`, `src/agent86/tui/app.py`
- **action**:
  1. In `src/agent86/tui/screens/model_picker.py`, add a module-level pure function:

     ```python
     def prefix_catalog_refs(
         provider: str, entries: list[tuple[str, str]] | None
     ) -> list[tuple[str, str]]:
     ```

     For each `(ref, label)` in `entries` (treat `None`/empty as `[]`):
     - `full = ref if ref.startswith(f"{provider}:") else f"{provider}:{ref}"`
     - label rule: `full if label == ref else label` — i.e. when the provider supplied no
       distinct display name (Ollama's `(name, name)`, or an OpenAI id echoed as its own label),
       prefix the label too so it stays equal to the ref and `model_choices`'s existing
       `label if label != ref else ref` expression (line 54) keeps rendering the full
       `provider:model`. When the provider DID supply a real display name (OpenRouter's
       `data[].name`), leave that label untouched.
     - Return a new list; never mutate the input (the caller's list is the session cache stored
       in `Agent86App._catalog_cache` — mutating it would corrupt the cache for later opens).
  2. **Double-prefix guard (document it in the docstring):** the already-prefixed test is an
     **exact `f"{provider}:"` prefix match only**. A bare Ollama id legitimately contains a colon
     (`llama3.1:8b`, `nemotron-3.5-lightning:latest`), so "contains a colon" is NOT a valid
     already-prefixed test — that is precisely the bug being fixed. This mirrors the same
     reasoning already recorded in `CatalogPickerModal._freetext_ref`
     (`provider_manager.py:174-179`).
  3. Export it: add `"prefix_catalog_refs"` to `model_picker.py`'s `__all__`.
  4. In `src/agent86/tui/app.py`, import `prefix_catalog_refs` alongside the existing
     `ModelPickerModal, model_choices` import (line 46) and change `_open_model_picker`
     (line 291) to:

     ```python
     def _open_model_picker(self, extra: list[tuple[str, str]]) -> None:
         # The catalog yields BARE model ids (catalog.py's documented contract); only a full
         # `provider:model` ref survives ModelRef.parse. Prefix BEFORE model_choices so its
         # role-slot dedupe compares full refs against full refs.
         provider = self.repl.harness.provider.name
         choices = model_choices(self.repl.cfg, extra=prefix_catalog_refs(provider, extra))
         ...
     ```

     Leave the rest of `_open_model_picker` (the empty-`choices` `/model ` prefill fallback and
     the `push_screen`) unchanged.
  5. Do **not** touch `model_choices`'s role-slot handling — `cfg.model.default`,
     `route.cheap` and `route.frontier` are already full `provider:model` refs and must pass
     through untouched. Only the `extra` list is prefixed.
- **verify**: `python -m pytest tests/tui/ -q` passes (existing suite, no regressions —
  `test_model_picker_uses_cached_catalog` seeds `("cached:ref", "cached label")` and only asserts
  the modal opens, so it must still pass).
- **done**: `prefix_catalog_refs` exists, is exported, and `_open_model_picker` is the single
  place both `/model` catalog paths (cache hit + fresh fetch) get prefixed.

### Task 2: Regression tests

- **files**: `tests/tui/test_pickers.py`, `tests/tui/test_app.py`
- **action**:
  1. In `tests/tui/test_pickers.py` (pure tests, no Pilot needed — follow the existing
     `test_model_choices_*` style), import `prefix_catalog_refs` and `ModelRef` and add:
     - `test_prefix_catalog_refs_prefixes_colon_bearing_ollama_id` — `prefix_catalog_refs(
       "ollama", [("nemotron-3.5-lightning:latest", "nemotron-3.5-lightning:latest")])` yields
       ref `"ollama:nemotron-3.5-lightning:latest"`.
     - `test_prefixed_ollama_ref_parses_back_to_provider_and_full_model` — `ModelRef.parse` on
       that ref gives `provider == "ollama"` and `model == "nemotron-3.5-lightning:latest"`
       (this is the exact assertion the reported bug violated).
     - `test_prefix_catalog_refs_prefixes_colon_free_id` — `prefix_catalog_refs("openai",
       [("gpt-4o", "gpt-4o")])` yields `"openai:gpt-4o"`, and `ModelRef.parse` accepts it
       (guards the broader, all-providers breakage).
     - `test_prefix_catalog_refs_does_not_double_prefix` — an entry already given as
       `("ollama:llama3.1:8b", ...)` comes back unchanged, and a distinct provider display name
       (e.g. `("gpt-4o", "GPT-4o")`) keeps its label while the ref is prefixed.
     - `test_model_choices_does_not_double_prefix_role_slots` — call
       `model_choices(load_config(), extra=prefix_catalog_refs(provider, entries))` where
       `provider`/`entries` are chosen so the catalog entry reproduces `cfg.model.default`
       (derive `provider` and the bare id by splitting `cfg.model.default` on the FIRST colon,
       matching `ModelRef.parse`): assert every returned value still equals `cfg.model.default`
       exactly (no `anthropic:anthropic:...`) and that the total count equals the un-extra'd
       `model_choices(cfg)` count — proving the dedupe still suppresses the duplicate now that
       prefixing happens first.
  2. In `tests/tui/test_app.py`, add ONE Pilot test proving the end-to-end `/model` wiring
     (mirror `test_model_picker_uses_cached_catalog` at line 244):
     - Build `repl = _make_repl(tmp_path, make_text_provider("hello world"))`, then set
       `repl.harness.provider.name = "ollama"` (instance attribute shadows `TextProvider.name`,
       which is a class attribute) so the active provider is the one from the bug report.
     - Seed `app._catalog_cache["ollama"] = [("nemotron-3.5-lightning:latest",
       "nemotron-3.5-lightning:latest")]` so no network call happens, then
       `app._run_or_chain(find_command("/model"))` and `await pilot.pause()`.
     - Assert `isinstance(app.screen, ModelPickerModal)` and that
       `"ollama:nemotron-3.5-lightning:latest"` is among the option VALUES the modal was built
       with (`[value for _, value in app.screen._choices]`) — and that the bare
       `"nemotron-3.5-lightning:latest"` is NOT.
  3. Confirm RED before GREEN: the new `test_pickers.py` assertions must fail against the
     pre-fix source (they reference a function that does not exist yet, so write them, run once
     to see the failure, then implement — or verify via a `git stash` round-trip if Task 1 lands
     first). Record which tests were confirmed failing pre-fix in the summary.
- **verify**: `python -m pytest tests/tui/test_pickers.py tests/tui/test_app.py -q` passes, then
  the full suite: `python -m pytest -q`.
- **done**: All four required assertions from the bug report are covered (colon-bearing Ollama id,
  `ModelRef.parse` round trip, colon-free id, role slots not double-prefixed), plus the
  end-to-end `/model` path test.

## Success Criteria

- [ ] Selecting an Ollama catalog entry via `/model` dispatches
      `/model ollama:nemotron-3.5-lightning:latest`, not the bare id — no "Unknown provider" error.
- [ ] `ModelRef.parse("ollama:nemotron-3.5-lightning:latest")` → provider `ollama`, model
      `nemotron-3.5-lightning:latest`.
- [ ] A colon-free catalog id (`gpt-4o`) becomes `openai:gpt-4o` and parses.
- [ ] Config role-slot refs (`model.default`, `route.cheap`, `route.frontier`) are byte-identical
      in the picker — never double-prefixed — and a catalog entry duplicating a role slot is
      still deduped away.
- [ ] `src/agent86/cognitive/catalog.py` is unmodified (`git diff --stat` shows no change to it),
      so the `/config model` `CatalogPickerModal` path keeps working unchanged.
- [ ] Full suite passes. **Known pre-existing, unrelated failure:**
      `tests/unit/test_memory.py::test_build_embedder_falls_back_without_torch` fails in this dev
      environment (sentence-transformers IS installed, so the test's "torch isn't installed"
      premise doesn't hold). Do not fix it; do not treat it as a regression.

## Output

Create `.planning/quick/260813-adr-make-model-catalog-picker-insert-the-act/260813-adr-SUMMARY.md`
on completion.
