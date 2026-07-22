# Phase 3: Secrets + Model/Provider Config - Context

**Gathered:** 2026-07-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Keyring-backed API keys (**SEC-01**) plus an in-app model/provider configuration surface
(**MODEL-01**) that lists, switches, adds, and live-tests providers/models, writing changes back
to `~/.agent86/config.toml` non-destructively with comments preserved (**MODEL-02**).

**In scope:** A `resolve_api_key(provider, pconf)` helper (env-first, then OS keyring) adopted by
every provider constructor; keyring set/clear from within the app; a live model catalog fetched
per provider; a `/config model` manager modal (list / add / test / save); a tomlkit-based
non-destructive write-back with user/project scope selection; enriching the Phase 2 `/model`
picker with the live catalog.

**Out of scope:** MCP server config UI (Phase 4 — MCP-01), packaging/lazy-import hardening and
the plain-loop/`run --json` degradation guarantee (Phase 5 — TUI-06), theming (v2 — POL-01).
This phase does not touch the harness or cognitive loop beyond the api-key seam and
`Harness.set_model`.
</domain>

<decisions>
## Implementation Decisions

### Model catalog source
- **D-01:** The model list is **live-fetched from each provider's models endpoint** at the moment
  the catalog is needed (OpenAI/OpenRouter/Groq `GET /v1/models`, Ollama `GET /api/tags`,
  Anthropic `GET /v1/models`). If the fetch fails, or the provider exposes no such endpoint
  (e.g. llamacpp), **fall back to free-text `provider:model` entry** — never a dead end.
- **D-02:** No hardcoded per-provider model catalog is shipped. The live endpoint is the single
  source of truth so the list cannot go stale between releases.
- **D-03:** Long catalogs (OpenRouter exposes 300+ models) are navigated with a
  **type-to-filter list** — a filter `Input` above an `OptionList` that narrows as the user
  types, deliberately mirroring the Phase 2 `/` palette interaction the user already knows.
- **D-04:** Fetched catalogs are cached **in memory for the app session only**. One fetch per
  launch, lazily on first use. No on-disk cache, no TTL, no invalidation logic.
- **D-05:** Providers with **no resolvable key are still listed**, visibly marked as having no
  key. Selecting one **chains directly into the add-key flow**, then fetches its catalog — so
  "add a provider" and "add a model" are one continuous path rather than two disjoint features.

### Secrets & key resolution
- **D-06:** Introduce **`resolve_api_key(provider_name, pconf)`** with strict precedence:
  **environment variable first** (via `pconf.api_key_env`), **then the OS keyring**. Config
  never stores a plaintext secret. Both `anthropic_provider.py:40` and `openai_provider.py:44`
  currently call `os.getenv` directly — those are the two seams to replace.
- **D-07:** Keyring naming is **service `"agent86"`, account = the config's provider name**
  (`keyring.get_password("agent86", "anthropic")`). Keying on the provider name means a custom
  `[providers.myvllm]` block gets a keyring slot for free, and entries are readable in Windows
  Credential Manager / macOS Keychain.
- **D-08:** When neither env nor keyring yields a key: **in the TUI, a masked key-entry modal
  appears at the point of need**; **in the plain loop and `run --json`, today's `ProviderError`
  is raised unchanged** (message may additionally mention the keyring). The scripting contract
  stays non-interactive.
- **D-09:** keyring being absent (headless/CI) or its backend erroring **falls through silently
  to env-only** — no warning printed, per the milestone constraint. But **keyring availability
  is shown explicitly in `/config` and in the secrets flow**, so "unavailable" is
  distinguishable from "no key stored" when the user goes looking.
- **D-10:** The app supports **storing (overwrite silently) and explicitly clearing** a key, with
  a confirm on clear. **No reveal/unmask action** — a stored secret is never rendered in plaintext
  on screen.

### Connection test
- **D-11:** The live test sends a **tiny real completion** (a ~1-token prompt, `max_tokens=1`)
  through the real `provider_for_ref` path — proving key, `base_url`, model name, and the actual
  completion code path together. Not a models-endpoint ping.
- **D-12:** The test runs **on a worker thread** (same pattern as the existing turn worker) with
  an **inline spinner** and status text in the modal, and a **hard timeout of ~15 seconds**
  producing a clear timeout failure. The app stays responsive throughout. No cancel button.
- **D-13:** A **failed test blocks the default Save path** and shows the provider error verbatim,
  but offers a clearly-labelled **"Save anyway"** override — required for endpoints that are
  legitimately unreachable at configuration time (a local llamacpp server that isn't running, a
  VPN-gated gateway).
- **D-14:** An entered key is held **in memory during the test and only written to the keyring
  once the test passes** (or when "Save anyway" is chosen). A typo'd key never becomes a
  persisted mystery.

