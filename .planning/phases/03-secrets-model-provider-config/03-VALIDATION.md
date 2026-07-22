---
phase: 3
slug: secrets-model-provider-config
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-21
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `03-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.2+ with pytest-asyncio (auto mode) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `testpaths = ["tests"]`) |
| **Quick run command** | `pytest tests/unit/test_secrets.py tests/unit/test_config_writer.py tests/unit/test_catalog.py tests/unit/test_providers_key_seam.py -q` (backend tasks) / `pytest tests/tui -q` (TUI tasks) |
| **Full suite command** | `pytest -q` |
| **Estimated runtime** | ~30 seconds full suite (196 tests today, expected ~215 after this phase) |

Textual modals are tested headlessly via `App.run_test()` / `Pilot`, following the `_PickerHost`
pattern in `tests/tui/test_pickers.py` and the full-app fake-provider pattern in
`tests/tui/test_app.py` / `tests/support.py`. **No test may touch the real OS keychain or make a
real network call** — keyring is monkeypatched at the `agent86.secrets` module boundary, and
catalog fetches / connection tests run against fakes.

---

## Sampling Rate

- **After every task commit:** backend-only tasks → `pytest tests/unit/test_secrets.py tests/unit/test_config_writer.py tests/unit/test_catalog.py tests/unit/test_providers_key_seam.py -q`; TUI-touching tasks → `pytest tests/tui -q`
- **After every plan wave:** `pytest -q` (full suite)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Req | Behavior | Test Type | Automated Command | File Exists | Status |
|-----|----------|-----------|-------------------|-------------|--------|
| SEC-01 | `resolve_api_key` returns env value when set, ignoring keyring | unit | `pytest tests/unit/test_secrets.py::test_env_wins_over_keyring -x` | ❌ W0 | ⬜ pending |
| SEC-01 | Falls back to keyring when env unset (keyring monkeypatched) | unit | `pytest tests/unit/test_secrets.py::test_keyring_fallback -x` | ❌ W0 | ⬜ pending |
| SEC-01 | Returns `None` silently when keyring raises/absent; no exception propagates | unit | `pytest tests/unit/test_secrets.py::test_keyring_unavailable_silent -x` | ❌ W0 | ⬜ pending |
| SEC-01 | Written TOML contains no plaintext secret — only `api_key_env` names | unit | `pytest tests/unit/test_config_writer.py::test_no_plaintext_secret_in_output -x` | ❌ W0 | ⬜ pending |
| SEC-01 | Providers still raise `ProviderError` with preserved wording when no key resolves | unit | `pytest tests/unit/test_providers_key_seam.py::test_provider_error_message_preserved -x` | ❌ W0 | ⬜ pending |
| SEC-01 | Keyless local providers (`api_key_env=None`) ignore stray keyring entries | unit | `pytest tests/unit/test_providers_key_seam.py::test_keyless_provider_ignores_keyring -x` | ❌ W0 | ⬜ pending |
| MODEL-01 | Each provider's catalog fetch normalizes a fixture response into `(ref, label)` | unit | `pytest tests/unit/test_catalog.py -x` | ❌ W0 | ⬜ pending |
| MODEL-01 | Catalog fetch failure falls back to free-text entry — never a dead end | unit | `pytest tests/unit/test_catalog.py::test_fetch_failure_falls_back -x` | ❌ W0 | ⬜ pending |
| MODEL-01 | `/config model`: selecting a no-key provider chains into key entry | integration (Pilot) | `pytest tests/tui/test_provider_manager.py::test_no_key_provider_chains_to_key_entry -x` | ❌ W0 | ⬜ pending |
| MODEL-01 | Connection test success/failure/timeout all resolve without hanging | integration (Pilot) | `pytest tests/tui/test_connection_test.py -x` | ❌ W0 | ⬜ pending |
| MODEL-01 | Failed test blocks default Save; "Save anyway" override works | integration (Pilot) | `pytest tests/tui/test_provider_manager.py::test_save_anyway_override -x` | ❌ W0 | ⬜ pending |
| MODEL-01 | Type-to-filter narrows a long catalog | integration (Pilot) | `pytest tests/tui/test_provider_manager.py::test_catalog_filter_narrows -x` | ❌ W0 | ⬜ pending |
| MODEL-02 | tomlkit write preserves hand-written comments/formatting | unit | `pytest tests/unit/test_config_writer.py::test_comments_preserved_roundtrip -x` | ❌ W0 | ⬜ pending |
| MODEL-02 | Write targets user scope by default, project scope when chosen | unit | `pytest tests/unit/test_config_writer.py::test_scope_selection -x` | ❌ W0 | ⬜ pending |
| MODEL-02 | Diff preview matches the actual before/after write | integration (Pilot) | `pytest tests/tui/test_save_diff.py::test_diff_matches_actual_write -x` | ❌ W0 | ⬜ pending |
| MODEL-02 (SC4) | Switching applies immediately via `Harness.set_model`; persisting default is separate | integration (Pilot) | `pytest tests/tui/test_provider_manager.py::test_switch_is_immediate_persist_is_separate -x` | ❌ W0 | ⬜ pending |
| D-22 | `agent86.cli` import does not import `keyring`/`tomlkit` | unit | `pytest tests/tui/test_lazy_import.py -x` | ✅ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_secrets.py` — SEC-01 precedence + silent degradation. Monkeypatch
      `get_password`/`set_password`/`delete_password`/`get_keyring` **at the `agent86.secrets`
      module boundary** — never import real keyring backends in tests.
