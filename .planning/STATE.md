---
gsd_state_version: 1.0
milestone: v0.6
milestone_name: milestone
status: unknown
last_updated: "2026-08-13T11:28:30.452Z"
progress:
  total_phases: 5
  completed_phases: 4
  total_plans: 30
  completed_plans: 30
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-19)

**Core value:** Run, configure, and steer the agent entirely from within an interactive terminal
app — no hand-editing TOML, no restarts.
**Current focus:** Phase 05 — packaging-hardening (Phase 04 complete)

## Milestone

**v0.6 — Interactive** (agent86 currently at v0.5.8)
5 phases | 10 v1 requirements | 0 phases complete

## Progress

| Phase | Status | Plans | Progress |
|-------|--------|-------|----------|
| 1 — TUI Skeleton + Live Status | ● | 5/5 | 100% |
| 2 — Command Palette + Menus | ● | 4/4 | 100% |
| 3 — Secrets + Model Config | ● | 13/13 | 100% |
| 4 — MCP Config UI | ● | 8/8 | 100% |
| 5 — Packaging & Hardening | ○ | 0/? | 0% |

## Recent Activity

- 2026-08-06 — Plan 04-08 complete (`/config mcp` full-app chain, Wave 4 — final plan, Phase 4
  now feature-complete 8/8, MCP-01 and the SEC-01 `headers.Authorization` write-path both closed):
  `/config mcp` registered in `tui/commands.py`'s `COMMANDS` registry with `needs_choice=
  "config_mcp"` (palette/`/help`/multi-word dispatch, zero per-surface wiring, mirrors
  `/config model`). `Agent86App` gains the full add/edit chain — `MCPManagerModal` →
  `MCPServerFormModal` → every unresolved `${VAR}` resolved one at a time through the existing
  masked `KeyEntryModal` (never a second masked field) → `MCPTestModal` on
  `Harness.ensure_mcp()`'s live manager → `SaveDiffModal` (headers/env written as individual TOML
  key paths, not whole dicts, so config_writer's forbidden-leaf-key guard actually inspects
  `headers.Authorization`) → `apply_edit` → `Harness.add_mcp_server` mounting the tested server's
  tools live. A cancelled add stops the server the test already started (D-13); a config write
  that succeeds while the live mount fails reports both without rolling back (D-16). Remove and
  enable/disable reuse the identical diff-and-confirm gate — no silent write, no extra "are you
  sure" dialog — and re-enabling a disabled server re-runs the connection test before mounting.
  Removed both plan-04-08-owned `xfail` markers from `tests/tui/test_mcp_manager.py`; added a
  `_FakeMCPManager` and full-app Pilot tests for the add chain, `${VAR}` key-entry chaining, both
  cancel paths, live mount, the override/mount-failure-reports-both path, per-key header/env TOML
  paths, and remove/disable/enable-with-test/no-op-remove. One test-only deviation: headless
  Pilot tests against the real `Agent86App` needed `run_test(size=(100, 50))` (default 80x24
  clips the MCP form below its Continue button) and a `pilot.pause`-based settle helper instead of
  a bare `asyncio.sleep` poll (buttons' `display` flag could flip `True` moments before their
  `Button` children finished mounting under `call_from_thread`) — 25+ consecutive runs green
  after the fix. Full suite green: 438 passed, 0 xfailed, 0 failed (the pre-existing, documented
  `CatalogPickerModal`/`#catalog-filter` flake from `deferred-items.md` appeared once per its two
  known forms across two full runs and cleared on immediate rerun both times — unrelated to this
  plan's files).

- 2026-08-06 — Plan 04-07 complete (MCP pre-save connection test modal, parallel Wave 3):
  `src/agent86/tui/screens/mcp_test.py` adds `MCPTestOutcome`/`MCPTestModal` — the MCP twin of
  `connection_test.py` (D-20): a 30s worker-thread test (raised from 15s because a first-run
  stdio server may `npx`-download its package) that starts a server for real on the caller's
  *live* `MCPManager` via `start_server(name, cfg, timeout=30.0, overrides=...)`, enumerates its
  tools, and requires an explicit Continue before the flow reaches the diff (D-19) rather than
  auto-dismissing on success. A real failure shows the verbatim (redacted, SEC-01) error and
  offers a labelled "Save anyway" override (D-13); timeout/cancel/escape all resolve explicitly
  and never hang. Removed the Wave 0 module-level `xfail` from `tests/tui/test_mcp_test_modal.py`
  — all 6 tests pass unmarked. Fixed a pre-existing scaffold bug flagged in the plan's own
  context: `Static.renderable` doesn't exist on the installed Textual 8.2.8 (`.render()` does,
  matching `test_save_diff.py`'s pattern). Full suite green: 418 passed, 2 xfailed (04-08-owned,
  untouched), 0 failed.