### Modal flow & write-back
- **D-15:** **`/model` stays the fast switch-only picker** Phase 2 shipped — now enriched with the
  live catalog (this fulfils Phase 2's deferred D-12). A **new `/config model` opens the full
  manager**: list providers/models, add, test, save, set role slots, clear key. The frequent
  action stays one keystroke; management is a separate, discoverable surface.
- **D-16:** **Scope is chosen at save time**, presented pre-selected to **user**
  (`~/.agent86/config.toml`) with **project** (`./.agent86/config.toml`) one arrow-key away.
  Explicit on every write — the user always knows which file changed.
- **D-17:** Before tomlkit commits, **show the TOML diff** — the exact lines being added/changed
  plus the target file path — with confirm/cancel. This is the user-visible proof that comments
  and surrounding config survive the write (success criterion 3).
- **D-18:** **Switching a model applies immediately in-session** via `Harness.set_model` exactly
  as `/model` does today (success criterion 4). **Persisting it as `model.default` is a separate,
  explicit action** in the manager — a quick experiment must never silently rewrite the default.

### Claude's Discretion
- **D-19:** How each provider's models-endpoint response is normalized into a common
  `(ref, label)` shape, and how the differing schemas (OpenAI `data[].id`, Ollama
  `models[].name`, Anthropic `data[].id`) are adapted. Claude chooses the abstraction — a small
  per-provider catalog function next to the existing provider modules is a reasonable shape.
- **D-20:** What metadata (if any) each catalog row displays beyond the ref — context window,
  pricing, and ownership are inconsistently available across endpoints. Show what's cheaply and
  uniformly available; don't build a metadata layer.
- **D-21:** Exact modal composition, widget ids, CSS, and how the type-to-filter list is wired,
  consistent with the Phase 1 layout and the `ModalScreen[T]` conventions in
  `tui/screens/approval.py` and `tui/screens/model_picker.py`.
- **D-22:** How `keyring` and `tomlkit` are added to `pyproject.toml` and lazy-imported so the
  `run` (one-shot) and `--plain` cold-start paths never import them (project constraint).
- **D-23:** Whether editing an existing provider's `base_url` / `num_ctx` is exposed in the
  manager this phase. Include it only if it falls out naturally from the add-provider flow;
  it is not a success criterion.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The api-key seam (SEC-01)
- `src/agent86/cognitive/anthropic_provider.py` §`AnthropicProvider.__init__` (line ~40) — the
  `key_env = config.api_key_env or "ANTHROPIC_API_KEY"` / `os.getenv` block to replace with
  `resolve_api_key`, and the exact `ProviderError` message the plain loop must keep raising.
- `src/agent86/cognitive/openai_provider.py` §`OpenAIProvider.__init__` (line ~44) — the second
  `os.getenv` seam, including the `require_key` flag that marks keyless local endpoints.
- `src/agent86/cognitive/base.py` §`provider_for_ref` (lines ~70–110) — provider dispatch, the
  `base_url`-implies-OpenAI-compatible fallback, and the `require_key=bool(pconf.api_key_env)`
  rule that keyring resolution must not break for keyless local endpoints.
- `src/agent86/cognitive/llamacpp_provider.py`, `src/agent86/cognitive/ollama_provider.py` —
  local, typically keyless providers; confirm they stay working with no key present.

### Config schema & write-back (MODEL-02)
- `src/agent86/config.py` — `ProviderConfig` (`api_key_env`, `base_url`, `num_ctx`),
  `ModelConfig`/`ModelRoute` (`default`, `route.cheap`, `route.frontier`, `context_window`),
  `_default_providers()` (the six seeded providers), `load_config`, `_deep_merge`,
  `_read_toml` (currently **read-only `tomllib`** — the write path is new), `config_paths`,
  `USER_CONFIG_PATH`, `PROJECT_CONFIG_PATH`.
- `src/agent86/types.py` — `ModelRef.parse` (validate refs from the catalog and free-text entry).

### TUI integration points
- `src/agent86/tui/commands.py` — `COMMANDS` registry / `CommandEntry` (name, usage, description,
  handler, `needs_choice`, `terminal`), `find_command`, `handle_command`, `CommandResult`,
  `_models_tables`, `_set_model`, `_help_table`. New `/config model` must be a registry entry so
  the palette and `/help` pick it up automatically.
- `src/agent86/tui/screens/model_picker.py` — `model_choices(cfg)` and `ModelPickerModal`; the
  module docstring explicitly names Phase 3 as the owner of the richer catalog (Phase 2 D-12).
- `src/agent86/tui/screens/approval.py` — the `ModalScreen[T]` contract every dismissal path must
  resolve; mirror it for the new modals.
- `src/agent86/tui/app.py` — `Agent86App`, `_dispatch_line` / `_run_or_chain` (the shared command
  dispatch and picker-chaining helper the new modals must route through), the thread-worker +
  `post_message` pattern to reuse for the connection test, `BINDINGS`, CSS.
- `src/agent86/tui/turn_bridge.py` — the existing worker/approval bridge; the reference for
  running blocking work off the UI thread.
- `src/agent86/orchestration/loop.py` — `Harness.set_model`, `provider` (live model application
  for success criterion 4).

### Prior phase decisions (patterns to honor)
- `.planning/phases/02-command-palette-menus/02-CONTEXT.md` — command-registry-as-single-source-
  of-truth (D-04/D-05), picker chaining (D-10), typed commands must keep working (D-11), and the
  deferred catalog note (D-12) this phase closes.
- `.planning/phases/01-tui-skeleton-live-status-line/01-CONTEXT.md` — Textual-only-inside-`tui/`,
  layout, plain loop and `run --json` untouched.

### Packaging constraint
- `pyproject.toml` — core dependency list (keyring and tomlkit are **not yet present**; both must
  be added and lazy-imported so `run`/`--plain` cold start does not regress).
- `CLAUDE.md` §Constraints — the performance/compatibility rules this phase must not violate.
- `src/agent86/cli.py` — `config` command output (line ~222 renders `api_key_env` per provider);
  keyring status should be surfacible here too, and nothing new may be imported at module load.

No external specs or ADRs exist for this project — requirements are fully captured in the
decisions above, ROADMAP.md Phase 3, and REQUIREMENTS.md (SEC-01, MODEL-01, MODEL-02).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tui/screens/approval.py::ApprovalModal` and `tui/screens/model_picker.py::ModelPickerModal` —
  the `ModalScreen[T]` pattern (every dismissal path resolves explicitly) to mirror for the
  key-entry, catalog, test, and save-confirm modals.
- `tui/turn_bridge.py` + `Agent86App`'s thread worker / `post_message` flow — the proven pattern
  for running the blocking connection test without freezing the UI.
- `tui/commands.py::COMMANDS` registry — adding `/config model` as an entry gives palette
  autocomplete and `/help` for free (Phase 2 D-04).
- `tui/app.py::_dispatch_line` / `_run_or_chain` — the single funnel every command path already
  goes through; new modals chain through it rather than inventing a parallel route.
- `config.py::_deep_merge`, `load_config` — reload-after-write semantics come for free if the
  write path reuses the existing loader.

### Established Patterns
- All Textual code lives in `src/agent86/tui/`; `ui/repl.py` and the plain loop are never touched.
- Commands return renderables via `CommandResult` rather than printing.
- Providers are constructed lazily inside `provider_for_ref`, with SDK imports inside `__init__` —
  the connection test should go through this same path, not a bespoke HTTP call.
- Provider SDKs are optional extras; the test must degrade with a clear message when a provider's
  SDK isn't installed rather than crashing the modal.

### Integration Points
- **`resolve_api_key`** is the new chokepoint: called by `AnthropicProvider.__init__`,
  `OpenAIProvider.__init__`, and any keyless-endpoint logic in `provider_for_ref`.
- **Config write-back** is entirely new — `config.py` currently reads TOML only (`tomllib`).
  tomlkit round-trip write plus scope selection is net-new surface.
- **`/config model`** enters through the command registry; **`/model`** keeps its existing entry
  but its choice source becomes the live catalog.
- **`Harness.set_model`** applies a switch live; the config write is the separate persist step.
</code_context>

<specifics>
## Specific Ideas

- The add-a-provider path should feel continuous: see a provider with no key → enter the key
  masked → it tests → catalog appears → pick a model → see the TOML diff → save. One flow, not
  four disconnected commands.
- The TOML diff preview is deliberately a trust-building artifact: the user should be able to see
  with their own eyes that their hand-written comments in `~/.agent86/config.toml` survived.
- Never print a stored secret to the screen or the transcript, and never write one to config.
- Filtering a long catalog should feel like the `/` palette from Phase 2 — same muscle memory.

</specifics>

<deferred>
## Deferred Ideas

- **MCP server list/add/remove/test UI** — Phase 4 (MCP-01). The tomlkit write-back and
  connection-test patterns built here should be reusable there; design them with that in mind but
  do not build MCP surface in this phase.
- **Plain-loop / `run --json` degradation guarantees and lazy-import hardening as a verified
  contract** — Phase 5 (TUI-06). This phase must not *break* them, but proving them is Phase 5.
- **On-disk catalog caching with a TTL** — rejected for this phase (D-04); revisit only if
  per-launch fetch latency proves annoying.
- **Recency/usage ranking of model choices** — considered for long-list navigation, deferred
  because it requires persisting usage state.
- **Revealing a stored key in plaintext** — explicitly rejected (D-10), not merely deferred.
- **Per-project scoped secrets** (keyring entries keyed by project) — not in scope; keyring
  entries are global per provider (D-07).
- **Theming / color schemes for the new modals** — v2 (POL-01).

</deferred>

---

*Phase: 03-secrets-model-provider-config*
*Context gathered: 2026-07-21*
