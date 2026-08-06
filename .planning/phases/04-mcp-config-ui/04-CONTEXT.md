# Phase 4: MCP Config UI - Context

**Gathered:** 2026-08-06
**Status:** Ready for planning

<domain>
## Phase Boundary

An in-app MCP management surface (**MCP-01**) that lists configured MCP servers, adds new ones,
edits and removes them, and enables/disables them — validating a server's connection and
enumerating its tools before the entry is written to config, and applying the change to the
running session.

**In scope:** An MCP manager modal reachable from the command registry; an add/edit form with two
peer entry paths (paste JSON / enter fields); a per-server `enabled` flag (net-new config field);
a delete capability in `config_writer` (net-new); a connection-test-and-enumerate-tools step
before save; live mount/unmount of a server's tools into the running registry; `${VAR}`-style
secret references for auth headers and stdio env, resolved env-first then keyring.

**Out of scope:** Packaging / lazy-import hardening and the plain-loop + `run --json` degradation
contract (Phase 5 — TUI-06); theming (v2 — POL-01). This phase does not change the cognitive
loop, the provider layer, or the model/provider config surfaces Phase 3 shipped. Editing MCP
servers from the non-interactive `agent86 mcp` Typer commands is not required — those stay
read-only (`list` / `tools`) unless it falls out for free.
</domain>

<decisions>
## Implementation Decisions

### Add / edit input flow
- **D-01:** The manager offers **two peer entry paths on equal footing** — "Add from JSON" and
  "Add manually". Neither is a fallback for the other.
- **D-02:** The JSON path accepts **both the bare server object** (`{"command": "npx", "args":
  [...]}`) **and the wrapped `{"mcpServers": {"name": {...}}}` form** — both are what users have on
  their clipboard from a server's README. The wrapped form supplies the server name; the bare form
  takes it from the Name field.
- **D-03:** In the manual path, **command + args are captured as one shell-ish line**
  (`npx -y @modelcontextprotocol/server-filesystem /tmp`) and split with `shlex` — not a repeating
  arg-row widget. Matches how commands are copied from a README.
- **D-04:** The **server name is typed by the user and is required**. A collision with an existing
  server **blocks** with a clear message — never a silent overwrite of a working server.
- **D-05:** **Validation errors surface inline, in the form** — the `MCPServerConfig` validator's
  own message renders under the fields, everything the user typed is preserved, and Continue is
  disabled until it parses. Mirrors `SaveDiffModal`, which renders `ConfigWriteError` and disables
  `#save-confirm` rather than crashing. Do not re-derive per-field validation rules; validate the
  whole object as the config validator already does.
- **D-06:** **`transport` is inferred** using the existing config rule (`command` → stdio, `url` →
  http). Because `sse` and `http` are indistinguishable from a URL alone, offer an **http/sse
  toggle only once a `url` is present**. No new inference logic; one decision, only when it is
  genuinely ambiguous.
- **D-07:** **Editing an existing server reuses the same form, pre-filled.** Selecting a server in
  the manager opens the add form with its current values; saving writes a diff over that server's
  keys. (Phase 3 deferred provider editing as "only if it falls out naturally" — D-23; here it
  does, since the form already exists.)
- **D-08:** The server list shows **static config facts only** — name, transport, endpoint, and
  enabled/disabled — extending the shape of the existing `agent86 mcp list` table with one column.
  Opening the manager must be instant and must **not** spawn any subprocess or open any transport.
  Live status is what the explicit test action is for.

### Enable / disable and removal
- **D-09:** A disabled server is represented by **`enabled: bool = True` on `MCPServerConfig`**
  (net-new field); `build_mcp` skips falsy ones. State lives in the server's own block, reads
  naturally in hand-edited TOML, and produces a one-line diff. Not a `[mcp] disabled = [...]` list,
  and not a commented-out table (which `load_config` could not see, so the UI could not list
  disabled servers at all).