- 2026-08-06 — Plan 04-06 complete (Harness live mount/unmount seam, parallel Wave 3):
  `src/agent86/orchestration/loop.py` adds `Harness.ensure_mcp()` (returns the live `MCPManager`,
  creating an empty one when the session started with none, idempotent, never touching the
  registry), `add_mcp_server(name, cfg)` (mounts an already-connected server's tools — never
  opens a transport itself — into the live registry, returning `(mounted, collisions)` with
  name collisions reported rather than swallowed, D-24), and `remove_mcp_server(name)`
  (unregisters a server's tools, stops its session, drops it from `manager.servers`; a no-op for
  an unknown name or absent manager). Neither new method rebuilds `self.registry` or reads
  `self.config.mcp_servers` after construction (RESEARCH Pitfall 3) — `self.mcp.servers` and
  `self.registry` are the only live truth, matching the discipline `set_model()` already used.
  D-15 needed no code: `_build_request` already reads `self.registry.specs()` fresh every turn,
  so a mount/unmount takes effect on the very next turn. 15 new unit tests in
  `tests/unit/test_loop.py` (manager creation/idempotency, mount, collision reporting, config
  recording, transport-free mounting via a monkeypatched `_open_transport`, and unmount/no-op
  paths) using a lightweight fake `MCPManager`/`Tool` pair, no real transport. Full suite green:
  418 passed, 2 xfailed (04-08-owned, untouched), 0 failed.

- 2026-08-06 — Plan 04-04 complete (task-per-server MCPManager lifecycle, parallel Wave 2 —
  the single load-bearing piece of engineering in this phase, D-23): `MCPManager` rewritten
  from one shared `AsyncExitStack` to one persistent `asyncio.Task` per server, each owning its
  own stack via `start_server`/`stop_server`/`tools_for`/`_ensure_loop`/`_launch`/`_serve` —
  anyio binds a transport's cancel scope to the task that entered it, so parking on a per-server
  `close_event` and letting `async with` unwind in place (rather than closing a shared stack from
  a different task) is what makes independent per-server teardown legal. Verified for real
  against two live stdio `FastMCP` servers: `test_independent_teardown_leaves_other_server_intact`
  passes with no "cancel scope"/"different task" `RuntimeError`, the surviving server keeps
  answering `call_tool`, and calling the stopped server correctly raises. Added
  `_resolve_server_secrets`/`unresolved_var_refs` for connect-time `${VAR}` expansion in
  args/env/url/headers (never `command`) via plan 04-02's `expand_var_refs` (D-17/D-25), and
  filtered `cfg.enabled=false` servers inside `build_mcp` rather than `MCPManager` (D-09).
  One deviation: `ClientSession` is now looked up through a small `_get_client_session()`
  indirection (module globals first, real `from mcp import ClientSession` fallback) instead of
  the plan's literal function-local import, because the real `mcp` package is installed in this
  environment and the Wave 0 fake-session scaffold monkeypatches `mcp_client.ClientSession` —
  without the indirection the test would silently exercise the real SDK against fake streams
  instead of the intended fake. Removed `xfail` from 3 unit scaffolds, 2 `build_mcp` filter
  scaffolds, and 5 real-stdio integration scaffolds. Full suite green: 402 passed, 8 xfailed
  (unrelated, later-plan scaffolds), 0 failed.

- 2026-08-06 — Plan 04-02 complete (secret references + config deletion, parallel Wave 1):
  `agent86/secrets.py` adds `find_var_refs`/`expand_var_refs`/`MissingSecretRef` — MCP server
  configs reference secrets as `${VAR}`, resolved env-first-then-keyring by reusing
  `resolve_api_key(name, name)` verbatim (no second precedence implementation); an unresolved
  reference raises `MissingSecretRef` carrying `.var_name`. `agent86/config_writer.py` adds a
  `DELETE` sentinel so `plan_edit` can remove a whole `[mcp.servers.NAME]` table in the same
  changes list as an ordinary set (one function, one diff, no `plan_delete`/`deletions=`);
  `_FORBIDDEN_LEAF_KEYS` gains `"authorization"` (closing the SEC-01 hole in MCP
  `headers.Authorization`) paired with a `_is_var_ref` exception so the `${VAR}` form saves while
  a literal — even with a decoy `${notreal}` appended — is refused. Found and fixed a tomlkit
  quirk while making the delete scaffold pass for real: a hand-written comment between two table
  headers parses as trailing content of the *preceding* table, so a naive delete silently dropped
  a surviving sibling's comment; `_apply_delete` now pops that trailing trivia and re-homes it on
  the parent container. Removed `xfail` from the 6 var_ref scaffolds in `test_secrets.py` and the
  7 delete/forbidden_var_ref scaffolds in `test_config_writer.py`. Full suite green: 370 passed,
  35 xfailed (unrelated, later-plan scaffolds), 0 failed.

- 2026-08-06 — Plan 04-03 complete (MCP schema/registry seams, parallel Wave 1): `MCPServerConfig`
  gains `enabled: bool = True` (D-09), TOML round-trippable via the existing `[mcp.servers.NAME]`
  normalize path, with `_resolve_transport` unchanged. `agent86 mcp list` gained an `Enabled`
  column (`Name | Transport | Enabled | Endpoint`) — no new Typer subcommand. `ToolRegistry` gains
  `unregister(name) -> bool` (D-14), popping a tool by name so a removed/disabled MCP server's
  tools stop being callable immediately; `register`/`default_registry`'s bulk-mount duplicate-
  swallow left byte-identical (explicit collision surfacing deferred to plan 04-06, D-24). Removed
  `xfail` from the 4 Wave 0 scaffolds owned by this plan across `test_config.py`/`test_mcp.py`;
  the 4 `build_mcp`/`start_server`/`stop_server` scaffolds owned by plan 04-04 remain xfail-marked
  and untouched. Full suite green: 363 passed, 40 xfailed, 2 xpassed, 0 failed.

