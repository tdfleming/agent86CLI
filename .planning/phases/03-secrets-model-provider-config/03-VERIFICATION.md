---
phase: 03-secrets-model-provider-config
verified: 2026-08-06T03:11:21Z
status: human_needed
score: 9/9 must-haves verified
re_verification:
  previous_status: human_needed
  previous_score: 4/4 (initial success-criteria pass, before UAT surfaced 5 blockers)
  gaps_closed:
    - "The entered API key is never echoed, logged to the transcript, or rendered in plaintext (D-10)"
    - "The connection test returns a pass/fail verdict for the provider, not an SDK crash"
    - "An API key is never rendered in plaintext anywhere in the UI or its error output (D-10)"
    - "Selecting a model through /config model produces a working turn against that model"
    - "A key stored in the OS keyring is resolved on subsequent connection tests without re-prompting"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Real OS keyring round-trip: /config model -> add a key for a test provider -> confirm it appears in Windows Credential Manager under service 'agent86' -> restart the app -> confirm the key still resolves -> clear it and confirm it is gone"
    expected: "Key is stored under service 'agent86' account <provider>, survives restart, and is removable; the full add-key -> test -> save flow no longer echoes the key or crashes on SDK/temperature errors"
    why_human: "Unit/Pilot tests mock the keyring backend and the Anthropic SDK; the original UAT session that found the 5 blockers used the real Windows Credential Manager and a live model call, which is the only way to prove the closures together end-to-end (03-VALIDATION.md Manual-Only row 1; 03-HUMAN-UAT.md test 1)"
  - test: "curl the Groq /v1/models endpoint with a real GROQ_API_KEY and compare the shape to tests/fixtures/catalog/groq_models.json"
    expected: "fetch_openai_compatible's {\"data\":[{\"id\":...}]} assumption matches Groq's real response"
    why_human: "No GROQ_API_KEY was available during this session either; unchanged from the initial verification (03-VALIDATION.md Manual-Only row 3, 03-HUMAN-UAT.md test 3, still blocked_by: third-party)"
---

# Phase 3: Secrets & Model/Provider Configuration Verification Report

**Phase Goal:** Keyring-backed API keys and an in-app model-config modal that lists, switches,
adds, and live-tests providers/models, writing changes back to user config non-destructively.
**Verified:** 2026-08-06T03:11:21Z
**Status:** human_needed (all automated checks pass, including all 5 UAT-diagnosed blockers now
closed against real source; two items remain inherently manual per 03-VALIDATION.md)
**Re-verification:** Yes — after gap-closure plans 03-10 through 03-13 closed the 5 blockers
diagnosed during human UAT on the original 4-truth verification

## Goal Achievement

### Observable Truths (Success Criteria from ROADMAP.md, plus the 5 UAT-diagnosed blockers)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `resolve_api_key(provider, pconf)` resolves env first, then keyring; providers use it; config never stores a plaintext secret | VERIFIED | `src/agent86/secrets.py:27-47` — env checked via `os.getenv` before any keyring import; `config_writer.py` forbidden-leaf-key guard unchanged since initial verification |
| 2 | A model-config modal can add a provider/model, store its key in the keyring, and run a live connection test that confirms a response before saving | VERIFIED | Chain unchanged: `ProviderManagerModal` -> `KeyEntryModal` -> catalog fetch -> `CatalogPickerModal` -> `ConnectionTestModal`; now additionally proven not to leak the key or crash on a real Anthropic SDK/model (see truths 5-9 below) |
| 3 | Saving writes to `~/.agent86/config.toml` via tomlkit with comments preserved; project-scope option offered | VERIFIED | Unchanged; UAT test 2 (real user config) passed |
| 4 | Switching the active model from the modal takes effect for the next turn | VERIFIED | Unchanged; `_dispatch_line(f"/model {ref}")` in `_on_test_done` |
| 5 | The entered API key is never echoed, logged to the transcript, or rendered in plaintext (D-10, UAT gap 1) | VERIFIED | `key_entry.py:45-51` calls `event.stop()` before `dismiss()`; `provider_manager.py`'s `CatalogPickerModal.on_input_submitted` does the same; `app.py:146-150` guards `on_input_submitted` on `event.input.id == "prompt"`. `tests/tui/test_secret_leak.py` (6 tests) confirmed failing pre-fix, passing post-fix |
| 6 | The connection test returns a pass/fail verdict for the provider, not an opaque SDK crash (UAT gap 2/3) | VERIFIED | `anthropic_provider.py:28-78` — `_MIN_ANTHROPIC_VERSION=(0,40)` guard raises a `ProviderError` naming found/needed versions and the exact upgrade command, before `anthropic.Anthropic(**kwargs)` is ever called. `tests/unit/test_anthropic_sdk_guard.py` (10 tests) proves the guard and the full `run_repl` fail-soft path ("Cannot start:" with no traceback, no key leak) |
| 7 | An API key is never rendered in plaintext anywhere in the UI or its error output (UAT gap 2b) | VERIFIED | `cli.py:53` sets `pretty_exceptions_show_locals=False`; `secrets.redact()` added and exported; `cognitive/base.py:117-151` `provider_for_ref` wraps construction, converts any non-`ProviderError` exception to a redacted `ProviderError` via `raise ... from None` (severs the frame chain holding the key). `tests/unit/test_secret_traceback.py` (10) + `tests/unit/test_guardrails.py` (14) pass |
| 8 | Selecting a model through `/config model` produces a working turn (no `temperature` 400 on Opus 5, UAT gap 5) | VERIFIED | `cognitive/capabilities.py` shared seam (`SAMPLING_PARAMS`, `supports_sampling_params`, `apply_sampling_params`, `mark_sampling_unsupported`, `is_sampling_rejection`); `anthropic_provider.py:164-183` gates sampling params in `stream()` and self-corrects on a live 400. `base.py.complete()` is derived from `stream()`, so `complete()` inherits the fix without separate code — satisfies the plan's explicit "check `complete()` too" requirement. `openai_provider.py` uses the same seam, behavior-identical for OpenAI/Groq/OpenRouter. `tests/unit/test_capabilities.py` (26 tests) pass |
| 9 | A key stored in the OS keyring is resolved on subsequent connection tests without re-prompting (UAT gap 4) | VERIFIED | `app.py` `_on_catalog_picked` imports `UNRESOLVED` from `cognitive.base` and passes `self._pending_key if self._pending_key is not None else UNRESOLVED` instead of a stale `None`. `tests/tui/test_secret_leak.py::test_second_connection_test_uses_unresolved` passes |