- **D-10:** `config_writer` gains **delete via a module-level `DELETE` sentinel used in the same
  `changes` list** — `plan_edit(scope, [(["mcp","servers","foo"], DELETE)])`. One code path, one
  diff, and a single edit can both delete one server and set a key on another. Not a separate
  `deletions=` parameter and not a parallel `plan_delete` function (either would split a combined
  change into two diffs and two writes).
- **D-11:** **Removal is confirmed by the existing diff preview, not by an extra dialog.** Remove
  goes straight to `SaveDiffModal`, which shows the exact block being deleted and requires an
  explicit confirm — that is already a real confirmation step.
- **D-12:** **Disabling goes through the same scope → diff → confirm flow as every other write.**
  No fast-path toggle that writes silently. Phase 3's D-16/D-17 guarantee is that the user always
  knows which file changed; the first write that skips the diff would break it.

### Live apply
- **D-13:** After a save, **only the affected server is reconnected and its tools mounted** into
  the live registry — `MCPManager` gains a per-server add path that opens the transport, lists
  tools, and registers them. Not a full manager restart (which would tear down healthy sessions),
  and not next-launch-only (the milestone's whole point is configuring without restarting). Reuses
  the connection the pre-save test just proved; consistent with Phase 3's D-18 "switching applies
  immediately".
- **D-14:** **Removing or disabling a mounted server unmounts its tools and closes its session
  immediately** — symmetric with the add path. This requires a **tool-removal method on
  `ToolRegistry`** (none exists today). Leaving a removed server's tools callable would let the
  model invoke something the user just deleted.
- **D-15:** A mid-session mount change is **picked up by the next turn with no notice injected into
  the conversation**. Tool specs are read from the registry when a turn is built; nothing is
  written into the transcript context on the model's behalf. Consistent with how `/model` already
  changes the world between turns.
- **D-16:** When the config write succeeds but the live mount fails, **report both** — the save
  succeeded, the mount did not, with the error and an "available next launch" hint. Mirrors
  `MCPManager.note`'s existing degrade-with-a-note behavior. Do **not** roll back a config the user
  explicitly confirmed via the diff (Phase 3's D-13 "Save anyway" established that a legitimately
  unreachable endpoint is still worth saving).

### Connection test, tool listing & auth
- **D-17:** Auth secrets are **referenced from config, never stored in it**: config holds e.g.
  `Authorization = "Bearer ${GITHUB_TOKEN}"` (headers) or `TOKEN = "${GITHUB_TOKEN}"` (stdio env),
  and the value is resolved **at connect time, env var first then the OS keyring** — the same
  precedence as Phase 3's `resolve_api_key`. `MCPServerConfig` does no `${VAR}` expansion today;
  this is net-new. Plaintext tokens in `config.toml` are rejected, not merely discouraged (SEC-01).
- **D-18:** When a `${VAR}` reference is unresolved at test time, the flow **chains into the
  existing masked `KeyEntryModal`** — the same no-key-→-enter-key path Phase 3 built. One
  secret-entry widget in the codebase, already hardened against transcript echo (plans 03-10 /
  03-11). No second masked field inside the add form.
- **D-19:** The test result shows a **tool count plus a scrollable list of tool names** (with
  descriptions). Success criterion 2 requires enumerating tools before saving, and seeing the
  actual names is what proves the right server got wired up. The `agent86 mcp tools` table already
  renders this shape.
- **D-20:** The test uses the **same worker-thread + hard-timeout pattern as
  `ConnectionTestModal`**, with the timeout raised to **~30s** — a first-run stdio server may
  `npx`-download its package, and `MCPManager.start()` already budgets 30s for exactly this. A 15s
  timeout would fail honest first runs and teach the user to distrust the test.

### Carried forward from Phase 3 (not re-decided)
- Failure blocks the default Save path but offers a clearly-labelled **"Save anyway"** override
  (D-13) — a local stdio server that isn't installed yet, or a VPN-gated remote, is legitimately
  unreachable at configuration time.
- **Scope is chosen at save time**, user pre-selected, project one arrow key away (D-16).
- **The TOML diff is shown before every commit**, with the target path (D-17).
- **No secret is ever rendered on screen** or written to config (D-10, SEC-01).
- A stored secret can be **set and explicitly cleared, never revealed**.

### Claude's Discretion
- **D-21:** **Command surface.** Follow Phase 3's D-15 pattern — a registry entry under `/config`
  (i.e. `/config mcp`) is the expected shape, since `find_command_for_line` already does
  longest-name-first multi-word dispatch and `/config model` established the precedent. Claude may
  choose otherwise if the registry makes a different shape cleaner; whatever is chosen must be a
  `COMMANDS` entry so the palette and `/help` pick it up with no per-surface wiring.
- **D-22:** Exact modal composition, widget ids, CSS, screen count, and how the add form is split
  across screens — consistent with the `ModalScreen[T]` conventions in `tui/screens/*.py`.
- **D-23:** The mechanics of per-server teardown on `MCPManager`'s background event loop. The
  current design enters every transport into **one shared `AsyncExitStack`**, which cannot release
  a single server — restructuring to per-server exit stacks (or equivalent) is Claude's call.
- **D-24:** How duplicate MCP tool names across servers are handled on remount. `default_registry`
  currently swallows `ValueError` on duplicates; whether the new mount path surfaces the collision
  instead is Claude's call.
- **D-25:** Where `${VAR}` expansion lives (a small resolver next to `secrets.py`, or inside
  `_open_transport`) and whether it applies to `command`/`args`/`url` as well as `headers`/`env`.
- **D-26:** Whether the `[mcp] enabled` master switch is exposed in the manager, and whether the
  read-only `agent86 mcp` Typer commands gain an `enabled` column.
- **D-27:** Whether project-scope config shadowing a user-scope server of the same name needs any
  UI treatment beyond what `_deep_merge` already does.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### MCP core (the surface this phase configures)
- `src/agent86/tools/mcp_client.py` — `MCPManager` (`start`, `_run_loop`, `tools`, `call_tool`,
  `close`; the shared `AsyncExitStack` in `_connect` that D-23 must restructure for per-server
  teardown; the 30s startup budget referenced by D-20), `MCPTool` (name sanitization →
  `mcp__{server}__{tool}`), `_open_transport` (per-transport lazy imports; the D-25 expansion
  seam), `_streamable_http`, `_content_to_text`, `build_mcp` (the `config.mcp.enabled` /
  `mcp_servers` gate that D-09's `enabled` flag must extend).
- `src/agent86/config.py` §`MCPServerConfig` (line ~149) — the three-transport schema, the
  `_resolve_transport` validator (D-06 reuses its inference rule; D-05 surfaces its messages), and
  where D-09's `enabled` field is added. §`MCPConfig` (line ~131) — the master switch.
  §`_normalize` (line ~256) — the `[mcp.servers.NAME]` → `mcp_servers` remap that any write path
  must produce keys compatible with.
- `src/agent86/orchestration/loop.py` (lines ~85–95, ~146, ~362) — `Harness.__init__` builds the
  MCP manager and passes `mcp_tools` into `default_registry` **once**; `mcp_note`; `close()`.
  This is the construction-time coupling D-13/D-14 must break.
- `src/agent86/tools/registry.py` §`default_registry` (lines ~75–105) — how MCP tools are mounted
  and how duplicate names are currently swallowed (D-24); `ToolRegistry` needs the removal method
  D-14 requires.

### Config write-back (extended by this phase)
- `src/agent86/config_writer.py` — `plan_edit` / `apply_edit` (the two-step tomlkit round-trip;
  D-10 adds the `DELETE` sentinel here), `ConfigEdit`, `scope_path`, `SCOPE_USER`/`SCOPE_PROJECT`,
  `_FORBIDDEN_LEAF_KEYS` (note: `Authorization` is **not** in this set, so a bearer token would
  currently pass the guard — D-17 is what closes that hole), `ConfigWriteError`.
- `src/agent86/secrets.py` — `resolve_api_key` / `keyring_available` / `has_stored_key` /
  `store_api_key` / `clear_api_key` / `redact`; the env-first-then-keyring precedence D-17 mirrors
  and the lazy keyring import pattern to copy.

### TUI integration points
- `src/agent86/tui/commands.py` — `COMMANDS` registry / `CommandEntry`, `find_command`,
  `find_command_for_line` (longest-name-first multi-word dispatch, needed for D-21),
  `handle_command`, `CommandResult`, `startup_notes` (line ~323 already surfaces `mcp_note`).
- `src/agent86/tui/app.py` — `Agent86App`, `_dispatch_line` / `_run_or_chain` (the single funnel
  every command path goes through), `on_input_submitted` (the `#prompt`-only guard from plan 03-10
  that keeps typed secrets out of the transcript), the `@work(thread=True)` + `post_message`
  pattern, `_catalog_cache` (the session-cache precedent), `BINDINGS`, CSS.
- `src/agent86/tui/screens/connection_test.py` — `ConnectionTestModal`: worker thread, hard
  timeout, "Save anyway" override. The direct template for D-19/D-20.
- `src/agent86/tui/screens/key_entry.py` — `KeyEntryModal`: masked entry, `event.stop()` first
  statement, keyring-unavailable messaging. Reused verbatim by D-18.
- `src/agent86/tui/screens/save_diff.py` — `SaveDiffModal`: scope radio, live diff recompute,
  error-renders-and-disables-confirm behavior D-05 mirrors, caller-applies-the-edit contract.
- `src/agent86/tui/screens/provider_manager.py` — `ProviderRow` / `provider_rows(cfg)` /
  `ProviderManagerModal` / `CatalogPickerModal`: the list-modal and type-to-filter shapes the MCP
  manager should mirror.
- `src/agent86/tui/screens/approval.py` — the `ModalScreen[T]` contract every dismissal path must
  resolve.
- `src/agent86/cli.py` (lines ~476–515) — `mcp_app` `list` / `tools` commands; the row and
  tool-table rendering to reuse, and the module-load lazy-import constraint.

### Tests to extend (existing MCP coverage)
- `tests/unit/test_mcp.py`, `tests/integration/test_mcp_client.py`,
  `tests/integration/test_mcp_live.py`, `tests/integration/live_mcp_server.py` (a real in-repo MCP
  server usable for connection-test and mount/unmount tests), `tests/unit/test_config.py`
  (MCPServerConfig validation cases).
- `tests/tui/test_lazy_import.py` — the guard that must stay green.

### Prior phase decisions (patterns to honor)
- `.planning/phases/03-secrets-model-provider-config/03-CONTEXT.md` — D-11..D-14 (connection test),
  D-15 (`/config <thing>` manager surface), D-16/D-17 (scope + diff), D-10 (never reveal a secret),
  D-18 (apply live, persist separately). This phase is deliberately the same shape.
- `.planning/phases/02-command-palette-menus/02-CONTEXT.md` — D-04/D-05 (registry as single source
  of truth), D-10 (picker chaining), D-11 (typed commands keep working).
- `.planning/phases/01-tui-skeleton-live-status-line/01-CONTEXT.md` — Textual only inside `tui/`;
  the plain loop and `run --json` are never touched.

### Constraints
- `CLAUDE.md` §Constraints and `pyproject.toml` — `mcp` is an optional extra
  (`pip install "agent86[mcp]"`); the manager must degrade with a note when it is absent, exactly
  as `MCPManager.start` does today. No new module-load imports on the `run` / `--plain` path.

No external specs or ADRs exist for this project — requirements are fully captured in the
decisions above, ROADMAP.md Phase 4, and REQUIREMENTS.md (MCP-01).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tui/screens/connection_test.py::ConnectionTestModal` — worker-thread test with a hard timeout
  and a "Save anyway" override; the MCP test is the same shape with a longer budget and a tool
  list instead of a completion.
- `tui/screens/key_entry.py::KeyEntryModal` — masked, echo-hardened secret capture, reused as-is
  for `${VAR}` resolution (D-18).
- `tui/screens/save_diff.py::SaveDiffModal` — scope + diff + confirm; works unchanged for MCP
  edits once `plan_edit` can express a deletion (D-10).
- `tui/screens/provider_manager.py` — `provider_rows(cfg)` → list-modal → chained action is the
  exact skeleton for the MCP server list; `CatalogPickerModal`'s type-to-filter pattern is
  available if the server list ever grows.
- `cli.py::mcp_list_cmd` / `mcp_tools_cmd` — row shape (name / transport / endpoint) and the tool
  table the manager and test result should match.
- `tests/integration/live_mcp_server.py` — a real MCP server in-repo, so the connection test and
  the mount/unmount paths can be tested end-to-end without network.

### Established Patterns
- All Textual code lives in `src/agent86/tui/`; `ui/repl.py` and the plain loop are never touched.
- Commands return renderables via `CommandResult`; nothing prints to stdout.
- Every `ModalScreen[T]` resolves explicitly on all dismissal paths, including Escape.
- Blocking work runs on a thread worker and reports back via `post_message`.
- MCP degrades to "zero tools and a note", never an error — the manager must preserve that.
- Secrets are lazily resolved at point of use and never rendered; `event.stop()` is the first
  statement in any modal Input submit handler.

### Integration Points
- **`MCPServerConfig.enabled`** — net-new field; `build_mcp` filters on it (D-09).
- **`config_writer` `DELETE` sentinel** — net-new; the only way to remove a server or a key (D-10).
- **`ToolRegistry` removal** — net-new; required for unmount (D-14).
- **Per-server transport lifecycle in `MCPManager`** — today one shared `AsyncExitStack` for all
  servers; add/remove of a single server requires restructuring (D-13/D-14/D-23).
- **`${VAR}` expansion in `_open_transport`** (or a resolver beside `secrets.py`) — net-new; the
  chokepoint that keeps tokens out of config (D-17/D-25).
- **`/config mcp` registry entry** — palette and `/help` come free from `COMMANDS` (D-21).
</code_context>

<specifics>
## Specific Ideas

- The add path should feel continuous, like Phase 3's provider flow: paste the JSON from a
  server's README → it validates inline → any missing secret is asked for masked → it connects and
  shows you the tools it found → you see the TOML diff → save → the tools are usable on the next
  turn. One flow, not five commands.
- Seeing the actual tool names (not just a count) is the point of the pre-save test — it is how a
  user knows they wired up the server they meant.
- Opening the manager must never spawn a subprocess. Listing is cheap; connecting is an explicit
  action.
- A user should be able to hand-edit `config.toml`, see `enabled = false` on a server, and
  immediately understand what it means.

</specifics>

<deferred>
## Deferred Ideas

- **Editing MCP servers from the non-interactive `agent86 mcp` CLI** (`mcp add` / `mcp remove`) —
  out of scope; the Typer commands stay read-only this phase.
- **Per-server tool allow/deny lists** (mounting only some of a server's tools) — a new capability,
  its own phase.
- **OAuth / dynamic client registration for remote MCP servers** — the MCP spec supports it; this
  phase covers static header auth only.
- **Live status polling / health checks in the server list** — rejected for this phase (D-08);
  revisit only if the static list proves insufficient.
- **Remembering a session's last test result per row** — considered for D-08, deferred because it
  needs session state that resets every launch.
- **Rolling back a config write when the live mount fails** — explicitly rejected (D-16), not
  merely deferred.
- **Plaintext tokens in config with a warning** — explicitly rejected (D-17), contradicts SEC-01.
- **Packaging / lazy-import hardening as a verified contract** — Phase 5 (TUI-06). This phase must
  not break it, but proving it is Phase 5.
- **Theming for the new modals** — v2 (POL-01).

</deferred>

---

*Phase: 04-mcp-config-ui*
*Context gathered: 2026-08-06*
