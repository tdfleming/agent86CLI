# Phase 4: MCP Config UI - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-06
**Phase:** 04-mcp-config-ui
**Areas discussed:** Add-server input flow, Enable/disable + removal, Live apply vs restart,
Test / tool listing / auth

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Add-server input flow | Guided form vs JSON paste; nothing collects command/args/env/url/headers today | ✓ |
| Enable/disable + removal | No `enabled` field on MCPServerConfig; config_writer has no delete op | ✓ |
| Live apply vs restart | MCPManager.start() runs once at Harness construction | ✓ |
| Test, tool listing & auth | What the test shows; where a bearer token lives vs SEC-01 | ✓ |

**User's choice:** All four.

---

## Add-server input flow

### Q1 — How should a user enter a new MCP server's details?

| Option | Description | Selected |
|--------|-------------|----------|
| JSON paste, primary (recommended) | Textarea parsed into MCPServerConfig; guided form secondary | |
| Guided form only | Transport first, then per-transport fields | |
| Both, equal footing | "Add from JSON" and "Add manually" as peer entries | ✓ |

**User's choice:** Both, equal footing.
**Notes:** More surface to build and test, but neither path is a fallback for the other. → D-01

### Q2 — How should args/env/headers be captured in the guided path?

| Option | Description | Selected |
|--------|-------------|----------|
| Single line, shell-ish split (recommended) | One Command field split with shlex | ✓ |
| Separate repeating rows | Add/remove row list per arg, key=value rows for env/headers | |
| Command line + key=value textarea | Shell-ish command plus a small multiline KEY=value box | |

**User's choice:** Single line, shell-ish split.
**Notes:** Matches how commands are copied from a README; avoids a repeating-row widget. → D-03

### Q3 — Where does the server name come from?

| Option | Description | Selected |
|--------|-------------|----------|
| User types it, collision blocks (recommended) | Required Name field; collision refuses to continue | ✓ |
| User types it, collision = edit | Colliding name pre-fills and overwrites | |
| Suggested, then editable | Derived from command or URL host | |

**User's choice:** User types it, collision blocks.
**Notes:** No silent overwrite of a working server. → D-04

### Q4 — Which JSON shapes should the paste path accept?

| Option | Description | Selected |
|--------|-------------|----------|
| Bare server object + wrapped (recommended) | Both `{...}` and `{"mcpServers": {...}}` | ✓ |
| Bare server object only | Inner object only | |
| Wrapped `mcpServers` map only | Full form only; permits multi-server import | |

**User's choice:** Bare server object + wrapped. → D-02

---

**Continue check:** "More questions" — user chose to keep going on this area.

### Q5 — How should validation failures surface?

| Option | Description | Selected |
|--------|-------------|----------|
| Inline, stay in the form (recommended) | Validator's message under the fields; Continue disabled | ✓ |
| Validate on Continue, error line | Error screen with Back button | |
| Live per-field as you type | Per-field markers on every keystroke | |

**User's choice:** Inline, stay in the form.
**Notes:** Mirrors SaveDiffModal. Per-field validation was flagged as drift-prone since
MCPServerConfig validates the whole object at once. → D-05

### Q6 — Explicit transport picker, or inferred?

| Option | Description | Selected |
|--------|-------------|----------|
| Inferred, overridable for remote (recommended) | command→stdio, url→http; http/sse toggle only when a url is present | ✓ |
| Explicit transport picker first | RadioSet gates which fields render | |
| Fully inferred, no override | url always means streamable http | |

**User's choice:** Inferred, overridable for remote.
**Notes:** Rejected fully-inferred because an SSE-only server would be unreachable from the UI. → D-06

### Q7 — Edit existing servers, or only add and remove?

| Option | Description | Selected |
|--------|-------------|----------|
| Edit reuses the add form (recommended) | Pre-filled form; diff over that server's keys | ✓ |
| Add and remove only | Editing means remove-then-re-add | |
| Edit, but no rename | Fields editable in place, name locked | |

**User's choice:** Edit reuses the add form.
**Notes:** Phase 3 deferred provider editing as "only if it falls out naturally" (D-23); here it
does, since the form already exists. → D-07