- 2026-08-06 — Plan 04-05 complete (MCP manager list + form modals, parallel Wave 2):
  `agent86/tui/screens/mcp_manager.py` created — `mcp_server_rows(cfg)` (pure, D-08: never spawns
  a subprocess or opens a transport; endpoint rendering byte-identical to `agent86 mcp list`),
  `parse_server_json` (accepts both the bare and `{"mcpServers"/"servers": {...}}` README JSON
  shapes, D-02; wrapped name wins over `name_hint`), `build_manual_config` (shlex-splits a
  command line into command+args, D-03; only honours an explicit transport when `url` is set,
  D-06), `parse_kv_list` (env/headers parsing, `${VAR}` passthrough for D-17). `MCPManagerModal`
  lists every server plus two peer "add" options (D-01) and dispatches edit/remove/toggle via
  Enter/`d`/`t`. `MCPServerFormModal` serves add-json/add-manual/edit from one form (D-07),
  re-validating on every keystroke and rendering the config validator's own message verbatim
  inline while disabling Continue (D-05), and blocking a name collision (D-04). Removed the Wave 0
  module-level `xfail` from `tests/tui/test_mcp_manager.py`; only the two 04-08-owned full-app
  chain tests remain explicitly `xfail`-marked. Fixed a genuine scaffold bug along the way —
  `Static.renderable` doesn't exist on the installed Textual 8.2.8 (`.render()` does, matching
  `test_save_diff.py`'s existing pattern). `pytest tests/tui/test_mcp_manager.py -q`: 17 passed,
  2 xfailed. `pytest tests/tui/ -q`: 109 passed, 8 xfailed, 0 failed. A pre-existing,
  test-order-dependent `CatalogPickerModal`/`#catalog-filter` flake (unrelated to this plan's
  files, first seen during 04-02) still reproduces in a full-suite run; logged in
  `deferred-items.md`, not fixed here (scope boundary).

- 2026-08-06 — Quick task 260805-xbw complete: `Harness._observe` (`orchestration/loop.py`)
  no longer collapses a failed tool result to the bare string `"error"`. `python_exec`/
  `run_command` report failure with `ok=False`, `error=None`, and the full
  `exit code / stdout / stderr` traceback in `content` — previously discarded, leaving the
  model blind to its own bugs and misattributing failures to a flaky sandbox. `_observe` now
  resolves the failure body from `content` (falling back to `error`, joining both when both
  are present), then runs the same guardrail scan/`UNTRUSTED_BANNER` wrap the success path
  already used — one scan site, not two. `_summarize` (the human-facing status line) was
  already correct and left untouched. `_BASE_IDENTITY` (`cognitive/prompt.py`) gained a
  `Debugging:` section instructing the model to print `traceback.format_exc()`, inspect data
  shape (`.keys()`/`type()`/`len()`) before indexing, and treat attempt-to-attempt differences
  as a clue about its own code, not environment flakiness. RED evidence recorded before the
  fix: 8/12 new tests failed pre-fix (the intended set), 4/12 passed pre-fix (pins on already-
  correct behavior). Full suite green: 353 passed (341 baseline + 12 new), 0 failed.

- 2026-08-06 — Plan 03-10 complete (UAT gaps 1 and 4 closure, parallel gap-closure wave):
  `KeyEntryModal.on_input_submitted` and `CatalogPickerModal.on_input_submitted` now call
  `event.stop()` as their first statement, and `Agent86App.on_input_submitted` now ignores
  every `Input` except `#prompt` — three defense-in-depth fixes closing UAT gap 1 (blocker,
  SEC-01/D-10): a typed API key was being echoed into the transcript and dispatched to the
  model as a real turn. `Agent86App._on_catalog_picked` now passes the `UNRESOLVED` sentinel
  (imported from `agent86.cognitive.base`) instead of the stale `None` left by the previous
  test's `finally` block whenever no key was typed this pass; `ConnectionTestModal.__init__`
  widens `api_key` to `Any = UNRESOLVED` to match — closing UAT gap 4 (blocker, MODEL-01): a
  keyring-stored key now resolves on the second and every subsequent connection test in a
  session, not just the first. Added `tests/tui/test_secret_leak.py` (6 new Pilot regression
  tests), confirmed 4/6 fail against the pre-fix source and all 6 pass post-fix. Full suite
  green: 331 passed, 0 failed.

