---
status: partial
phase: 03-secrets-model-provider-config
source: [03-VERIFICATION.md]
started: 2026-08-05
updated: 2026-08-05
---

## Current Test

[awaiting human testing]

## Tests

### 1. Real OS keyring round-trip in Windows Credential Manager
expected: Running `agent86`, opening `/config model`, adding a provider and entering an API key
stores that key in the real Windows Credential Manager (visible under Control Panel → Credential
Manager → Windows Credentials as an `agent86`-scoped entry). Restarting `agent86` resolves the key
back from the keyring without re-prompting, and `agent86 config` shows the Key column as stored.
Deleting the credential makes the key fall back to the environment variable (or show as missing)
rather than crashing. Automated tests mock the keyring backend, so only a real run proves the
Credential Manager integration.
result: [pending]

### 2. Comment preservation against the user's actual ~/.agent86/config.toml
expected: Saving a change from the model-config modal against the real `~/.agent86/config.toml`
(not the test fixture) preserves all existing comments, key ordering, and formatting — the
SaveDiffModal preview matches the actual on-disk diff exactly, and nothing outside the changed
lines moves. The project-scope option writes to the project config instead when selected.
result: [pending]

### 3. Live Groq catalog schema check
expected: With a real `GROQ_API_KEY` set, the catalog fetch against Groq's live `/v1/models`
endpoint returns models that normalize correctly into the picker. Groq's schema was the one
provider that could not be confirmed against a live call during execution (no API key available;
the docs page is client-rendered). OpenRouter's schema was confirmed live and matches its fixture.
If Groq's live response diverges from `tests/fixtures/catalog/groq_models.json`, the fixture and
normalizer need updating.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