### Q8 — What does each list row show before anything is tested?

| Option | Description | Selected |
|--------|-------------|----------|
| Static config facts only (recommended) | Name, transport, endpoint, enabled/disabled | ✓ |
| Live status on open | Connect to every server when the modal opens | |
| Static, plus last-test result | Config facts plus this session's remembered pass/fail | |

**User's choice:** Static config facts only.
**Notes:** Opening a menu must not spawn every stdio subprocess or hang on a dead remote. → D-08

**Continue check:** "Next area".

---

## Enable/disable + removal

### Q1 — How should a disabled server be represented in config.toml?

| Option | Description | Selected |
|--------|-------------|----------|
| `enabled = true` field on the server (recommended) | New bool on MCPServerConfig; build_mcp skips falsy | ✓ |
| `[mcp] disabled = ["name"]` list | Single list on MCPConfig, no per-server schema change | |
| Comment out the block | tomlkit comments out the whole table | |

**User's choice:** `enabled = true` field on the server.
**Notes:** Comment-out was rejected because load_config could not see it, so the UI could not list
disabled servers at all. → D-09

### Q2 — What shape should the delete capability take in config_writer?

| Option | Description | Selected |
|--------|-------------|----------|
| Sentinel value in the same changes list (recommended) | `DELETE` sentinel in `plan_edit` | ✓ |
| Separate `deletions` parameter | `plan_edit(scope, changes, deletions=[...])` | |
| Separate `plan_delete` function | Parallel function returning its own ConfigEdit | |

**User's choice:** Sentinel value in the same changes list.
**Notes:** Keeps a combined change (delete A, disable B) to one diff and one write. → D-10

### Q3 — Confirm before a destructive removal?

| Option | Description | Selected |
|--------|-------------|----------|
| Diff preview is the confirmation (recommended) | Straight to SaveDiffModal, which shows the deleted block | ✓ |
| Explicit confirm, then diff | A "Remove server X?" dialog first | |
| Suggest disable instead | Remove path offers disable as the default | |

**User's choice:** Diff preview is the confirmation.
**Notes:** A separate yes/no before an explicit diff-confirm would be two prompts for one
action. → D-11

### Q4 — Should disabling also go through scope + diff + save?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — same flow, no exceptions (recommended) | Every write goes scope → diff → confirm | ✓ |
| Toggle writes immediately | Straight to user scope with a transcript note | |
| Batch toggles, one save | Several toggles, one combined diff | |

**User's choice:** Yes — same flow, no exceptions.
**Notes:** The first write that skips the diff would break Phase 3's D-16/D-17 guarantee. → D-12

**Continue check:** "Next area".

---

## Live apply vs restart

### Q1 — When do a new server's tools become available to the model?

| Option | Description | Selected |
|--------|-------------|----------|
| Reconnect just that server, mount its tools (recommended) | Per-server add path on MCPManager | ✓ |
| Restart the whole MCP manager | Close everything, re-run build_mcp | |
| Next launch, with a clear note | Config written, restart required | |

**User's choice:** Reconnect just that server, mount its tools.
**Notes:** Full restart would tear down healthy sessions; next-launch-only contradicts the
milestone's core value. → D-13

### Q2 — What happens to a removed/disabled server's already-mounted tools?

| Option | Description | Selected |
|--------|-------------|----------|
| Unmount immediately, close the session (recommended) | Symmetric with add; needs a ToolRegistry removal method | ✓ |
| Leave mounted until restart | Config updates, live session unchanged | |
| Unmount tools, leave the session open | Tools hidden, transport stays until exit | |

**User's choice:** Unmount immediately, close the session.
**Notes:** Otherwise the model could invoke a tool for a server the UI shows as removed. → D-14

### Q3 — How is the changed tool list communicated?

| Option | Description | Selected |
|--------|-------------|----------|
| Next turn picks it up, no notice to the model (recommended) | Specs read from the registry per turn | ✓ |
| Also inject a system note | Tell the model which tools appeared/vanished | |
| Only apply between turns, block during one | Queue registry mutations until a turn ends | |