- 2026-08-06 — Plan 03-11 complete (UAT gap 2 closure, parallel gap-closure wave): closes the
  second, independent secret-leak path found during UAT — a startup crash rendering a live
  `sk-ant-...` key in the `locals` panels of four traceback frames. `agent86.cli`'s `typer.Typer`
  now sets `pretty_exceptions_show_locals=False` (Rich never renders frame locals, on any code
  path). `agent86.secrets.redact()` added — strips explicit secrets and key-shaped tokens
  (`sk-`/`gsk_`/`xai-`/`AIza` prefixes) from any human-visible string. `cognitive/base.py`'s
  `provider_for_ref` refactored: the dispatch chain moved verbatim into a private
  `_build_provider()`, guarded by a wrapper that converts any non-`ProviderError` exception into
  a `ProviderError` with a redacted message and a severed `__cause__` chain (`from None`) —
  deliberate `ProviderError`s (missing key, missing SDK, unknown provider) pass through
  unchanged. 10 new regression tests in `tests/unit/test_secret_traceback.py`; 2 confirmed to
  fail against the pre-fix source via a `git stash` round-trip. Full suite green: 331 passed
  (grown from 275/311 as sibling gap-closure plans 03-10..03-13 landed concurrently in the same
  parallel wave). SEC-01/D-10 traceback leak closed.

- 2026-08-06 — Plan 03-12 complete (UAT gap 5 closure, blocker, parallel gap-closure wave):
  `agent86.cognitive.capabilities` adds a single per-model capability seam
  (`supports_sampling_params`/`apply_sampling_params`/`mark_sampling_unsupported`/
  `is_sampling_rejection`) recording that Anthropic removed `temperature`/`top_p`/`top_k` on
  Claude Opus 5, Opus 4.8, Opus 4.7, Sonnet 5 and Fable 5 — sending any of them 400s, with no
  replacement value, so they must be omitted entirely. `AnthropicProvider.stream` now gates
  through this seam (the gate is on the model, never on the value, since
  `CompletionRequest.temperature` defaults to `0.0`) and self-corrects: a real rejection from a
  model not yet in the hardcoded list is learned via `mark_sampling_unsupported` and retried
  once before any text is emitted. `complete()` stays inherited from `ModelProvider`, so the
  connection-test path used by `/config model` is fixed by the same change.
  `OpenAIProvider.stream` routed through the identical seam — byte-identical behaviour for
  OpenAI/Groq/OpenRouter today (no OpenAI-family model is affected), correct omission for free
  if a gateway proxies an Anthropic model through an OpenAI-compatible endpoint. 43 new tests
  (`test_capabilities.py` + `test_sampling_params.py`); existing `test_openai_provider.py` left
  byte-unmodified. Full suite green: 331 passed, 0 failed. ROADMAP success criterion 4
  ("switching the active model takes effect for the next turn") now holds in practice for the
  default `anthropic:claude-opus-5` selection. MODEL-01 gap closed.

- 2026-08-06 — Plan 03-13 complete (UAT gap 3 closure, blocker, gap-closure wave — Phase 3 now
  fully closed, all 6 UAT gaps resolved): `AnthropicProvider.__init__` gains an SDK-version guard
  — `_MIN_ANTHROPIC_VERSION = (0, 40)` and a tolerant `_version_tuple` parser (stops at the first
  non-numeric character per dot-segment, so pre-release suffixes never block startup) — that
  raises `ProviderError` naming the version found, the version needed, and the exact
  `pip install -U "anthropic>=0.40"` upgrade command, mirroring the existing missing-package
  `ImportError` path exactly in tone and type. The guard fires before `anthropic.Anthropic(...)`
  is ever constructed, so a stale SDK below the floor (versions < 0.28 pass `proxies=` to
  `httpx.Client`, which httpx removed in 0.28) never reaches the opaque
  `Client.__init__() got an unexpected keyword argument 'proxies'` `TypeError` that dumped a
  traceback and leaked the key at startup (root cause of UAT gaps 2 and 3 together). Because the
  guard raises `ProviderError`, it passes through plan 03-11's catch-all and `run_repl`'s existing
  `except ProviderError` branch untouched — no changes needed to `cognitive/base.py` or
  `ui/repl.py`. 10 new regression tests in `tests/unit/test_anthropic_sdk_guard.py`: 6 unit tests
  on the guard itself (stale version raises with exact wording, zero-client-construction proof,
  real 0.120.2 constructs normally, missing/unparseable version doesn't block startup, missing-
  package path unchanged), 4 end-to-end through `run_repl` (an opaque `TypeError` and a genuine
  stale-SDK `ProviderError` both print "Cannot start:" with no traceback and no leaked key).
  `pyproject.toml`'s `anthropic>=0.40` floor left untouched (verified via empty `git diff --stat`)
  — no dependency pin was part of this deliverable, per the plan's explicit instruction that the
  environment (already at anthropic 0.120.2) was not the fix. Full suite green: 341 passed
  (up from 331), 0 failed, across two consecutive reruns.