- [ ] `tests/unit/test_config_writer.py` — MODEL-02 tomlkit round-trip, comment preservation,
      scope selection, no-plaintext-secret assertion.
- [ ] `tests/fixtures/config_with_comments.toml` — a hand-commented TOML fixture so round-trip
      fidelity is proven concretely, not by asserting on tomlkit internals.
- [ ] `tests/unit/test_catalog.py` + fixture JSON payloads for all five endpoint shapes
      (OpenAI, Groq, OpenRouter, Anthropic, Ollama). Mock `httpx` — no real endpoints.
- [ ] `tests/unit/test_providers_key_seam.py` — `require_key`/keyless-endpoint regression and the
      preserved-`ProviderError`-message assertion. (Check first whether an existing
      `tests/unit/test_cognitive*.py` should be extended instead of adding a new file.)
- [ ] `tests/tui/test_provider_manager.py`, `tests/tui/test_connection_test.py`,
      `tests/tui/test_save_diff.py` — follow the `_PickerHost` / `run_test()` / `Pilot` shape in
      `tests/tui/test_pickers.py` and `tests/tui/test_app.py`.
- [ ] Extend `tests/tui/test_lazy_import.py` with `keyring` / `tomlkit` assertions alongside the
      existing `textual` assertion.
- [ ] Framework install: **none** — pytest and pytest-asyncio are already dev dependencies.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real store → retrieve → clear cycle against Windows Credential Manager | SEC-01 | Monkeypatched unit tests cannot prove `WinVaultKeyring` behavior or its payload size limit (RESEARCH Pitfall 3) | In Windows Terminal: launch the TUI, `/config model`, add a key for a test provider, confirm it appears in Credential Manager under service `agent86`, restart the app and confirm the key still resolves, then clear it and confirm it is gone |
| Comment preservation in the user's real `~/.agent86/config.toml` | MODEL-02 | Fixture round-trip proves the mechanism; only a real user config proves the integration | Back up `~/.agent86/config.toml`, add a model via the manager, diff before/after and confirm every hand-written comment survived |
| Live catalog fetch against OpenRouter and Groq | MODEL-01 | RESEARCH rates these two response schemas MEDIUM/LOW confidence — fixtures are inferred, not captured from a live call | Run `curl https://openrouter.ai/api/v1/models` and the Groq equivalent, confirm the normalizer's field assumptions, and update fixtures if the shape differs |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-21 (gsd-plan-checker: VERIFICATION PASSED, Dimension 8 PASS)
