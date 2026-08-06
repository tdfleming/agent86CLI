---
phase: 03-secrets-model-provider-config
verified: 2026-08-06T00:41:51Z
status: human_needed
score: 4/4 must-haves verified
human_verification:
  - test: "Real OS keyring round-trip: /config model -> add a key for a test provider -> confirm it appears in Windows Credential Manager under service 'agent86' -> restart the app -> confirm the key still resolves -> clear it and confirm it is gone"
    expected: "Key is stored under service 'agent86' account <provider>, survives restart, and is removable"
    why_human: "Unit tests monkeypatch keyring at the agent86.secrets module boundary; WinVaultKeyring payload-size behavior and real backend detection cannot be proven without the real OS credential store (03-VALIDATION.md Manual-Only row 1)"
  - test: "Back up ~/.agent86/config.toml, add a model via the manager, diff before/after against the real file"
    expected: "Every hand-written comment and blank line in the user's real config survives the write"
    why_human: "Fixture round-trip (tests/fixtures/config_with_comments.toml) proves the tomlkit mechanism; only the user's real file proves the integration end-to-end (03-VALIDATION.md Manual-Only row 2)"
  - test: "curl the Groq /v1/models endpoint with a real GROQ_API_KEY and compare the shape to tests/fixtures/catalog/groq_models.json"
    expected: "fetch_openai_compatible's {\"data\":[{\"id\":...}]} assumption matches Groq's real response"
    why_human: "No GROQ_API_KEY was available during execution; OpenRouter's shape was confirmed live on 2026-08-05 and matches its fixture exactly, but Groq remains unverified against a live call (03-VALIDATION.md Manual-Only row 3, 03-04-SUMMARY.md 'Unverified')"
---

# Phase 3: Secrets & Model/Provider Configuration Verification Report