- 2026-08-06 — Plan 03-09 complete (full-app chain + live-catalog /model picker, Wave 3 — final
  plan, Phase 3 now feature-complete 9/9): `agent86/tui/messages.py` adds `CatalogReady`.
  `Agent86App` gains a per-session `_catalog_cache`, `_request_catalog`/`_fetch_catalog`
  (`@work(thread=True)`, cache populated only in `on_catalog_ready` on the UI thread — RESEARCH
  Open Question 3 resolved: the cache lives on the App, not `_Repl`/`Harness`), and the full
  `/config model` chain: `ProviderManagerModal` → `KeyEntryModal` (only if no key) → catalog fetch
  → `CatalogPickerModal` → `ConnectionTestModal` → on pass/override, `store_api_key` fires exactly
  once (D-14), the model switch applies immediately via `_dispatch_line("/model <ref>")`, then
  `SaveDiffModal` → `apply_edit` on confirm. `_dispatch_line` now routes any bare (argument-less)
  `needs_choice` command typed directly — not just palette-picked — through `_run_or_chain`, since
  the Wave-0 chain tests type `"/config model"` straight into the prompt and press Enter.
  `model_choices(cfg, extra=...)` enriches the `/model` picker with the live catalog, closing
  Phase 2's deferred D-12; `/model` stays switch-only (D-15). Removed the 3 remaining chain-wiring
  `xfail` markers from `tests/tui/test_provider_manager.py` (filling in
  `test_save_anyway_override`'s exact key-press choreography with network-safe mocks for
  `catalog.fetch_catalog`/`connection_test.provider_for_ref`); added 3 catalog-cache tests, 3
  `/model`-picker cache tests, and an escape/`SkipAction` regression test to `test_app.py`, plus 3
  `model_choices(extra=...)` tests to `test_pickers.py`. Full suite green: **275 passed, 0
  xfailed, 0 xpassed, 0 failed** (up from 262/2/1/0). `deferred-items.md` removed (its logged
  failures were transient parallel-wave artifacts, already resolved). Manual Windows Terminal
  verification (real keyring round-trip, real comment-preserving save, live OpenRouter/Groq
  catalog schema check) per `03-VALIDATION.md` remains outstanding before the phase is declared
  fully done end-to-end, but all automated success criteria are met.

- 2026-08-05 — Plan 03-06 complete (key-entry + connection-test modals, parallel Wave 2):
  `src/agent86/tui/screens/key_entry.py` adds `KeyEntryModal(ModalScreen[str | None])` — masked
  (`password=True`) key capture, explicit dismiss on submit/empty/escape, distinct
  "OS keyring unavailable" messaging (SEC-01, D-08/D-09/D-10). `src/agent86/tui/screens/
  connection_test.py` adds `ConnectionTestModal(ModalScreen[TestOutcome])` — a worker-thread
  (`@work(thread=True)`) real 1-token completion test via `provider_for_ref(ref, cfg, api_key=...)`,
  a hard 15s timeout that auto-resolves without waiting on a button, and a "Save anyway" override
  on real provider errors; the tested key is never written to the keyring by this module (MODEL-01,
  D-11..D-14). Deleted the shared Wave 0 xfail marker from `tests/tui/test_connection_test.py` and
  added 5 new `KeyEntryModal` tests; all 10 tests in the file pass. Full suite green: 262 passed,
  2 xfailed (unrelated), 1 xpassed (unrelated), 0 failed. Note: due to a parallel-executor commit
  race, `connection_test.py` landed inside plan 03-08's commit (`689f0da`) rather than its own —
  content verified correct and complete; see 03-06-SUMMARY.md for detail.

- 2026-08-06 — Plan 03-08 complete (provider manager + catalog picker, parallel Wave 2):
  `agent86/tui/screens/provider_manager.py` adds `ProviderRow`/`provider_rows(cfg)`/
  `ProviderManagerModal`/`CatalogPickerModal`. `provider_rows` lists every configured provider
  in config order with an accurate, secret-free key status (`key ok`/`no key`/`local, no key
  needed`), sourced from `resolve_api_key` so it matches exactly what a real turn would resolve
  (D-05/D-09/D-10). `ProviderManagerModal` (OptionList) dismisses with the selected `ProviderRow`
  or `None` on Escape. `CatalogPickerModal` narrows a catalog by typing (case-insensitive
  substring on ref/label, mirroring Phase 2's `_sync_palette` filter-and-reset-highlighted
  pattern, D-03) and its filter Input doubles as the D-01 free-text fallback when the catalog is
  empty or nothing matches — never a dead end. A `_catalog_ref`/`_freetext_ref` split avoids
  double-prefixing Ollama model names that already contain a colon (e.g. `llama3.1:8b`). Wave 0
  module-level xfail removed; per-function xfail kept on exactly the 3 tests plan 03-09 owns
  (full-app chain wiring). Full suite green: 262 passed, 2 xfailed, 1 xpassed (harmless early
  pass of a 03-09-owned test), 0 failed. MODEL-01 requirement's provider-list/catalog-picker
  surfaces complete.

- 2026-08-06 — Plan 03-05 complete (command-surface + keyring visibility, parallel Wave 2):
  `/config model` registered in `tui/commands.py`'s `COMMANDS` registry with
  `needs_choice="config_model"`, discoverable via `/help` and the `/` palette with zero
  per-surface wiring (MODEL-01). `find_command_for_line` added for longest-name-first multi-word
  dispatch so `/config model` wins over `/config` while `/models` still beats the `/model` prefix
  and `/model <arg>`/`/quit`/`/exit` are unchanged; `handle_command` rewritten to use it,
  `find_command` (palette's exact-name lookup) untouched. `_key_source` helper (env → keyring →
  none → n/a) added to both `tui/commands.py` and `cli.py`; the TUI `/models` table and `agent86
  config` (bare — wired via a new `config_app` callback to the existing `_list_models`, since that
  table lived under `agent86 models` rather than a pre-existing `agent86 config` default action)
  both now show a `Key` column and an `OS keyring: available/unavailable` line, no secret ever
  rendered (D-09/D-10, SEC-01). 8 new regression tests added; full suite green: 262 passed,
  2 xfailed, 1 xpassed, 0 failed.