**Score:** 9/9 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/agent86/tui/screens/key_entry.py` | `event.stop()` before dismiss | VERIFIED | Line 49, first statement of `on_input_submitted` |
| `src/agent86/tui/screens/provider_manager.py` | `CatalogPickerModal.on_input_submitted` consumes its own event | VERIFIED | Line 156, `event.stop()` |
| `src/agent86/tui/app.py` | `on_input_submitted` guarded to `#prompt` only; `UNRESOLVED` pass-through | VERIFIED | Lines 126, 146-150 (`event.input.id != "prompt"` guard on two handlers); line 328 (`UNRESOLVED` pass-through) |
| `src/agent86/cli.py` | Typer configured to never render frame locals | VERIFIED | Line 53, `pretty_exceptions_show_locals=False` |
| `src/agent86/secrets.py` | `redact()` exported | VERIFIED | Line 35 `def redact`, in `__all__` |
| `src/agent86/cognitive/base.py` | `provider_for_ref` converts any escaping exception to a redacted `ProviderError` | VERIFIED | Lines 117-151, `except Exception as exc` branch uses `redact()` and `raise ... from None` |
| `src/agent86/cognitive/capabilities.py` | Per-model sampling-param capability seam | VERIFIED | `SAMPLING_PARAMS`, `supports_sampling_params`, `apply_sampling_params`, `mark_sampling_unsupported`, `is_sampling_rejection` all present and exported |
| `src/agent86/cognitive/anthropic_provider.py` | Sampling params gated + one-shot retry; SDK-version guard | VERIFIED | `apply_sampling_params` used in `stream()` (line 164); self-correction on `is_sampling_rejection` (lines 180-183); `_MIN_ANTHROPIC_VERSION` guard (lines 28-78) |
| `src/agent86/cognitive/openai_provider.py` | Same sampling-param seam, behavior-identical | VERIFIED | Line 123, `apply_sampling_params` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `KeyEntryModal.on_input_submitted` | modal-local dismiss, never the App | `event.stop()` | WIRED | Confirmed by reading the handler; regression test proves no transcript append / no turn dispatch |
| `Agent86App.on_input_submitted` | `#prompt` Input only | `event.input.id != "prompt": return` guard | WIRED | Two call sites guarded (lines 126, 146-150) |
| `_on_catalog_picked` | `ConnectionTestModal` -> `provider_for_ref` | `UNRESOLVED` sentinel pass-through | WIRED | `cognitive/base.py` treats `UNRESOLVED` (not `None`) as "resolve from env/keyring" |
| `provider_for_ref` | `agent86.secrets.redact` | except-clause re-raise with `from None` | WIRED | `cognitive/base.py:141-151` |
| `AnthropicProvider.stream()` | `capabilities.apply_sampling_params` | direct call at kwargs-construction time | WIRED | Line 164; also drives the retry path via `is_sampling_rejection`/`mark_sampling_unsupported` |
| `AnthropicProvider.__init__` | `run_repl`'s `except ProviderError` branch | `ProviderError` raised before `anthropic.Anthropic(**kwargs)` | WIRED | Version guard fires before SDK client construction; `run_repl`'s existing catch is untouched and now reachable for this failure mode too |

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SEC-01 | 03-01, 03-02, 03-03, 03-05, 03-06, 03-09, 03-10, 03-11 | API keys stored/read via OS keyring; env precedence; no plaintext secret in config or UI/error output | SATISFIED | Original precedence/write-guard logic unchanged; UAT gaps 1 and the D-10 traceback leak (gap 2b) closed by 03-10/03-11, both independently re-verified above |
| MODEL-01 | 03-01, 03-04, 03-05, 03-06, 03-08, 03-09, 03-10, 03-12, 03-13 | List/switch/add/test providers & models in-app, live test before saving, and the selected model actually completes a turn | SATISFIED | Original chain unchanged; UAT gaps 2 (opaque SDK crash), 4 (stale keyring resolution), and 5 (temperature 400) closed by 03-13, 03-10, 03-12 respectively, all independently re-verified above |
| MODEL-02 | 03-01, 03-03, 03-07, 03-09 | Config written back non-destructively, comments preserved, user default / project option | SATISFIED | Unchanged since initial verification; UAT test 2 (real user config) passed |

