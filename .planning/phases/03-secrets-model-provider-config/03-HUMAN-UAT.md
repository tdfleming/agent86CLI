---
status: diagnosed
phase: 03-secrets-model-provider-config
source: [03-VERIFICATION.md]
started: 2026-08-05
updated: 2026-08-05
---

## Current Test

[testing complete — 1 passed, 1 issue (5 gaps diagnosed), 1 blocked on a third-party prerequisite]

## Tests

### 1. Real OS keyring round-trip in Windows Credential Manager
expected: Running `agent86`, opening `/config model`, adding a provider and entering an API key
stores that key in the real Windows Credential Manager (visible under Control Panel → Credential
Manager → Windows Credentials as an `agent86`-scoped entry). Restarting `agent86` resolves the key
back from the keyring without re-prompting, and `agent86 config` shows the Key column as stored.
Deleting the credential makes the key fall back to the environment variable (or show as missing)
rather than crashing. Automated tests mock the keyring backend, so only a real run proves the
Credential Manager integration.
result: issue
reported: "Screenshots show the API key echoed in plaintext in the transcript, `saving anyway
despite: Client.__init__() got an unexpected keyword argument 'proxies'`, and a follow-up
connection test failing with `No Anthropic API key found` despite the key having just been stored
in the keyring."
severity: blocker

### 2. Comment preservation against the user's actual ~/.agent86/config.toml
expected: Saving a change from the model-config modal against the real `~/.agent86/config.toml`
(not the test fixture) preserves all existing comments, key ordering, and formatting — the
SaveDiffModal preview matches the actual on-disk diff exactly, and nothing outside the changed
lines moves. The project-scope option writes to the project config instead when selected.
result: pass

### 3. Live Groq catalog schema check
expected: With a real `GROQ_API_KEY` set, the catalog fetch against Groq's live `/v1/models`
endpoint returns models that normalize correctly into the picker. Groq's schema was the one
provider that could not be confirmed against a live call during execution (no API key available;
the docs page is client-rendered). OpenRouter's schema was confirmed live and matches its fixture.
If Groq's live response diverges from `tests/fixtures/catalog/groq_models.json`, the fixture and
normalizer need updating.
result: blocked
blocked_by: third-party
reason: "User has no Groq API key. Confirmed independently during this session that GROQ_API_KEY is
unset in the environment. This is the same prerequisite gap that prevented live confirmation during
execution — not a defect, and not resolvable without a Groq account."
unblocks_when: "A GROQ_API_KEY is available. Re-run `/gsd:verify-work 03` at that point; nothing
else about this test needs to change."
risk_if_never_tested: "Groq's `/v1/models` response shape stays unconfirmed against a live call.
The normalizer and `tests/fixtures/catalog/groq_models.json` were built from the documented schema,
so a divergence would surface as Groq models missing or malformed in the picker — degraded catalog
for one provider, not a crash, and the free-text `provider:model` fallback (03-08) still lets a user
select a Groq model by hand. OpenRouter, which shares the OpenAI-compatible catalog path, was
confirmed live and matches its fixture, which is partial evidence the shared normalizer is sound."

## Summary

total: 3
passed: 1
issues: 1
pending: 0
skipped: 0
blocked: 1
gaps: 5

## Notes

The keyring layer itself is **proven working** — verified live against the real Windows
Credential Manager backend during this session:

```
backend: keyring.backends.Windows
keyring_available: True
has_stored_key('anthropic'): True
resolve_api_key('anthropic','ANTHROPIC_API_KEY') -> FOUND len=108
```

So SEC-01 storage/retrieval is sound. All three gaps below are in the *callers* around it, not
in `agent86.secrets`.

## Gaps

- truth: "The entered API key is never echoed, logged to the transcript, or rendered in plaintext (D-10)"
  status: failed
  reason: "User reported: the raw sk-ant-... key is visible in the transcript after submitting it in the key-entry modal"
  severity: blocker
  test: 1
  root_cause: "`KeyEntryModal.on_input_submitted` (src/agent86/tui/screens/key_entry.py:45) never calls `event.stop()`, so the `Input.Submitted` message bubbles past the dismissed modal up to `Agent86App.on_input_submitted` (src/agent86/tui/app.py:146), which does not filter on `event.input.id` and therefore treats the key as a typed prompt line — echoing it to the transcript and dispatching it as a real turn to the model. No modal in src/agent86/tui/screens/ calls event.stop()."
  artifacts:
    - path: "src/agent86/tui/screens/key_entry.py"
      issue: "on_input_submitted dismisses without event.stop(); message bubbles to the App"
    - path: "src/agent86/tui/app.py"
      issue: "on_input_submitted at line 146 accepts Input.Submitted from any Input, not just #prompt"
  missing:
    - "Call event.stop() in KeyEntryModal.on_input_submitted before dismiss()"
    - "Guard Agent86App.on_input_submitted with `if event.input.id != 'prompt': return`"
    - "Audit the other modals (model_picker, provider_manager, save_diff) for the same bubbling leak"
    - "Regression test: submitting in KeyEntryModal must not append to the transcript or start a turn"
  debug_session: ""

- truth: "The connection test returns a pass/fail verdict for the provider, not an SDK crash"
  status: failed
  reason: "User reported: saving anyway despite: Client.__init__() got an unexpected keyword argument 'proxies'"
  severity: blocker
  test: 1
  root_cause: "Installed `anthropic` was 0.25.9 against `httpx` 0.28.1. anthropic <0.28 passes `proxies=` to `httpx.Client(...)` (anthropic/_base_client.py:723), and httpx removed that parameter in 0.28. pyproject.toml:26 already declares the correct floor (`anthropic = [\"anthropic>=0.40\"]`), so the environment simply had a stale pin — held there by an unrelated `anthropic-tools 1.0.7`, which requires `anthropic<0.26.0` and shares the same global site-packages. `anthropic-tools` is referenced nowhere in agent86's src/, tests/, or pyproject.toml."
  escalation: "Not merely a connection-test failure. Once `model.default` became `anthropic:claude-opus-5` and the key resolved from the keyring, `_Repl.__init__` -> `ModelRouter.default_provider()` -> `AnthropicProvider.__init__` ran at STARTUP, so `agent86` could not boot at all (full traceback from ui/repl.py:427)."
  status_note: "RESOLVED IN ENV during this UAT session: upgraded to anthropic 0.120.2; `anthropic.Anthropic()` now constructs against httpx 0.28.1. The code-level guard below is still outstanding."
  artifacts:
    - path: "pyproject.toml"
      issue: "anthropic>=0.40 declared as an optional extra only; nothing enforces the floor at runtime or in CI"
    - path: "src/agent86/cognitive/anthropic_provider.py"
      issue: "no version guard — an incompatible SDK surfaces as a raw TypeError from deep inside httpx"
  missing:
    - "DONE: pip install -U 'anthropic>=0.40' (now 0.120.2)"
    - "Add an explicit SDK-version check in AnthropicProvider that raises a ProviderError naming the fix, the way the missing-package path at anthropic_provider.py:34 already does"
    - "Fail soft at startup: a provider that cannot be constructed should degrade to a clear 'Cannot start' message (repl.py:428 already catches ProviderError — a TypeError bypasses it) rather than dumping a traceback"
  debug_session: ""

- truth: "An API key is never rendered in plaintext anywhere in the UI or its error output (D-10)"
  status: failed
  reason: "The Rich traceback from the startup crash rendered the full sk-ant-... key in the `locals` panels of four separate frames (provider_for_ref, AnthropicProvider.__init__, anthropic._client.__init__, _base_client.__init__)"
  severity: blocker
  test: 1
  root_cause: "Rich's traceback handler renders local variables by default, and `api_key` is an ordinary local in `provider_for_ref` (cognitive/base.py:87) and `AnthropicProvider.__init__` (anthropic_provider.py:49). Any unhandled exception below the key-resolution point prints the secret to the terminal — and into any log, screenshot, or pasted bug report. This is a second, independent leak path from the transcript-echo gap above: fixing event.stop() does not fix this."
  artifacts:
    - path: "src/agent86/cli.py"
      issue: "Rich traceback rendering enabled with show_locals (or Typer's default pretty exceptions) — dumps secrets on any crash"
    - path: "src/agent86/cognitive/base.py"
      issue: "resolved api_key held as a plain local, visible in every downstream frame's locals"
  missing:
    - "Disable local-variable rendering in the traceback handler (Typer: pretty_exceptions_show_locals=False), or install a scrubbing excepthook"
    - "Regression test: force a provider construction failure with a known key and assert the key string never appears in captured stderr"
  debug_session: ""

- truth: "Selecting a model through /config model produces a working turn against that model"
  status: failed
  reason: "User reported: error: Anthropic API error: Error code: 400 - {'type': 'invalid_request_error', 'message': '`temperature` is deprecated this model.'} on a plain `hello` turn against anthropic:claude-opus-5"
  severity: blocker
  test: 1
  root_cause: "`AnthropicProvider.stream()` (src/agent86/cognitive/anthropic_provider.py:113) puts `temperature` into the request kwargs unconditionally, sourced from `CompletionRequest.temperature` which defaults to 0.0 (src/agent86/types.py:158) and is set explicitly at orchestration/loop.py:178 and agents/subagent.py:74. `temperature`, `top_p`, and `top_k` were REMOVED on Claude Opus 5 (and Opus 4.8/4.7, Sonnet 5, Fable 5) — the API rejects them with a 400 and there is no replacement value; the parameter must be omitted entirely and behavior steered by prompting. Confirmed against the bundled claude-api reference, not inferred from the error text."
  boundary_note: "This defect lives in the cognitive tier, which 03-VERIFICATION.md records as outside Phase 3's boundary. It surfaced here because Phase 3's whole purpose is letting the user select a model — and the model it now selects by default cannot complete a turn. Fixing it is required for Phase 3's success criteria to hold in practice, even though the file is out of scope."
  artifacts:
    - path: "src/agent86/cognitive/anthropic_provider.py"
      issue: "line 113 sends `temperature` unconditionally; rejected with 400 on Opus 5 / Opus 4.8 / Opus 4.7 / Sonnet 5 / Fable 5"
    - path: "src/agent86/types.py"
      issue: "CompletionRequest.temperature defaults to 0.0 — always truthy as a field, so a naive `if request.temperature` guard would still send 0.0"
    - path: "src/agent86/cognitive/openai_provider.py"
      issue: "line 117 does the same for OpenAI-compatible endpoints — correct for OpenAI/Groq/OpenRouter today, but the same per-model gating pattern should be applied deliberately rather than by accident"
  missing:
    - "Omit `temperature` from the Anthropic request kwargs for models that reject it (Opus 5, Opus 4.8, Opus 4.7, Sonnet 5, Fable 5) rather than passing it through"
    - "Prefer a per-model capability check over a hardcoded model-name list, so newly released models do not silently regress"
    - "Regression test: assert the constructed Anthropic kwargs contain no `temperature`/`top_p`/`top_k` for an Opus 5 ref"
    - "Check the same call path in complete() as well as stream() — the connection test uses complete()"
  debug_session: ""

- truth: "A key stored in the OS keyring is resolved on subsequent connection tests without re-prompting"
  status: failed
  reason: "User reported: second test showed 'No Anthropic API key found. Set the ANTHROPIC_API_KEY environment variable or store a key in the OS keyring via /config model.' 72 seconds after the key was stored"
  severity: blocker
  test: 1
  root_cause: "`Agent86App._on_test_done` (src/agent86/tui/app.py:340) clears `self._pending_key = None` in its finally block. On the next pass through the flow `_on_catalog_picked` (app.py:320) passes that `None` straight into `ConnectionTestModal`, which forwards it to `provider_for_ref(..., api_key=None)`. Because `None is not UNRESOLVED` (src/agent86/cognitive/base.py:84), the keyring-resolution branch is skipped entirely and the provider falls through to the `if not api_key` error at anthropic_provider.py:44. The UNRESOLVED sentinel exists precisely for this case, but the TUI never uses it. Verified independently that the key IS present and resolvable in the keyring."
  artifacts:
    - path: "src/agent86/tui/app.py"
      issue: "passes api_key=None (meaning 'no new key entered') where UNRESOLVED (meaning 'go look it up') is required"
    - path: "src/agent86/cognitive/base.py"
      issue: "provider_for_ref silently treats None as an explicit empty key rather than a resolution request"
  missing:
    - "Pass UNRESOLVED instead of None when _pending_key is unset, in _on_catalog_picked / ConnectionTestModal"
    - "Regression test: run the /config model flow twice with a keyring-stored key; the second test must resolve without re-prompting"
  debug_session: ""