- 2026-08-06 — Plan 03-07 complete (save-diff modal, parallel Wave 2): `agent86/tui/screens/
  save_diff.py` adds `SaveDiffModal(ModalScreen[ConfigEdit | None])` — the D-16/D-17 trust-building
  step. On mount and on every scope change it calls `config_writer.plan_edit(scope, changes)`
  (pure, no disk I/O) and renders the unified diff plus target path; `#scope-user` is pre-selected,
  `#scope-project` is one arrow key away and recomputes the diff. `#save-confirm` dismisses with
  the live `ConfigEdit`; `#save-cancel`/Escape dismiss with `None`; a `ConfigWriteError`/`ValueError`
  (malformed existing file, forbidden secret key) renders the error text and disables
  `#save-confirm` instead of crashing. The modal never calls `apply_edit` itself — the caller
  applies the returned `ConfigEdit` on confirm. Deleted the Wave 0 xfail marker from
  `tests/tui/test_save_diff.py`; added 2 integration tests proving the previewed diff is
  byte-identical to what gets written and that all four hand-written comments in
  `tests/fixtures/config_with_comments.toml` survive a real preview-then-apply round trip.
  `pytest tests/tui/test_save_diff.py -q` — 6 passed, 0 xfailed. MODEL-02 requirement complete.

- 2026-08-06 — Plan 03-02 complete (secrets seam, parallel Wave 1): `agent86/secrets.py` created
  with `resolve_api_key`/`keyring_available`/`has_stored_key`/`store_api_key`/`clear_api_key` —
  env var wins, falls back to OS keyring, never raises (silent degrade when keyring absent/broken),
  keyring imported lazily inside every function body. `provider_for_ref` in `cognitive/base.py`
  now resolves the key once via `resolve_api_key(ref.provider, pconf.api_key_env)` — keyed on the
  config section name so a custom `[providers.myvllm]` block gets its own keyring slot — and
  injects it into every provider construction path via an `UNRESOLVED` sentinel (direct
  construction, as existing tests do, still self-resolves). Both `os.getenv` seams in
  `anthropic_provider.py`/`openai_provider.py` removed; `llamacpp_provider.py` forwards the key.
  Original `ProviderError` wording preserved verbatim with only an appended clause. Deleted the
  Wave 0 xfail markers from `tests/unit/test_secrets.py` (7 tests) and
  `tests/unit/test_providers_key_seam.py` (6 tests); all now pass. Full suite green: 229 passed,
  16 xfailed, 1 xpassed (unrelated), 0 failed. SEC-01 requirement complete.

- 2026-08-06 — Plan 03-04 complete (catalog fetch + normalization, parallel Wave 1):
  `agent86/cognitive/catalog.py` adds `fetch_catalog`/`fetch_openai_compatible`/`fetch_anthropic`/
  `fetch_ollama`/`CatalogUnavailable`, normalizing all five distinct provider models-endpoint
  response shapes (OpenAI, Groq, OpenRouter, Anthropic, Ollama) into a common `(ref, label)` list
  (MODEL-01, D-01/D-02: the live endpoint is the only source of truth, nothing hardcoded).
  Anthropic uses `x-api-key` + `anthropic-version: 2023-06-01`, never `Authorization: Bearer`
  (RESEARCH Pitfall 4). Any fetch failure, or a provider with no listing endpoint (llama.cpp),
  raises `CatalogUnavailable` so the caller falls back to free-text `provider:model` entry — never
  a dead end. Deleted the Wave 0 xfail marker from `tests/unit/test_catalog.py`; all 9 tests pass
  for real. Live-verified the OpenRouter schema against `GET https://openrouter.ai/api/v1/models`
  (matches the fixture exactly); Groq's schema stays unverified (no API key available) and is
  recorded as an open item for a future manual pass. Full suite green: 229 passed, 16 xfailed,
  1 xpassed, 0 failed.

- 2026-08-06 — Plan 03-03 complete (config write-back, parallel Wave 1): `agent86/config_writer.py`
  adds `plan_edit`/`apply_edit` — a two-step tomlkit round-trip write-back (D-17) that preserves
  every comment/blank line in a hand-edited `config.toml`, targets user scope by default with
  project scope selectable via `scope_path`, and produces a `difflib.unified_diff` preview before
  anything is written. Any leaf key in `{api_key, apikey, key, token, secret, password}` raises
  `ValueError` before text is generated, so no plaintext secret can reach disk through this module
  (SEC-01). Writes are atomic (`tempfile.mkstemp` + `os.replace`), so a crash mid-write cannot
  truncate an existing config; malformed existing TOML raises `ConfigWriteError`. `tomlkit` stays
  lazily imported (guarded by `tests/tui/test_lazy_import.py`, still 2 passing). Deleted the Wave 0
  xfail marker from `tests/unit/test_config_writer.py`; all 6 original + 3 new hardening tests pass.
  Full suite green: 229 passed, 16 xfailed, 1 xpassed, 0 failed.