**User's choice:** Next turn picks it up, no notice to the model.
**Notes:** Injection would be the first such message in the codebase; the block-during-turn option
may guard a state that can't occur, since the modal can't be open mid-turn. → D-15

### Q4 — Config write succeeded but the live mount failed. How does that read?

| Option | Description | Selected |
|--------|-------------|----------|
| Config saved, mount failed — say both (recommended) | Report both halves plus the error | ✓ |
| Roll back the config write | Treat it as one atomic operation | |
| Silent — note only in the server list | Row shows a failed state, no transcript output | |

**User's choice:** Config saved, mount failed — say both.
**Notes:** Rollback would discard a config the user explicitly confirmed; Phase 3's "Save anyway"
established that an unreachable endpoint is still worth saving. → D-16

**Continue check:** "Next area".

---

## Test, tool listing & auth

**Tension surfaced during scouting:** `config_writer._FORBIDDEN_LEAF_KEYS` blocks
`api_key`/`token`/`secret`/`key`/`password`, but a remote server's
`headers = { Authorization = "Bearer …" }` is not caught by that set. `MCPServerConfig` does no
`${VAR}` expansion today.

### Q1 — Where should a bearer token / secret env var live?

| Option | Description | Selected |
|--------|-------------|----------|
| Keyring + `${VAR}` reference in config (recommended) | Resolved at connect time, env first then keyring | ✓ |
| Env-var reference only, no keyring | `${VAR}` from os.environ and nothing else | |
| Allow plaintext in config, warn | Literal token on disk with a warning | |

**User's choice:** Keyring + `${VAR}`-style reference in config.
**Notes:** Env-only would mean the TUI still can't store a secret, so "add a server" would require
leaving the app. Plaintext directly contradicts SEC-01. → D-17

### Q2 — How is the secret captured?

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse KeyEntryModal, chained (recommended) | Unresolved `${VAR}` chains into the existing masked modal | ✓ |
| A masked field inside the add form | One fewer screen | |
| No capture — tell the user to set the env var | Nothing to build | |

**User's choice:** Reuse KeyEntryModal, chained.
**Notes:** One secret-entry widget, already hardened by plans 03-10/03-11. → D-18

### Q3 — What does the test result screen show?

| Option | Description | Selected |
|--------|-------------|----------|
| Count plus a scrollable tool list (recommended) | Names and descriptions in a scrollable pane | ✓ |
| Count only | "Connected — 12 tools." | |
| Count, names on demand | Expand action for the list | |

**User's choice:** Count plus a scrollable tool list.
**Notes:** Seeing names is what proves the right server got wired up. → D-19

### Q4 — Timeout, given a first-run `npx` download?

| Option | Description | Selected |
|--------|-------------|----------|
| Longer timeout (~30s), same shape (recommended) | Worker thread + hard timeout, sized for a cold fetch | ✓ |
| Keep 15s, identical to Phase 3 | One constant across both test modals | |
| 30s with visible elapsed time | Longer budget plus a running counter | |

**User's choice:** Longer timeout (~30s), same shape.
**Notes:** MCPManager.start() already budgets 30s. A 15s timeout would fail honest first runs and
push users to "Save anyway". → D-20

**Final check:** "I'm ready for context".

---

## Claude's Discretion

Areas left to Claude during planning/implementation (D-21..D-27): the exact command surface
(`/config mcp` expected, per Phase 3's D-15 pattern); modal composition, widget ids, CSS and screen
count; per-server teardown mechanics on MCPManager's background loop (today one shared
`AsyncExitStack`); duplicate tool-name handling on remount; where `${VAR}` expansion lives and how
far it applies; whether the `[mcp] enabled` master switch is exposed; whether project-scope
shadowing needs UI treatment.

## Deferred Ideas

`agent86 mcp add`/`remove` CLI commands; per-server tool allow/deny lists; OAuth / dynamic client
registration for remote servers; live status polling in the list; remembering per-row test results
across the session; rolling back a write on mount failure (rejected); plaintext tokens in config
(rejected); packaging/lazy-import hardening (Phase 5); theming (v2).
