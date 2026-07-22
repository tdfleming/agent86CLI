# Phase 3: Secrets + Model/Provider Config - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-21
**Phase:** 03-secrets-model-provider-config
**Areas discussed:** Model catalog source, Key storage & fallback, Connection-test UX, Modal flow & write-back

---

## Model catalog source

### Q1 — Where should the list of selectable models come from?

| Option | Description | Selected |
|--------|-------------|----------|
| Live fetch, typed fallback | Query the provider's models endpoint at modal-open; fall back to free-text ref entry on failure or when no endpoint exists | ✓ |
| Curated static list | Hand-maintained per-provider list in the codebase; offline but goes stale | |
| Live fetch + curated seed | Curated shortlist shown immediately, live results merged in | |
| Free-text only | No catalog; the connection test validates what's typed | |

**User's choice:** Live fetch, typed fallback → D-01, D-02

### Q2 — How should a long catalog (OpenRouter 300+) be made navigable?

| Option | Description | Selected |
|--------|-------------|----------|
| Type-to-filter list | Filter input above an OptionList, mirroring the Phase 2 `/` palette | ✓ |
| Plain scrollable list | Arrow keys only, consistent with existing model_picker | |
| Filter + recency ranking | Filter plus pinned recently-used/configured refs | |

**User's choice:** Type-to-filter list → D-03
**Notes:** Recency ranking deferred — requires persisting usage state.

### Q3 — Should fetched catalogs be cached between app runs?

| Option | Description | Selected |
|--------|-------------|----------|
| In-memory only | Fetch once per app session, no disk state | ✓ |
| On-disk TTL cache | Persist to ~/.agent86/cache/ with a TTL | |
| No caching | Re-fetch on every display | |

**User's choice:** In-memory only → D-04
**Notes:** On-disk TTL caching recorded as a deferred idea.

### Q4 — Should providers with no key configured still be listed?

| Option | Description | Selected |
|--------|-------------|----------|
| List provider, prompt for key | Show marked "no key"; selecting chains into the add-key flow, then fetches | ✓ |
| Hide until keyed | Only show providers whose key resolves | |
| List, error on select | Show everything; selecting an unkeyed provider reports the missing key and stops | |

**User's choice:** List provider, prompt for key → D-05

---

## Key storage & fallback

### Q1 — What should `resolve_api_key` do when neither env nor keyring has a key?

| Option | Description | Selected |
|--------|-------------|----------|
| Modal prompt in TUI, error in plain | Masked key-entry modal at point of need in the TUI; plain loop / `run --json` raise today's ProviderError unchanged | ✓ |
| Always error | Return None and let providers raise as they do now | |
| Prompt everywhere | Interactive prompt in both TUI and plain loop | |

**User's choice:** Modal prompt in TUI, error in plain → D-08
**Notes:** Preserves the non-interactive scripting/CI contract.

### Q2 — How should keys be named in the OS keyring?

| Option | Description | Selected |
|--------|-------------|----------|
| Service `agent86`, account = provider | `keyring.get_password("agent86", "anthropic")`; custom provider blocks get a slot for free | ✓ |
| Account = api_key_env name | Mirrors the env var it shadows; breaks for providers with no api_key_env | |
| Service per provider | `keyring.get_password("agent86:anthropic", "api_key")`; scatters entries across service names | |

**User's choice:** Service `agent86`, account = provider → D-07

### Q3 — How should keyring absence or backend failure surface?

| Option | Description | Selected |
|--------|-------------|----------|
| Silent fallback, visible on demand | Falls through to env-only silently; keyring status shown in `/config` and the secrets modal | ✓ |
| Fully silent | Never mention keyring when unavailable | |
| One-time warning | Dim note the first time keyring is needed and unavailable | |

**User's choice:** Silent fallback, visible on demand → D-09
**Notes:** Satisfies the milestone's "silently fall through to env vars" constraint while staying diagnosable.

### Q4 — Should stored keys be deletable/overwritable from within the app?

| Option | Description | Selected |
|--------|-------------|----------|
| Set and clear | Store (overwrite silently) plus an explicit clear with confirm | ✓ |
| Set only | Removal requires the OS keychain UI | |
| Set, clear, and reveal | Also allow unmasking the stored key on demand | |

**User's choice:** Set and clear → D-10
**Notes:** Reveal explicitly rejected — a live secret must never render on screen.

---

## Connection-test UX

### Q1 — What should the live connection test send?