- 2026-08-05 — Plan 03-01 complete (Wave 0 scaffolds, 1/9 plans in Phase 3): `keyring>=25.0` and
  `tomlkit>=0.13` added as core-but-lazy dependencies (installed, confirmed absent from
  `sys.modules` after `import agent86.cli`); 4 backend xfail-scaffolded unit-test modules
  (`test_secrets`, `test_config_writer`, `test_catalog`, `test_providers_key_seam`) and 3 TUI
  xfail-scaffolded Pilot modules (`test_provider_manager`, `test_connection_test`, `test_save_diff`)
  written against the exact interfaces plans 03-02..03-09 must implement, plus 6 fixture files
  (hand-commented TOML + 5 catalog JSON payloads). Work was committed in a prior session
  (2814da7/aaa0649/875015e, 2026-07-21); this session verified every acceptance criterion still
  holds and produced the SUMMARY.md that was never created. Full suite green: 198 passed,
  42 xfailed, 3 xpassed, 0 failed.

- 2026-07-20 — Quick task 260720-1rs complete: fixed Shift+Tab silently doing nothing in the TUI
  instead of cycling the approval mode. Root cause: Textual's `App` ships a default `shift+tab`
  binding for focus traversal that intercepted the key ahead of `Agent86App`'s `cycle_mode`
  binding whenever the prompt `Input` was focused — the same footgun 02-02 documented for `enter`.
  Fixed by marking the binding `priority=True` and guarding `action_cycle_mode` with `SkipAction`
  when a modal is pushed, mirroring the existing `action_palette_up`/`_down`/`_dismiss` pattern.
  New regression test presses the real key via `pilot.press("shift+tab")` (confirmed to fail
  pre-fix, pass post-fix). Full suite green (39 TUI tests).

- 2026-07-20 — Quick task 260720-1jw complete: fixed the TUI `/models` command printing
  `<rich.table.Table object at 0x...>` reprs. Root cause: `_models_tables` returned a tuple
  `(table, roles)` but `CommandResult.render` must be a single renderable and `RichLog.write`
  stringifies a non-renderable tuple. Fixed by returning `Group(table, roles)`; pinning test
  updated. Full suite green (196 tests).

- 2026-07-20 — Plan 02-04 complete (Phase 2 now feature-complete, 4/4 plans): `#palette`
  `OptionList` wired into `Agent86App` — typing `/` filters `COMMANDS` by prefix into a dropdown;
  priority `up`/`down`/`escape` App bindings navigate/dismiss it, each raising `SkipAction` when
  hidden so the key falls through to a focused modal's own widget (a bug found while wiring
  picker chaining — the same footgun 02-02 proved for `enter`, now closed for arrow keys too).
  Enter-routing follows the 02-02 Approach B decision exactly: no permanent priority `enter`
  binding; `on_input_submitted` checks the palette first, otherwise dispatches unchanged.
  Selecting `/model`/`/mode` chains into the Plan 03 pickers via `_run_or_chain`; every path —
  typed, plain-turn, or picker-chained — now funnels through one shared `_dispatch_line` helper.
  Full suite green (196 tests) including D-11 backward-compat and lazy-import guards.

- 2026-07-20 — Plan 02-01 complete: `tui/commands.py::handle_command` refactored from a flat
  if/else chain into a declarative `COMMANDS: list[CommandEntry]` registry (`CommandEntry` =
  name/usage/description/handler/needs_choice/terminal) with `find_command` lookup; `_help_table`
  now renders from `COMMANDS` instead of hand-written rows, so `/help` and the palette can never
  drift. `needs_choice` is `"model"` on `/model` and `"mode"` on `/mode` for Plan 03/04 to consume.
  All existing behavior preserved byte-for-byte (including the `/quit` alias and the `/models` vs
  `/model` prefix edge case), pinned by three new regression tests. Full suite green (190 tests).

- 2026-07-20 — Plan 02-02 complete: wave-0 spike (`tests/tui/test_palette_keys.py`) resolves
  RESEARCH Open Question 1 empirically — a permanent App-level priority `enter` Binding
  suppresses `Input.Submitted` even when its action no-ops. **Enter-routing decision: Approach B**
  — Plan 04 must dynamically bind/unbind `enter` only while the palette is open, never register
  it as a permanent priority binding. `up`/`down` confirmed safe as permanent priority bindings.
  Full suite green (190 tests).

- 2026-07-20 — Plan 01-05 complete: `run_repl` now routes the default rich-capable TTY path to
  `run_tui` (lazy-imported inside the branch), with `--plain`/`AGENT86_PLAIN`/non-TTY and any
  Textual import-or-start failure falling back to the plain loop with a dim note — proven by
  `tests/tui/test_fallback.py` (routing, both fallback paths, textual-free import). Phase 1 is
  now feature-complete (5/5 plans); full suite green (178 tests). Manual Windows Terminal
  verification per 01-VALIDATION.md is still outstanding before declaring the phase fully done.

- 2026-07-20 — Plan 01-04 complete: `Agent86App(App)` composes the RichLog transcript + streaming
  Static line + prompt Input + `StatusFooter`; turns run on a Textual thread worker
  (`run_turn_worker` + `post_message`), the footer stays live during processing, and
  `ApprovalModal` resolves the worker's blocked `threading.Event` on every dismissal path —
  proven by headless `App.run_test()` Pilot tests covering shell, live streaming, and both
  approve/deny approval outcomes. `run_tui(cfg, resume)` is the TUI entry point. Full suite green
  (174 tests).