**Phase Goal:** Keyring-backed API keys and an in-app model-config modal that lists, switches,
adds, and live-tests providers/models, writing changes back to user config non-destructively.
**Verified:** 2026-08-06T00:41:51Z
**Status:** human_needed (all automated checks pass; three items are inherently manual per
03-VALIDATION.md and were never claimed as automatable)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Success Criteria from ROADMAP.md)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `resolve_api_key(provider, pconf)` resolves env first, then keyring; providers use it; config never stores a plaintext secret | VERIFIED | `src/agent86/secrets.py:27-47` — env checked via `os.getenv` before any keyring import; `plan_edit` in `src/agent86/config_writer.py:83-87` raises `ValueError` on any of `api_key`, `apikey`, `key`, `token`, `secret`, `password` as a leaf key, so no write path can ever persist a secret |
| 2 | A model-config modal can add a provider/model, store its key in the keyring, and run a live connection test that confirms a response before saving | VERIFIED | Full chain in `src/agent86/tui/app.py:278-344`: `ProviderManagerModal` -> `KeyEntryModal` -> catalog fetch -> `CatalogPickerModal` -> `ConnectionTestModal` (real `provider_for_ref(...).complete(...)` 1-token probe, `src/agent86/tui/screens/connection_test.py:80-89`) -> `store_api_key` only fires in `_on_test_done` after `outcome.ok` or explicit override (D-14 gate, `app.py:323-340`) |
| 3 | Saving writes to `~/.agent86/config.toml` via tomlkit with comments preserved; project-scope option offered | VERIFIED | `config_writer.plan_edit` uses `tomlkit.parse`/CST round-trip (`config_writer.py:70-97`); `_write_atomic` (temp-file + `os.replace`) prevents truncation; `SaveDiffModal` pre-selects `SCOPE_USER`, offers `SCOPE_PROJECT` one radio-button away (`save_diff.py:46-56`); `tests/unit/test_config_writer.py` round-trips a hand-commented fixture and passes |
| 4 | Switching the active model from the modal takes effect for the next turn | VERIFIED | `_on_test_done` calls `self._dispatch_line(f"/model {self._pending_ref}")` immediately on a passing test (`app.py:342-343`), which reaches the pre-existing `Harness.set_model` path (`orchestration/loop.py:130`) *before* the `SaveDiffModal` is even shown — persistence to `model.default` is a separate, later, user-confirmed step (`_persist_changes`, `app.py:346-356`) |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/agent86/secrets.py` | env-first/keyring-fallback key resolution, lazy-imported | VERIFIED | `keyring` imported inside every function body only; `resolve_api_key`/`keyring_available`/`has_stored_key`/`store_api_key`/`clear_api_key` all present and exercised by `tests/unit/test_secrets.py` |
| `src/agent86/config_writer.py` | comment-preserving write-back, plan/apply split, secret-leaf guard | VERIFIED | `plan_edit`/`apply_edit`/`ConfigEdit`/`ConfigWriteError` all present; `tomlkit` imported lazily; atomic write via `tempfile.mkstemp` + `os.replace` |
| `src/agent86/cognitive/catalog.py` | live per-provider models fetch, normalized `(ref,label)` | VERIFIED | OpenAI-compatible / Anthropic (`x-api-key`, never Bearer) / Ollama fetchers present; `CatalogUnavailable` raised on any failure or unsupported provider (llama.cpp); no hardcoded model list |
| `src/agent86/tui/screens/key_entry.py` | masked key entry, no echo, no reveal | VERIFIED | `Input(password=True)`; dismiss-only exit paths; no reveal action |
| `src/agent86/tui/screens/connection_test.py` | real live probe, 15s hard timeout, Save-anyway override | VERIFIED | `provider_for_ref(...).complete(...)` on a worker thread with `Event.wait(TIMEOUT_S=15.0)`; `TestOutcome.override` wired to the "Save anyway" button; content confirmed intact despite the 03-08/689f0da commit-attribution race (see item 6 below) |
| `src/agent86/tui/screens/save_diff.py` | diff+scope preview before any disk write | VERIFIED | `plan_edit` called in `_refresh` on mount and on scope change; never touches disk; `on_button_pressed`/`action_cancel` both resolve explicitly |
| `src/agent86/tui/screens/provider_manager.py` | provider list w/ key status + type-to-filter catalog picker w/ free-text fallback | VERIFIED | `provider_rows` uses `resolve_api_key` for status, never returns the key; `CatalogPickerModal` free-text fallback in `on_input_submitted` |
| `src/agent86/tui/app.py` | end-to-end chain wiring, `/config model` entry point | VERIFIED | `_open_provider_manager` -> ... -> `_on_save_confirmed` chain complete; `_dispatch_line` routes `/model <ref>` through existing Phase-2 path |
| `src/agent86/cli.py` | `/config` bare-invocation surfaces provider/key table, lazy-imported | VERIFIED | `config_default` callback with `invoke_without_command=True`; `has_stored_key`/`keyring_available` imported lazily inside `_list_models`; confirmed by direct import-probe (`sys.modules` after `import agent86.cli` contains none of keyring/tomlkit/textual) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `ConnectionTestModal` | `store_api_key` | `_on_test_done` gate | WIRED | Key is only ever persisted after `outcome.ok` or explicit override; confirmed by reading `app.py:323-340`, no other call site of `store_api_key` exists in the app |
| `ProviderManagerModal` | `KeyEntryModal` | `_on_provider_row` (no-key branch) | WIRED | `row.keyless or row.has_key` short-circuits straight to catalog fetch; otherwise chains to key entry — no dead end (D-05) |
| `SaveDiffModal` | `config_writer.apply_edit` | `_on_save_confirmed` | WIRED | `edit is None` (cancel) writes nothing and logs a session-only note; otherwise `apply_edit` is called and `repl.cfg` is refreshed from the reload |
| `/model <ref>` switch | `Harness.set_model` | `_dispatch_line` -> `handle_command` -> `_set_model` | WIRED | Fires *before* `SaveDiffModal` is shown, satisfying success criterion 4 independent of whether the user later saves or cancels |
| `agent86 config` (bare) | `_list_models` | `config_default` Typer callback | WIRED | `ctx.invoked_subcommand is None` guard means `config show`/`config path` dispatch normally to their own commands, unaffected |
| Typed bare `needs_choice` command (`/model`, `/mode`, `/config model`) | `_run_or_chain` | `_dispatch_line` match-and-route | WIRED (behavior change, see Anti-Patterns/Notes) | Previously only palette-selected `needs_choice` entries opened a picker; 03-09 extended this to typed input with no argument |

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SEC-01 | 03-01, 03-02, 03-03, 03-05, 03-06, 03-09 | API keys stored/read via OS keyring; env precedence; no plaintext secret in config | SATISFIED | `secrets.py` precedence logic + `config_writer.py` forbidden-leaf-key guard + `key_entry.py`/`connection_test.py` D-14 store-after-test gate, all independently confirmed above |
| MODEL-01 | 03-01, 03-04, 03-05, 03-06, 03-08, 03-09 | List/switch/add/test providers & models in-app, live test before saving | SATISFIED | Full chain wired in `app.py`; catalog fetch is live, no hardcoded models; connection test is a real 1-token completion |
| MODEL-02 | 03-01, 03-03, 03-07, 03-09 | Config written back non-destructively, comments preserved, user default / project option | SATISFIED | `config_writer.py` tomlkit round-trip + `save_diff.py` scope selector + `_persist_changes`/`_on_save_confirmed` wiring in `app.py` |

No orphaned requirements — REQUIREMENTS.md maps exactly SEC-01/MODEL-01/MODEL-02 to Phase 3 and
all three appear in at least one plan's `requirements:` frontmatter field.

**Note on requirement-marking discipline (scrutiny item 1):** REQUIREMENTS.md's checkbox list
(lines 28-36) marks all three as `[x]`, which is now accurate against shipped code. However the
Traceability table further down the same file (lines 71-73) is stale — it still reads "In
Progress (Wave 0 scaffolds done, plan 03-01/9)" for all three rows, unchanged since 03-01. This is
a documentation-freshness gap, not a functional one: independent re-verification of the actual
code (not the SUMMARY claims, not the checkbox) confirms all three requirements are genuinely
satisfied by wired, tested, non-stub code as of the 03-09 commit. The traceability table should be
updated to "Complete" by whatever process closes out this phase.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | No TODO/FIXME/placeholder/stub-return patterns found in any of the 10 phase-modified core files | — | none |

**Behavioral deviation note (scrutiny item 3):** 03-09 changed `_dispatch_line` so that any
argument-less `needs_choice` command *typed directly* (not just palette-picked) now opens the same
picker/chain as palette selection. This is a real, intentional behavior change versus pre-Phase-3
code:
- Typed bare `/mode` previously called `_cycle_approval()` directly (silent cycle, text output
  "approval mode: X"); it now opens `ModePickerModal` instead.
- Typed bare `/model` previously printed "current model: ... / usage: ..."; it now opens
  `ModelPickerModal`.

Both old behaviors remain reachable with an argument (`/mode auto`, `/model openai:gpt-4o`) and
Shift+Tab still cycles mode. No test types the literal string `/model` or `/mode` into the prompt
`Input` and presses Enter to exercise this exact path (existing coverage calls
`app._run_or_chain(find_command("/model"))` directly, and a separate test exercises Shift+Tab).
The logic is shared with the already-tested palette path, so risk is low, but this is a
user-visible change to two Phase 2 commands, not merely additive — flagged for awareness, not
scored as a gap since it is documented in 03-09-SUMMARY.md and both commands remain fully
functional.

**CLI surface note (scrutiny item 2):** `agent86 config` (bare, no subcommand) now prints the
provider/key table via a Typer `invoke_without_command=True` callback. Read the guard directly:
`config_default` only acts `if ctx.invoked_subcommand is None`, so `agent86 config show` and
`agent86 config path` still dispatch to their own registered commands untouched. Sane, standard
Typer group-callback pattern — confirmed non-breaking.

**Lazy-import compliance (scrutiny item 4):** Independently probed (not just trusting
`test_lazy_import.py`) with a fresh subprocess-equivalent import: `import agent86.cli` followed by
inspecting `sys.modules` shows zero modules from `keyring`, `tomlkit`, or `textual`. Every
call site of `keyring`/`tomlkit` in `secrets.py`/`config_writer.py`/`cli.py` imports inside the
function body, never at module scope.

**Plaintext-secret trace (scrutiny item 5):** Traced key flow end to end: `KeyEntryModal`
(`Input(password=True)`, dismisses with the raw string held only in the modal's return value) ->
`app._pending_key` (in-memory attribute only) -> `store_api_key` (writes to OS keyring, never to
any file) in `_on_test_done`. Separately, `_persist_changes` (what gets written to `config.toml`)
only ever appends `["providers", name, "api_key_env"]` (the *env var name*, e.g. `"OPENAI_API_KEY"`)
— never the key value — and `config_writer.plan_edit` independently guards against any leaf named
`api_key`/`apikey`/`key`/`token`/`secret`/`password` by raising `ValueError`. Two independent
layers both refuse to ever let a secret reach disk.

**Commit-attribution file-integrity check (scrutiny item 6):** `src/agent86/tui/screens/connection_test.py`
landed in commit `689f0da` (03-08's commit) instead of 03-06's, per a documented commit-attribution
race. Content was read in full and is complete and correct: masked key never touches this file,
real `provider_for_ref(...).complete(...)` call, `Event.wait(15.0)` hard timeout,
`TestOutcome.override` for Save-anyway, all four dismissal paths (success, failure, timeout,
Escape) resolve explicitly. All 10 of `tests/tui/test_connection_test.py`'s tests pass. No content
was lost or corrupted.

### Human Verification Required

See `human_verification` in the frontmatter — these three items are explicitly out of automated
reach per `03-VALIDATION.md`'s Manual-Only table and were never claimed as machine-verifiable:

1. Real Windows Credential Manager round-trip for a stored key.
2. Comment-preservation diff against the user's actual `~/.agent86/config.toml`.
3. Live Groq `/v1/models` schema confirmation (OpenRouter's shape was already confirmed live on
   2026-08-05 and matches its fixture exactly; Groq remains unverified for lack of a
   `GROQ_API_KEY` in this environment).

### Gaps Summary

No functional gaps. All 4 success criteria are verified against actual, wired, tested source —
not SUMMARY claims. The full test suite (275 tests) passes. The only findings are: (a) a stale
Traceability-table status line in REQUIREMENTS.md that lags the (correct) top-of-file checkbox
list, which is a documentation-freshness issue, not a code gap; and (b) a documented, low-risk,
intentional UX change to bare-typed `/model`/`/mode` that trades a text-output shortcut for the
same picker used elsewhere in the app. Status is `human_needed` rather than `passed` only because
three items are inherently outside automated reach per the phase's own validation strategy.

---

_Verified: 2026-08-06T00:41:51Z_
_Verifier: Claude (gsd-verifier)_