| Option | Description | Selected |
|--------|-------------|----------|
| Tiny real completion | ~1-token prompt, max_tokens=1, through the real provider_for_ref path | ✓ |
| Models-endpoint ping | GET /v1/models with the key; free but doesn't confirm the model responds | |
| Completion, models-ping fallback | Try completion, fall back to a ping | |

**User's choice:** Tiny real completion → D-11
**Notes:** Directly satisfies success criterion 2 ("confirms a response before saving").

### Q2 — What shows while testing, and what timeout?

| Option | Description | Selected |
|--------|-------------|----------|
| Inline spinner, ~15s timeout | Spinner + status text, run on a worker thread; hard 15s timeout | ✓ |
| Blocking with disabled buttons | Static "Testing…" text, controls frozen | |
| Spinner, cancellable | Spinner plus explicit Cancel of the in-flight test | |

**User's choice:** Inline spinner, ~15s timeout → D-12
**Notes:** Cancellation rejected — thread cancellation of a blocking SDK call adds real complexity.

### Q3 — Should a failed test block saving?

| Option | Description | Selected |
|--------|-------------|----------|
| Block, with explicit override | Failure blocks the default Save; a labelled "Save anyway" escape hatch exists | ✓ |
| Hard block | No save until the test passes | |
| Warn only | Show the failure, let Save proceed | |

**User's choice:** Block, with explicit override → D-13
**Notes:** Override needed for legitimately-offline endpoints (local llamacpp, VPN-gated gateway).

### Q4 — Store the key before or after the test passes?

| Option | Description | Selected |
|--------|-------------|----------|
| After a passing test | Held in memory during the test; persisted only on pass (or Save anyway) | ✓ |
| Immediately on entry | Store then test; bad keys accumulate in the keychain | |

**User's choice:** After a passing test → D-14

---

## Modal flow & write-back

### Q1 — How does the config surface relate to the Phase 2 `/model` picker?

| Option | Description | Selected |
|--------|-------------|----------|
| Keep /model, add /config model | `/model` stays the fast switcher (enriched with the live catalog); `/config model` is the full manager | ✓ |
| One modal does everything | Replace the picker with a single manager modal | |
| /model with an "Add new…" row | Append an add entry to the existing picker | |

**User's choice:** Keep /model, add /config model → D-15
**Notes:** Preserves the Phase 2 deliverable and keeps the frequent action one keystroke.

### Q2 — When is the user/project scope choice presented?

| Option | Description | Selected |
|--------|-------------|----------|
| Ask at save, default user | Scope selector at save, pre-set to user, project one arrow-key away | ✓ |
| Silent user default, /scope override | Always user unless explicitly switched beforehand | |
| Infer from existing config | Write to whichever file already defines that provider | |

**User's choice:** Ask at save, default user → D-16

### Q3 — Show a write-back preview before tomlkit commits?

| Option | Description | Selected |
|--------|-------------|----------|
| Show the TOML diff | Exact lines added/changed plus the target path, with confirm/cancel | ✓ |
| Confirm with a summary | Plain-language summary plus confirm | |
| Write immediately | No confirmation — the test already gated it | |

**User's choice:** Show the TOML diff → D-17
**Notes:** Framed as trust-building — visible proof that hand-written comments survive.

### Q4 — What gets written vs. held in memory when switching?

| Option | Description | Selected |
|--------|-------------|----------|
| Live now, persist optional | Switch applies immediately via Harness.set_model; persisting as model.default is a separate action | ✓ |
| Switch always persists | Every switch also writes model.default | |
| Ask each switch | Prompt "also make this the default?" after switching | |

**User's choice:** Live now, persist optional → D-18
**Notes:** A quick experiment must never silently rewrite the default.

---

## Claude's Discretion

Left to Claude during research/planning (see CONTEXT.md D-19 … D-23):
- Normalizing differing models-endpoint response schemas into a common `(ref, label)` shape
- What metadata, if any, each catalog row displays beyond the ref
- Exact modal composition, widget ids, CSS, and filter wiring
- How `keyring` and `tomlkit` are added to `pyproject.toml` and lazy-imported
- Whether editing an existing provider's `base_url` / `num_ctx` is exposed this phase

## Deferred Ideas

- MCP server config UI — Phase 4 (MCP-01)
- Plain-loop / `run --json` degradation as a *verified* contract — Phase 5 (TUI-06)
- On-disk catalog caching with a TTL
- Recency/usage ranking of model choices
- Per-project scoped secrets
- Theming for the new modals — v2 (POL-01)
- Revealing a stored key in plaintext — rejected outright, not deferred

## Todos Cross-Referenced

None — `gsd-tools todo match-phase 3` returned 0 pending todos.