- 2026-07-20 — Plan 01-02 complete: `StatusFooter(Static)` reactive widget (always_update=True on
  a `StatusState` attribute) makes `format_status_line`'s working/phase branch live, and
  `ApprovalModal(ModalScreen[bool])` resolves approve/deny/escape to an explicit bool on every
  dismissal path — proven by headless `App.run_test()` widget tests. Full suite green (170 tests).

- 2026-07-20 — Plan 01-03 complete: `agent86/tui/commands.py` ports `_Repl.dispatch` slash-command
  behavior into a `CommandResult`/`handle_command`/`startup_notes` adapter that returns renderables
  instead of printing to stdout — proven by parity tests mirroring `tests/integration/test_repl.py`.
  Full suite green (170 tests).

- 2026-07-20 — Plan 01-01 complete: tui package skeleton, textual core-but-lazy dep, Message
  vocabulary (TurnDelta/ToolAnnounce/ApprovalRequest/TurnDone/TurnError), and the turn_bridge
  worker/approval bridge — proven by headless unit tests + lazy-import guard. Full suite green
  (162 tests).

- 2026-07-19 — Phase 1 planned: 5 plans across 4 waves (foundation/turn-bridge → widgets+commands →
  app shell → entry routing/fallback). Wave 0 test scaffolds included per 01-VALIDATION.md.

- 2026-07-19 — Project initialized from a pre-agreed plan (brownfield; codebase already read in
  session, formal mapping skipped). PROJECT.md, config.json, REQUIREMENTS.md, ROADMAP.md written.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260720-1jw | Fix TUI /models rendering bug — wrap tables in a Group | 2026-07-20 | 47da657 | [260720-1jw-fix-tui-models-rendering-bug-wrap-tables](./quick/260720-1jw-fix-tui-models-rendering-bug-wrap-tables/) |
| 260720-1rs | Fix TUI shift+tab not cycling approval mode — priority binding | 2026-07-20 | 2050765 | [260720-1rs-fix-tui-shift-tab-not-cycling-approval-m](./quick/260720-1rs-fix-tui-shift-tab-not-cycling-approval-m/) |
| 260805-xbw | Surface failed tool tracebacks to the model — fix _observe + debugging-discipline prompt | 2026-08-06 | a092502 | [260805-xbw-surface-failed-tool-tracebacks-to-the-mo](./quick/260805-xbw-surface-failed-tool-tracebacks-to-the-mo/) |
| 260813-adr | Make /model catalog picker insert the active provider prefix | 2026-08-13 | 2a63ada | [260813-adr-make-model-catalog-picker-insert-the-act](./quick/260813-adr-make-model-catalog-picker-insert-the-act/) |

- 2026-08-13 — Quick task 260813-adr complete: fixed the TUI `/model` catalog picker dispatching a
  broken ref for every provider (reported via the Ollama entry `nemotron-3.5-lightning:latest`
  producing "Unknown provider 'nemotron-3.5-lightning'"). Root cause: `fetch_catalog` returns bare
  model ids by contract, but `Agent86App._open_model_picker` passed them straight into
  `model_choices` unprefixed, so `ModelRef.parse`'s first-colon split mis-parsed any colon-bearing
  Ollama id and rejected any colon-free id (e.g. openai `gpt-4o`) outright. Added a pure
  `prefix_catalog_refs(provider, entries)` helper in `model_picker.py` (mirroring
  `CatalogPickerModal._catalog_ref`, exact-prefix double-prefix guard) and wired it into
  `_open_model_picker` before `model_choices`, covering both the session-cache and fresh-fetch
  paths. `cognitive/catalog.py` left unmodified. 6 new regression tests (5 pure + 1 end-to-end
  Pilot), confirmed RED against the pre-fix source before finalizing. Full suite green: 436 passed,
  6 skipped, 1 known pre-existing unrelated failure (`test_build_embedder_falls_back_without_torch`).

## Next Step

Phase 3 (secrets-model-provider-config) is now feature-complete and fully gap-closed: 13/13
plans done, all 6 UAT items from `03-HUMAN-UAT.md` resolved (1 passed as-is, 5 gaps diagnosed and
closed by plans 03-10..03-13). Plan 03-13 closed the last blocker, UAT gap 3 (Anthropic SDK
version guard + fail-soft startup) — full suite green at 341 passed, 0 failed. Manual Windows
Terminal verification per `03-VALIDATION.md` §Manual-Only (real keyring round-trip, real
config.toml comment preservation, live OpenRouter/Groq catalog schema check, and a real `hello`
turn against `anthropic:claude-opus-5`) remains outstanding but does not block automated
progress.

Phase 4 (MCP Config UI) is now feature-complete: 8/8 plans done, MCP-01 and the SEC-01
`headers.Authorization` write-path gap both closed. Full suite green at 438 passed, 0 xfailed,
0 failed. Manual Windows Terminal verification of the full `/config mcp` flow against a real MCP
server remains outstanding but does not block automated progress. Next: Phase 5 (Packaging &
Hardening) — TUI-06 formal packaging/hardening.