REQUIREMENTS.md's Traceability table (lines 71-73) now correctly reads "Complete" for all three
rows — the staleness flagged in the initial verification has been resolved (matches the top-of-file
checkbox list, which was already correct). No orphaned requirements: REQUIREMENTS.md maps exactly
SEC-01/MODEL-01/MODEL-02 to Phase 3 and all three appear in at least one plan's `requirements:`
frontmatter field (03-01 through 03-13).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | No TODO/FIXME/placeholder/stub-return patterns found in any of the gap-closure files (`key_entry.py`, `provider_manager.py`, `app.py`, `cli.py`, `secrets.py`, `cognitive/base.py`, `cognitive/capabilities.py`, `cognitive/anthropic_provider.py`, `cognitive/openai_provider.py`) | — | none |

Full test suite: **341 passed**, up from 275 at initial verification (66 new tests: 6 for gaps
1/4 in `tests/tui/test_secret_leak.py`, 10 for the traceback leak in
`tests/unit/test_secret_traceback.py`, 14 in `tests/unit/test_guardrails.py`, 26 for the
sampling-param gate in `tests/unit/test_capabilities.py`, 10 for the SDK-version guard in
`tests/unit/test_anthropic_sdk_guard.py`). No regressions against the 4 originally-verified
success criteria.

### Human Verification Required

See `human_verification` in the frontmatter:

1. Real Windows Credential Manager end-to-end round-trip (add key -> store -> restart -> resolve
   -> clear), this time exercising the fixed flow (no echo, no SDK crash, no temperature 400, no
   stale-keyring miss on retest) together in one live session — the automated tests prove each
   fix in isolation but the original UAT session is the only prior evidence of the combined flow,
   and that session predates the fixes.
2. Live Groq `/v1/models` schema confirmation — unchanged, still blocked on a missing
   `GROQ_API_KEY` in this environment (not a code defect; `03-HUMAN-UAT.md` test 3 still marked
   `blocked`).

Comment-preservation against the real `~/.agent86/config.toml` (originally human-verification item
2) is no longer listed here — `03-HUMAN-UAT.md` test 2 already passed during the prior UAT session
and nothing in the gap-closure plans touched `config_writer.py` or `save_diff.py`.

### Gaps Summary

No functional gaps remain. All 5 UAT-diagnosed blockers (transcript/turn leak, opaque Anthropic
SDK crash, traceback secret leak, unconditional `temperature` 400, stale keyring resolution on
retest) are closed by genuine, tested source changes in plans 03-10 through 03-13 — verified here
against the actual code and passing regression tests, not against SUMMARY.md claims. The original
4 success criteria remain verified with no regressions. `03-HUMAN-UAT.md`'s Gaps section has been
updated in place: all 5 entries now carry `status: resolved` with `resolved_by`/`resolution_evidence`
fields pointing at the specific commits and tests. The frontmatter `status` there was updated from
`diagnosed` to `resolved`. Status here is `human_needed` rather than `passed` only because two
items remain inherently outside automated reach: the combined live Credential Manager session
(recommended as a final confidence check on the fixed flow) and the Groq live-schema check
(unchanged, blocked on a missing API key, not a code defect).

---

_Verified: 2026-08-06T03:11:21Z_
_Verifier: Claude (gsd-verifier)_
