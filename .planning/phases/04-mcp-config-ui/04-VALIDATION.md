---
phase: 4
slug: mcp-config-ui
status: approved
nyquist_compliant: true
wave_0_complete: false  # plan 04-01 owns it
created: 2026-08-06
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing suite: 341+ passing as of Phase 3 completion) |
| **Config file** | `pyproject.toml` — no separate `pytest.ini` |
| **Quick run command** | `pytest tests/unit/test_mcp.py tests/unit/test_config.py tests/unit/test_config_writer.py tests/unit/test_secrets.py tests/tui/test_mcp_manager.py -q` |
| **Full suite command** | `pytest -q` |
| **Estimated runtime** | ~10s quick / ~90s full |

---

## Sampling Rate

- **After every task commit:** Run the quick run command, scoped to touched modules
- **After every plan wave:** Run `pytest -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

> Populated by the planner — one row per task in every PLAN.md. Requirement column
> maps to MCP-01 or SEC-01.

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-T1 | 04-01 | 0 | MCP-01, SEC-01 | unit | `pytest tests/unit/test_secrets.py tests/unit/test_config_writer.py tests/unit/test_config.py tests/unit/test_mcp.py -q` | creates | ⬜ pending |
| 04-01-T2 | 04-01 | 0 | MCP-01 | integration | `pytest tests/integration/test_mcp_client.py -q` | extends | ⬜ pending |
| 04-01-T3 | 04-01 | 0 | MCP-01 | TUI | `pytest tests/tui/test_mcp_manager.py tests/tui/test_mcp_test_modal.py -q` | creates | ⬜ pending |
| 04-02-T1 | 04-02 | 1 | SEC-01 | unit | `pytest tests/unit/test_secrets.py -q && pytest tests/tui/test_lazy_import.py -q` | ✅ (04-01) | ⬜ pending |
| 04-02-T2 | 04-02 | 1 | SEC-01, MCP-01 | unit | `pytest tests/unit/test_config_writer.py -q && pytest tests/tui/test_save_diff.py tests/tui/test_lazy_import.py -q` | ✅ (04-01) | ⬜ pending |
| 04-03-T1 | 04-03 | 1 | MCP-01 | unit | `pytest tests/unit/test_config.py -q` | ✅ (04-01) | ⬜ pending |
| 04-03-T2 | 04-03 | 1 | MCP-01 | unit | `pytest tests/unit/test_mcp.py -k unregister -q && pytest tests/unit/test_tools.py tests/unit/test_loop.py -q` | ✅ (04-01) | ⬜ pending |
| 04-04-T1 | 04-04 | 2 | MCP-01 | integration | `pytest tests/unit/test_mcp.py tests/integration/test_mcp_client.py tests/integration/test_mcp_live.py -q` | ✅ (04-01) | ⬜ pending |
| 04-04-T2 | 04-04 | 2 | SEC-01 | unit | `pytest tests/unit/test_mcp.py -q && pytest tests/unit/test_secrets.py -q` | ✅ (04-01) | ⬜ pending |
| 04-04-T3 | 04-04 | 2 | MCP-01 | unit | `pytest tests/unit/test_config.py -k build_mcp -q && pytest tests/unit/test_mcp.py tests/unit/test_loop.py -q` | ✅ (04-01) | ⬜ pending |
| 04-05-T1 | 04-05 | 2 | MCP-01 | TUI | `pytest tests/tui/test_mcp_manager.py -k "rows or parse or build_manual or kv_list" -q` | ✅ (04-01) | ⬜ pending |
| 04-05-T2 | 04-05 | 2 | MCP-01 | TUI | `pytest tests/tui/test_mcp_manager.py -k "manager_ or spawns_no_subprocess" -q` | ✅ (04-01) | ⬜ pending |
| 04-05-T3 | 04-05 | 2 | MCP-01 | TUI | `pytest tests/tui/test_mcp_manager.py -q` | ✅ (04-01) | ⬜ pending |
| 04-06-T1 | 04-06 | 3 | MCP-01 | unit | `pytest tests/unit/test_loop.py -k ensure_mcp -q` | creates | ⬜ pending |
| 04-06-T2 | 04-06 | 3 | MCP-01 | unit | `pytest tests/unit/test_loop.py -q && pytest tests/unit/test_mcp.py tests/unit/test_tools.py -q` | creates | ⬜ pending |
| 04-07-T1 | 04-07 | 3 | MCP-01 | TUI | `pytest tests/tui/test_mcp_test_modal.py -k "timeout or failure or escape or overrides" -q` | ✅ (04-01) | ⬜ pending |
| 04-07-T2 | 04-07 | 3 | MCP-01, SEC-01 | TUI | `pytest tests/tui/test_mcp_test_modal.py -q` | ✅ (04-01) | ⬜ pending |
| 04-08-T1 | 04-08 | 4 | MCP-01 | TUI | `pytest tests/tui/test_commands.py tests/tui/test_palette.py -q && pytest tests/tui/test_mcp_manager.py -k registry -q` | ✅ (04-01) | ⬜ pending |
| 04-08-T2 | 04-08 | 4 | MCP-01, SEC-01 | TUI | `pytest tests/tui/test_mcp_manager.py -q && pytest tests/tui/test_app.py -q` | ✅ (04-01) | ⬜ pending |
| 04-08-T3 | 04-08 | 4 | MCP-01 | TUI | `pytest tests/tui/test_mcp_manager.py -q && pytest tests/tui/ -q` | ✅ (04-01) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Requirement → behavior coverage (from RESEARCH.md)

| Req | Behavior | Test Type | Command | File Exists |
|-----|----------|-----------|---------|-------------|
| MCP-01 (list) | Manager modal lists servers with transport/status; opening spawns no subprocess (D-08) | TUI | `pytest tests/tui/test_mcp_manager.py -k list -x` | ❌ W0 |
| MCP-01 (add stdio) | Add-from-JSON and add-manually both validate, test, and write on save | integration + TUI | `pytest tests/integration/test_mcp_client.py -k per_server -x` | ❌ W0 |
| MCP-01 (add sse/http) | Connection test enumerates tools before save over a real transport | integration (live) | `pytest tests/integration/test_mcp_live.py -x` | ✅ extend |
| MCP-01 (remove/disable) | Config updated non-destructively (comments preserved); live tools unmounted | unit | `pytest tests/unit/test_config_writer.py -k delete -x` · `pytest tests/unit/test_mcp.py -k unregister -x` | ❌ W0 |
| SEC-01 (D-17) | Literal secret under `headers.Authorization` / `env.TOKEN` rejected; `${VAR}` reference accepted | unit | `pytest tests/unit/test_config_writer.py -k forbidden_var_ref -x` | ❌ W0 |
| MCP-01 (D-23) | Adding server B while A runs, then stopping A, raises no cancel-scope `RuntimeError`; B's session intact | integration (live) | `pytest tests/integration/test_mcp_client.py -k independent_teardown -x` | ❌ W0 |
| MCP-01 (D-25) | `expand_var_refs` resolves env-first-then-keyring by var name; raises on neither | unit | `pytest tests/unit/test_secrets.py -k var_ref -x` | ❌ W0 |

---

## Wave 0 Requirements

- [ ] `tests/tui/test_mcp_manager.py` — new Pilot test module for the list/add/edit/remove modal chain, mirroring `tests/tui/test_provider_manager.py`
- [ ] `tests/tui/test_mcp_test_modal.py` — worker-thread + 30s-timeout + tool-list rendering, mirroring `tests/tui/test_connection_test.py`
- [ ] Extend `tests/unit/test_mcp.py` — `ToolRegistry.unregister`, `MCPManager.start_server`/`stop_server` against fakes (no real transport)
- [ ] Extend `tests/integration/test_mcp_client.py` — independent per-server teardown raises no cancel-scope error (**highest-value new test in the phase**; direct D-23 regression guard, uses `tests/integration/live_mcp_server.py`)
- [ ] Extend `tests/unit/test_config_writer.py` — `DELETE` sentinel round-trip (diff shows removed table, other comments preserved) + `${VAR}` exception to `_FORBIDDEN_LEAF_KEYS`
- [ ] Extend `tests/unit/test_secrets.py` — `find_var_refs` / `expand_var_refs` / `MissingSecretRef`
- [ ] Extend `tests/unit/test_config.py` — `MCPServerConfig.enabled` defaults True; `build_mcp` filters disabled servers

**Must stay green (regression guard, not new work):** `tests/tui/test_lazy_import.py` — Textual/keyring/tomlkit must not be imported on the `run` one-shot or `--plain` path.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end paste-JSON → inline validate → masked key prompt → connect → tool list → diff → save flow feels continuous | MCP-01 | Multi-modal chaining with a real subprocess; perceptual continuity is not assertable | Launch `agent86`, run `/config mcp`, add a real stdio server from a README-style JSON paste, confirm each step advances without a dead end |
| A hand-edited `config.toml` showing `enabled = false` reads as obviously meaningful | MCP-01 (D-09) | Readability judgment | Disable a server via the UI, open `config.toml`, confirm the one-line diff is self-explanatory |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner-approved 2026-08-06 — every task carries an <automated> verify; Wave 0 (04-01) precedes every implementation wave
