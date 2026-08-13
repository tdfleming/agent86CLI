---
phase: quick-260813-atc
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/agent86/tui/screens/model_picker.py
  - src/agent86/tui/app.py
  - src/agent86/tui/messages.py
  - tests/tui/test_pickers.py
  - tests/tui/test_app.py
  - tests/tui/test_commands.py
autonomous: true
requirements: [QUICK-260813-atc]

must_haves:
  truths:
    - "Typing `/model nemotron-3.5-lightning:latest` in the TUI while ollama is the active provider switches the model and echoes a `resolved to ollama:nemotron-3.5-lightning:latest` line."
    - "Typing a typo (`nemotron-3.5-lightnin:latest`) that is NOT in the active provider's catalog surfaces the existing strict `Unknown provider ...` error, byte-unchanged, with no fallback attempt."
    - "Typing `gpt-4o` while ollama is active surfaces the existing strict `must be 'provider:model'` error, unchanged."
    - "An already-valid ref (`anthropic:claude-opus-4-8`) switches on the strict path and never consults the catalog."
    - "A syntactically valid ref naming a KNOWN provider that fails for an unrelated reason (missing key, build error) surfaces its strict error immediately — no catalog fetch of the active provider, no 'fetching … catalog' noise."
    - "With a cold catalog cache, the bare-ref resolution completes after `CatalogReady` arrives, without blocking the UI."
    - "A pending bare-ref dispatch is ALWAYS validated against the catalog of the provider that was active when it was dispatched — an intervening successful `/model` switch to another provider can never cause one entry to be validated against the other provider's catalog."
    - "Overlapping `/model <bad-ref>` dispatches issued before their cold-cache fetches resolve each produce exactly one visible outcome — none is silently dropped — and exactly one catalog fetch is issued PER PROVIDER."
    - "A failed or empty catalog fetch falls through to the strict error — never a silent retry, never a silent drop."
    - "`agent86.tui.commands.handle_command` and the plain loop keep strict `ModelRef` parsing — the fallback is TUI-app-layer only."
  artifacts:
    - path: "src/agent86/tui/screens/model_picker.py"
      provides: "Pure `catalog_has_ref(ref, entries)` bare-id membership test, alongside `prefix_catalog_refs`"
      exports: ["catalog_has_ref", "prefix_catalog_refs", "model_choices", "ModelPickerModal"]
    - path: "src/agent86/tui/app.py"
      provides: "`_dispatch_model` / `_is_bare_ref_candidate` gate / `_finish_model_fallback` / `_provider_key`, a provider-tagged `_pending_model` queue with a `_model_fetch_inflight` set, and the `model_fallback` CatalogReady purpose"
      contains: "model_fallback"
    - path: "tests/tui/test_app.py"
      provides: "Pilot regression tests for warm-cache match, typo non-match, colon-free non-match, valid-ref passthrough, known-provider auth failure (no fetch), cold-cache completion, catalog-failure fallthrough, overlapping dispatches, and cross-provider stranding"
    - path: "tests/tui/test_commands.py"
      provides: "Strict-parsing pin proving the adapter (and therefore --plain) is unchanged"
  key_links:
    - from: "src/agent86/tui/app.py::_dispatch_line"
      to: "src/agent86/tui/app.py::_dispatch_model"
      via: "entry.name == '/model' and arg interception before handle_command"
      pattern: "_dispatch_model"
    - from: "src/agent86/tui/app.py::_dispatch_model"
      to: "agent86.tui.commands.handle_command"
      via: "strict attempt first; provider-identity comparison detects failure (no dispatch duplication)"
      pattern: "handle_command\\(self\\.repl, f\"/model"
    - from: "src/agent86/tui/app.py::_dispatch_model"
      to: "src/agent86/tui/app.py::_is_bare_ref_candidate"
      via: "gate — only a plausible first-colon-split failure may reach the catalog branch"
      pattern: "_is_bare_ref_candidate"
    - from: "src/agent86/tui/app.py::_dispatch_model"
      to: "src/agent86/tui/app.py::_request_catalog"
      via: "purpose='model_fallback', issued once per provider via the _model_fetch_inflight set"
      pattern: "_model_fetch_inflight"
    - from: "src/agent86/tui/app.py::on_catalog_ready"
      to: "src/agent86/tui/app.py::_finish_model_fallback"
      via: "purpose branch BEFORE the CatalogPickerModal fallthrough; resolves only entries whose captured provider == message.provider, re-queues the rest"
      pattern: "purpose == \"model_fallback\""
    - from: "src/agent86/tui/app.py::_finish_model_fallback"
      to: "agent86.tui.screens.model_picker.catalog_has_ref"
      via: "catalog vouches for the typed string before any retry"
      pattern: "catalog_has_ref"
---

<objective>
Make the TUI's typed `/model <bare-ref>` path recover from `ModelRef.parse`'s first-colon split by
retrying as `<active-provider>:<typed-string>` — but **only** when the active provider's live model
catalog vouches for the typed string verbatim. A non-match keeps today's strict error, unchanged.

Purpose: `/model nemotron-3.5-lightning:latest` currently errors with
`Unknown provider 'nemotron-3.5-lightning'` because `ModelRef.parse` (`types.py:66-76`) splits on the
FIRST colon and Ollama ids carry their own `:tag`. Quick task 260813-adr fixed this for the *picker*
path (`prefix_catalog_refs`); this closes the *typed* path. Requiring a catalog hit means a real typo
still fails loudly at type time instead of being masked as a provider-side "model not found" at
request time.

Output: a pure `catalog_has_ref` helper, app-layer fallback wiring with a new `model_fallback`
catalog purpose, and 11 regression tests.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260813-adr-make-model-catalog-picker-insert-the-act/260813-adr-SUMMARY.md
@src/agent86/tui/app.py
@src/agent86/tui/screens/model_picker.py
@src/agent86/tui/commands.py
@src/agent86/tui/messages.py
@tests/tui/test_app.py
@tests/tui/test_pickers.py
@tests/tui/test_commands.py

<decisions>
**LOCKED (user chose this over two alternatives — do not substitute an always-retry scheme):**
catalog-validated fallback, then echo.

- On a failed typed ref, look up the **whole typed string** in the **active provider's** catalog.
- Catalog hit → retry as `<active-provider>:<typed-string>` AND echo a confirmation line
  (`resolved to ollama:nemotron-3.5-lightning:latest`) so the user sees what happened.
- Catalog miss → **no** fallback; surface the existing strict error **byte-unchanged**.
  Preserving the strict error is the feature. Do NOT add fuzzy matching, did-you-mean, or a
  best-effort retry.

**Scope boundaries (deliberate, state them in the SUMMARY — they are not omissions):**
- **TUI-only by design.** `src/agent86/ui/repl.py` and `run --json` have no catalog and MUST keep
  strict `ModelRef` parsing — CLAUDE.md makes them the scripting/CI contract. The fallback lives in
  `Agent86App` only; `tui/commands.py::handle_command` stays strict so the adapter's plain-loop
  parity holds.
- **Do NOT change** `ModelRef.parse` (`src/agent86/types.py`).
- **Do NOT change** `fetch_catalog`'s bare-id contract (`src/agent86/cognitive/catalog.py`) — it is
  load-bearing for `CatalogPickerModal` and for 260813-adr's `prefix_catalog_refs`; changing it
  would double-prefix the `/config model` path.
- **Do NOT duplicate `_Repl.dispatch` logic.** `tui/commands.py`'s module docstring is explicit that
  it adapts, never re-implements, dispatch. The chosen seam (below) preserves that.

**Chosen seam — app layer, around dispatch (Task 2 must follow this):**
`Agent86App._dispatch_line` intercepts `/model <arg>` and routes it to a new `_dispatch_model(arg)`,
which calls the ordinary `handle_command(self.repl, f"/model {arg}")` **first** (the strict path,
zero duplication) and detects failure by comparing `self.repl.harness.provider` identity before and
after. `Harness.set_model`'s docstring (`orchestration/loop.py:130-143`) guarantees the current
provider is left unchanged on failure and replaced with a new object on success, so identity is an
exact success signal. The strict error text (`result.render`) is *held back* rather than written, so
a successful fallback never shows a scary error first; on a catalog miss it is written verbatim.

Why not the alternatives: `_set_model` in `commands.py` cannot reach `_catalog_cache` (it only gets
`repl`), and passing a lookup callable in would either change the `CommandEntry` handler signature
or stash a TUI-only attribute on the shared `_Repl` — both leak TUI concerns into the adapter that
the plain loop shares. Keeping the whole fallback in `app.py` keeps `commands.py` strict and keeps
the plain-loop boundary self-evident.

**Failure-shape gate (checker warning 1 — do not skip).** A `set_model` failure is not automatically
a colon-split failure. `/model anthropic:claude-opus-4-8` with no key fails for an auth reason and
names its *target* provider explicitly; entering the catalog branch there would fetch the catalog of
the *currently active* (unrelated) provider, emitting a real network call plus
`fetching … model catalog…` / `catalog unavailable` noise before the correct strict error finally
appears. So `_dispatch_model` only reaches the catalog branch when the failure is *plausibly* the
first-colon-split ambiguity — see `_is_bare_ref_candidate` in Task 2.

**Pending-state shape (checker warnings 2 and 3 — do not skip).** Cold-cache resolution is deferred
to `on_catalog_ready`, which creates two distinct hazards:

  *(a) Clobbering.* With a single pending slot, a second `/model` dispatch inside the fetch window
  overwrites the first; the first `CatalogReady` answers the *second* arg and one command vanishes
  with zero feedback. A silent DROP is worse than the silent retry the locked decision already
  forbids.

  *(b) Cross-provider stranding.* The active provider can change **between** two queued dispatches,
  via an unrelated dispatch that succeeded on the strict path and returned early without ever
  touching the queue:
  ```
  /model nemotron-3.5-lightning:latest   # ollama active, cold -> queued, ollama fetch starts
  /model anthropic:claude-opus-4-8       # succeeds strictly -> active provider is now anthropic
  /model gpt-4o                          # fails, candidate, anthropic cold -> queued
  <ollama CatalogReady arrives>          # must NOT validate gpt-4o against ollama's catalog
  ```
  A naive drain would validate `gpt-4o` against ollama's catalog; on a coincidental match the user
  is told `resolved to ollama:gpt-4o` and switched to the wrong provider, violating the locked
  decision that validation happens against the **active** provider's catalog.

**Decision: `_pending_model` is a list of `(arg, strict_error, provider)` triples — the provider
active at dispatch time is captured per entry — plus a `_model_fetch_inflight: set[str]` recording
which providers have a fetch outstanding.** The drain resolves only entries whose captured provider
equals `message.provider` and re-queues the rest untouched. Chosen over the two alternatives the
checker floated for hazard (a) because:
  - a monotonic-token map would need the token to survive the round trip, and `CatalogReady`
    (`tui/messages.py`) carries no correlation field — the token would have to be smuggled inside
    the free-form `purpose` string and re-parsed in `on_catalog_ready`, complicating the routing the
    checker already cleared;
  - a "reject while pending" flag gives the second dispatch a non-answer and introduces a
    stuck-flag failure mode that would wedge `/model` for the rest of the session.

Invariants Task 2 must uphold (and Task 3 must test):
  1. **Every dispatch yields exactly one user-visible outcome** — a `resolved to …` + retry result,
     or the strict error, exactly once, on every path including a stranded entry whose own later
     fetch fails or returns empty.
  2. **Exactly one fetch per provider per burst** — gated on `_model_fetch_inflight`, NOT on queue
     length. (Queue length was the original formulation and is wrong: entry #3 above finds a
     non-empty queue and would never issue anthropic's fetch, silently piggybacking on ollama's.)
  3. **An entry is only ever validated against its own captured provider's catalog.**
</decisions>

<interfaces>
<!-- Contracts the executor needs. Do not go exploring; these are current as of this plan. -->

From `src/agent86/tui/screens/model_picker.py` (260813-adr):
```python
def prefix_catalog_refs(provider: str, entries: list[tuple[str, str]] | None) -> list[tuple[str, str]]:
    """Prefix bare catalog (ref, label) pairs with `provider:`. Double-prefix guard is an EXACT
    f"{provider}:" prefix match only — 'contains a colon' is NOT a valid already-prefixed test."""
__all__ = ["ModelPickerModal", "model_choices", "prefix_catalog_refs"]
```

From `src/agent86/tui/app.py`:
```python
self._catalog_cache: dict[str, list[tuple[str, str]]] = {}   # __init__, line ~112

def _dispatch_line(self, line: str) -> None:
    log = self.query_one("#transcript", RichLog)
    log.write(f"[bold]> {line}[/bold]")
    match = find_command_for_line(line)
    if match is not None:
        entry, arg = match
        if entry.needs_choice and not arg:
            self._run_or_chain(entry)
            return
    result = handle_command(self.repl, line)
    ...  # exit / turn / handled+noop, then footer refresh

def _request_catalog(self, provider: str, api_key: str | None, purpose: str) -> None:
    """Serves from self._catalog_cache when warm (posts CatalogReady immediately);
    otherwise writes 'fetching … catalog…' and starts the @work(thread=True) fetch."""

def on_catalog_ready(self, message: CatalogReady) -> None:
    if message.error is None:
        self._catalog_cache[message.provider] = message.entries
    else:
        ...write "[yellow]catalog unavailable:[/yellow] ..."
    if message.purpose == "model_picker":
        self._open_model_picker(message.entries)
        return
    self.push_screen(CatalogPickerModal(...), self._on_catalog_picked)   # "manager" fallthrough
```

From `src/agent86/tui/commands.py`:
```python
@dataclass
class CommandResult:
    action: str          # "handled" | "turn" | "exit" | "noop"
    render: Any | None = None

def find_command_for_line(line: str) -> tuple[CommandEntry, str] | None: ...
def handle_command(repl, line: str) -> CommandResult: ...
def _set_model(repl, arg) -> str:   # returns str(exc) on ProviderError/ValueError — no raise
```

From `src/agent86/orchestration/loop.py`:
```python
def set_model(self, model_str: str) -> ModelProvider:
    """...Raises ProviderError/ValueError if the ref is unknown or its API key is missing,
    in which case the current model is left unchanged."""
    from agent86.cognitive.base import provider_for_model   # function-local: monkeypatchable
```

From `src/agent86/cognitive/base.py::_build_provider` — the provider names that resolve WITHOUT a
`[providers.X]` config block (needed by the gate; see the drift note in Task 2):
```python
"anthropic" | "ollama" | "openai" | "openai-compatible" | "llamacpp"
# ...else: any name with a configured base_url is treated as OpenAI-compatible
# ...else: raise ProviderError(f"Unknown provider '{ref.provider}'. ...")
```

Test conventions (`tests/tui/test_app.py`):
```python
def _make_repl(tmp_path, provider, approval=ApprovalMode.AUTO)   # real Harness + real _Repl
async def _wait_until(predicate, timeout=5.0, interval=0.02)
# Active-provider override trick used by the 260813-adr test:
repl.harness.provider.name = "ollama"   # instance attr shadows the fake provider's class attr
# Catalog seeding: app._catalog_cache["ollama"] = [("nemotron-3.5-lightning:latest", "...")]
# Cold-cache tests monkeypatch agent86.cognitive.catalog.fetch_catalog (never the network)
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Pure `catalog_has_ref` helper + unit tests</name>
  <files>src/agent86/tui/screens/model_picker.py, tests/tui/test_pickers.py</files>
  <behavior>
    - `catalog_has_ref("nemotron-3.5-lightning:latest", [("nemotron-3.5-lightning:latest", "…")])` → True
    - `catalog_has_ref("nemotron-3.5-lightnin:latest", <same catalog>)` → False (typo, one char off)
    - `catalog_has_ref("gpt-4o", <ollama catalog>)` → False
    - `catalog_has_ref("ollama:llama3.1", [("llama3.1", "llama3.1")])` → False — catalog refs are
      BARE; an already-prefixed string must never match, so a valid ref can never trip the fallback
    - `catalog_has_ref("x", None)` and `catalog_has_ref("x", [])` → False (cold/failed catalog)
    - Matching is exact and case-sensitive; the label half of each pair is never consulted
  </behavior>
  <action>
Add a module-level pure function `catalog_has_ref(ref, entries)` to
`src/agent86/tui/screens/model_picker.py`, directly beneath `prefix_catalog_refs` (same file: both
are pure helpers that encode `fetch_catalog`'s bare-id contract, and `app.py` already imports from
here). Signature:

```python
def catalog_has_ref(ref: str, entries: list[tuple[str, str]] | None) -> bool:
```

Body: `return any(entry_ref == ref for entry_ref, _label in entries or [])`.

Docstring must state: `fetch_catalog` returns BARE model ids by documented contract, so the
comparison is against the `ref` half of each `(ref, label)` pair only — never the label, which may
be a provider-supplied display name (OpenRouter's `data[].name`). Exact, case-sensitive match: this
is the guard that keeps a typo from being masked as a provider-side "model not found" at request
time (the user's locked decision), so no normalization, no fuzzy matching, no `startswith`.
Note that a `None`/empty `entries` (cold or failed catalog) returns False so the caller falls
through to the strict error.

Add `"catalog_has_ref"` to `__all__`.

Add the six behavior cases above as pure tests in `tests/tui/test_pickers.py`, following the
existing `prefix_catalog_refs` test style in that file (plain sync functions, no Pilot). Include at
least one test that pairs `catalog_has_ref` with `prefix_catalog_refs` and `ModelRef.parse` to pin
the end-to-end contract: a bare colon-bearing Ollama id that the catalog vouches for, once prefixed,
parses to provider `ollama` / model `nemotron-3.5-lightning:latest`.
  </action>
  <verify>
    <automated>C:\Projects\agent86CLI\.venv\Scripts\python.exe -m pytest tests/tui/test_pickers.py -q</automated>
    <automated>C:\Projects\agent86CLI\.venv\Scripts\python.exe -m ruff check src/agent86/tui/screens/model_picker.py tests/tui/test_pickers.py</automated>
  </verify>
  <done>`catalog_has_ref` exists, is exported in `__all__`, and all six behavior cases plus the
  prefix+parse round-trip pass. `prefix_catalog_refs`, `model_choices`, and `ModelPickerModal` are
  byte-unchanged (`git diff` shows only the added function and the `__all__` line).</done>
</task>

<task type="auto">
  <name>Task 2: Wire the catalog-validated fallback into `Agent86App`</name>
  <files>src/agent86/tui/app.py, src/agent86/tui/messages.py</files>
  <action>
All changes are in the app layer. Do not touch `tui/commands.py`, `ui/repl.py`, `types.py`, or
`cognitive/catalog.py`.

**1. Import + module constant + pending state.** Add `catalog_has_ref` to the existing
`from agent86.tui.screens.model_picker import ...` line. Add a module-level constant near
`__all__`:
```python
#: Provider names `cognitive.base._build_provider` resolves without a [providers.X] config block.
#: Used ONLY as a failure-shape heuristic (see _is_bare_ref_candidate). Under-inclusion is safe —
#: a future built-in missing from this set costs one extra catalog lookup whose miss re-emits the
#: same strict error, never a different outcome. Over-inclusion would be the harmful direction
#: (it would wrongly suppress the catalog branch), so keep this an exact mirror of that chain.
_BUILTIN_PROVIDERS = frozenset({"anthropic", "openai", "openai-compatible", "ollama", "llamacpp"})
```
In `Agent86App.__init__`, beside the other chain state:
```python
# /model bare-ref fallback. A LIST of (arg, strict_error, provider) triples, not a slot:
#  - two /model dispatches inside one fetch window must each still get an answer;
#  - the provider is captured PER ENTRY because an intervening successful /model switch can
#    change the active provider between two queued dispatches — an entry must only ever be
#    validated against the catalog of the provider that was active when it was dispatched.
self._pending_model: list[tuple[str, Any, str]] = []
# Providers with a model_fallback catalog fetch outstanding — one fetch per provider per burst.
self._model_fetch_inflight: set[str] = set()
```
(`Any` needs `from typing import Any` if not already imported — `strict_error` is a str or a Rich
renderable.)

**2. Extract `_provider_key`.** `_run_or_chain`'s `"model"` branch already resolves the active
provider's key in four lines; the new path needs the same. Extract:
```python
def _provider_key(self, provider: str) -> str | None:
    from agent86.config import ProviderConfig
    from agent86.secrets import resolve_api_key

    pconf = self.repl.cfg.providers.get(provider, ProviderConfig())
    return resolve_api_key(provider, pconf.api_key_env)
```
and use it in BOTH `_run_or_chain` and the new code. Behavior of `_run_or_chain` must be otherwise
identical (its existing `/model` picker tests must keep passing untouched).

**3. Intercept in `_dispatch_line`.** Inside the existing `if match is not None:` block, after the
`entry.needs_choice and not arg` chain check, add:
```python
        if entry.name == "/model" and arg:
            self._dispatch_model(arg)
            return
```
This deliberately also covers picker-chained and `/config model`-chained dispatches
(`_on_model_picked`, `_on_test_done`) — they pass an already-valid prefixed ref, so the strict path
succeeds and the catalog is never consulted.

**4. `_is_bare_ref_candidate(arg, active)` — the failure-shape gate.**
```python
    def _is_bare_ref_candidate(self, arg: str, active: str) -> bool:
        """Is this failure PLAUSIBLY ModelRef.parse's first-colon split, and not something else?

        Only a plausible candidate may reach the catalog branch. A ref that names a real provider
        and merely failed to build (missing key, bad base_url, SDK error) must NOT trigger a
        catalog fetch of the *active* provider — that would put a real network call and a
        "fetching … catalog…" line in front of the correct strict error.
        """
        from agent86.types import ModelRef

        try:
            parsed = ModelRef.parse(arg)
        except ValueError:
            return True  # no colon at all (e.g. "gpt-4o") — a bare id is exactly this shape
        if parsed.provider == active:
            return False  # explicitly targets the active provider; the failure is build/auth
        return (
            parsed.provider not in self.repl.cfg.providers
            and parsed.provider not in _BUILTIN_PROVIDERS
        )
```

**5. `_dispatch_model(arg)`.** Docstring: "Run `/model <arg>`; if the strict path fails, retry as
`<active-provider>:<arg>` ONLY when the failure looks like a first-colon split AND the active
provider's catalog vouches for `arg` verbatim (locked user decision). TUI-only — `ui/repl.py` and
`run --json` keep strict parsing."
```python
    def _dispatch_model(self, arg: str) -> None:
        log = self.query_one("#transcript", RichLog)
        before = self.repl.harness.provider
        result = handle_command(self.repl, f"/model {arg}")
        # set_model() replaces harness.provider on success and leaves it untouched on failure
        # (loop.py:130-143), so identity is an exact success signal — no dispatch duplication.
        if self.repl.harness.provider is not before:
            if result.render is not None:
                log.write(result.render)
            self.query_one("#status", StatusFooter).status = self.repl.status
            return
        provider = before.name
        if not self._is_bare_ref_candidate(arg, provider):
            if result.render is not None:
                log.write(result.render)          # strict error, immediately, no fetch
            return
        entries = self._catalog_cache.get(provider)
        if entries is not None:
            self._finish_model_fallback(arg, result.render, provider, entries)
            return
        # Cold cache: never block the UI. Queue this dispatch WITH the provider that was active
        # for it, then ensure exactly one fetch is outstanding for that provider.
        self._pending_model.append((arg, result.render, provider))
        self._ensure_catalog_fetch(provider)

    def _ensure_catalog_fetch(self, provider: str) -> None:
        """Start a model_fallback catalog fetch for `provider` unless one is already outstanding.

        Gated on _model_fetch_inflight, NOT on queue length: a queue that is non-empty because of
        ANOTHER provider's pending entry must still start this provider's own fetch, or that entry
        would silently piggyback on an unrelated arrival and never be answered.
        """
        if provider in self._model_fetch_inflight:
            return
        self._model_fetch_inflight.add(provider)
        self._request_catalog(provider, self._provider_key(provider), "model_fallback")
```

**6. `_finish_model_fallback(arg, strict_error, provider, entries)`.**
```python
        log = self.query_one("#transcript", RichLog)
        if not catalog_has_ref(arg, entries):
            # Catalog miss (typo, or a ref belonging to another provider): the strict error is
            # the RIGHT answer — surfacing it unchanged is the point of the locked decision.
            if strict_error is not None:
                log.write(strict_error)
            return
        # Reuse 260813-adr's exact-prefix double-prefix guard so the typed and picker paths of
        # /model can never drift.
        full = prefix_catalog_refs(provider, [(arg, arg)])[0][0]
        if full == arg:                       # defensive: already prefixed, retry would re-fail
            if strict_error is not None:
                log.write(strict_error)
            return
        log.write(f"[dim]resolved to {full}[/dim]")
        retry = handle_command(self.repl, f"/model {full}")
        if retry.render is not None:
            log.write(retry.render)
        self.query_one("#status", StatusFooter).status = self.repl.status
```
Call `handle_command` directly here (not `_dispatch_model`) — that is what makes recursion
impossible and lets a genuine retry failure surface once, plainly. Note every branch writes exactly
one outcome (invariant 1).

**7. `on_catalog_ready` routing.** Add the new branch AFTER the existing `model_picker` branch and
**BEFORE** the `push_screen(CatalogPickerModal(...))` fallthrough (that fallthrough currently
catches every non-`model_picker` purpose and would otherwise pop a picker modal at us):
```python
        if message.purpose == "model_fallback":
            self._model_fetch_inflight.discard(message.provider)
            # Resolve ONLY the entries dispatched under this provider (invariant 3); entries queued
            # under a different provider — an intervening successful /model switch can change the
            # active provider mid-flight — are re-queued untouched and answered by their own
            # arrival. A failed/empty fetch leaves entries == [] -> catalog_has_ref False -> the
            # strict error is written. Never a silent retry, never a silent drop.
            pending, self._pending_model = self._pending_model, []
            stranded: list[tuple[str, Any, str]] = []
            for arg, strict_error, provider in pending:
                if provider == message.provider:
                    self._finish_model_fallback(arg, strict_error, provider, message.entries)
                else:
                    stranded.append((arg, strict_error, provider))
            self._pending_model.extend(stranded)
            # Liveness safety net (invariant 1): normally each stranded provider's fetch is still
            # in flight from its own dispatch, so this is a no-op. If one somehow is not, restart
            # it rather than leaving an entry with no outcome forever.
            for _arg, _err, provider in stranded:
                self._ensure_catalog_fetch(provider)
            return
```
Note `self._pending_model` is re-read (not the stale local) when extending, because
`_finish_model_fallback` can dispatch a successful retry — which cannot itself queue, but keep the
ordering as written so the code stays obviously correct.

**8. Docstring only** in `src/agent86/tui/messages.py`: extend `CatalogReady`'s `purpose` sentence to
list the third value, e.g. `"model_fallback" (resolving a typed bare /model ref)`. No signature or
behavior change.

Keep lines ≤ the project's ruff line length; do not introduce new ruff errors (the pre-existing E501
at `app.py:560`/`:586` and the `test_app.py` I001/E501 are out of scope — leave them alone).
  </action>
  <verify>
    <automated>C:\Projects\agent86CLI\.venv\Scripts\python.exe -m pytest tests/tui/ -q</automated>
    <automated>C:\Projects\agent86CLI\.venv\Scripts\python.exe -m ruff check src/agent86/tui/app.py src/agent86/tui/messages.py</automated>
    <automated>C:\Projects\agent86CLI\.venv\Scripts\python.exe -m pytest tests/tui/test_lazy_import.py -q</automated>
  </verify>
  <done>All existing `tests/tui/` tests still pass (135 baseline, no new failures); `git diff --stat`
  shows only `app.py` and `messages.py` changed by this task; `git diff` on
  `src/agent86/ui/repl.py`, `src/agent86/tui/commands.py`, `src/agent86/types.py`, and
  `src/agent86/cognitive/catalog.py` is EMPTY; ruff reports no new errors on the touched files.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Regression tests (Pilot + strict-parsing pin) with RED proof</name>
  <files>tests/tui/test_app.py, tests/tui/test_commands.py</files>
  <behavior>
    In `tests/tui/test_app.py` (Pilot, following `_make_repl` / `_wait_until` and the
    `repl.harness.provider.name = "ollama"` active-provider trick):
    1. Warm cache, catalog HIT: seed `app._catalog_cache["ollama"] = [("nemotron-3.5-lightning:latest",
       "nemotron-3.5-lightning:latest")]`, dispatch `/model nemotron-3.5-lightning:latest` →
       `repl.harness.provider.name == "ollama"`, `provider.model == "nemotron-3.5-lightning:latest"`,
       transcript contains `resolved to ollama:nemotron-3.5-lightning:latest`.
    2. Warm cache, TYPO miss: same seeded catalog, dispatch
       `/model nemotron-3.5-lightnin:latest` → transcript contains the unchanged strict
       `Unknown provider 'nemotron-3.5-lightnin'` text, contains NO `resolved to` line, and the
       active provider is unchanged.
    3. Warm cache, colon-free miss: dispatch `/model gpt-4o` while ollama is active → transcript
       contains the unchanged `must be 'provider:model'` error, no `resolved to`, provider unchanged.
    4. Already-valid ref: dispatch `/model ollama:llama3.1` with the catalog cache EMPTY (`{}`) →
       the switch succeeds, no `resolved to` line, and NO catalog fetch was triggered (monkeypatch
       `agent86.cognitive.catalog.fetch_catalog` to raise `AssertionError` if called).
    5. **Known-provider failure must not fetch (checker warning 1):** monkeypatch
       `agent86.cognitive.base.provider_for_model` to raise
       `ProviderError("No Anthropic API key found ...")` (`Harness.set_model` imports it
       function-locally, so the module attribute is the live seam), and monkeypatch `fetch_catalog`
       to raise `AssertionError` if called. With ollama active and the cache EMPTY, dispatch
       `/model anthropic:claude-opus-4-8` → the strict error appears, no `resolved to`, transcript
       contains NO `fetching` line, `app._pending_model == []`, and `fetch_catalog` was never called.
    6. Cold cache: leave `_catalog_cache` empty, monkeypatch
       `agent86.cognitive.catalog.fetch_catalog` to return
       `[("nemotron-3.5-lightning:latest", "…")]`, dispatch the bare ref, then
       `await _wait_until(lambda: repl.harness.provider.model == "nemotron-3.5-lightning:latest")`
       → resolution completes after `CatalogReady`, `resolved to` echoed, and
       `app._pending_model == []` / `app._model_fetch_inflight == set()` afterwards.
    7. Cold cache, fetch FAILS: monkeypatch `fetch_catalog` to raise `CatalogUnavailable` →
       the strict error is written, no `resolved to`, provider unchanged, `_pending_model` drained
       and `_model_fetch_inflight` empty.
    8. **Overlapping dispatches, same provider (checker warning 2):** cold cache; monkeypatch
       `fetch_catalog` to block on a `threading.Event` (and count calls) and return
       `[("nemotron-3.5-lightning:latest", "…")]`. Dispatch `/model nemotron-3.5-lightning:latest`
       and then, before the fetch resolves, `/model nemotron-3.5-lightnin:latest` (the typo) →
       assert `len(app._pending_model) == 2` while in flight; after release, BOTH produce an
       outcome — the transcript contains `resolved to ollama:nemotron-3.5-lightning:latest` AND the
       typo's `Unknown provider 'nemotron-3.5-lightnin'` error — `fetch_catalog` was called exactly
       ONCE (same provider), and `app._pending_model == []`.
    9. **Cross-provider stranding (checker warning 3):** the exact sequence from `<decisions>`.
       Cold cache; a `fetch_catalog` fake that records `provider` per call and blocks provider A
       (`ollama`) on an event while answering provider B (`anthropic`) immediately (or blocks both
       and releases in a controlled order). With ollama active: dispatch
       `/model nemotron-3.5-lightning:latest` (queued under ollama), then
       `/model anthropic:claude-opus-4-8` which SUCCEEDS strictly (monkeypatch whatever is needed so
       the anthropic provider builds — e.g. a fake `provider_for_model` returning a stub whose
       `.name == "anthropic"` — active provider is now anthropic), then `/model gpt-4o` (queued
       under anthropic). Assert: `fetch_catalog` was called for BOTH `ollama` and `anthropic`
       (two calls, one per provider — proving `gpt-4o` did not piggyback); when ollama's
       `CatalogReady` arrives, the `gpt-4o` entry is still pending (not resolved against ollama's
       catalog) and the transcript contains NO `resolved to ollama:gpt-4o`; after anthropic's
       arrival, `gpt-4o` produces exactly one outcome validated against ANTHROPIC's catalog; both
       dispatches end with exactly one outcome each and `app._pending_model == []`.
    10. Cold cache, colon-free miss: dispatch `/model gpt-4o` while ollama is active with an empty
        cache and a `fetch_catalog` returning an ollama catalog WITHOUT `gpt-4o` → strict
        `must be 'provider:model'` error exactly once, no `resolved to`, queue drained.

    In `tests/tui/test_commands.py` (no app, no catalog — the plain-loop/scripting contract):
    11. `handle_command(repl, "/model nemotron-3.5-lightning:latest")` returns
        `action == "handled"` with `render` containing `Unknown provider 'nemotron-3.5-lightning'`,
        and `harness.provider` is unchanged — proving the adapter (shared with `--plain` semantics)
        has NO fallback and `ModelRef.parse` is untouched; plus `handle_command(repl, "/model gpt-4o")`
        returns the unchanged `must be 'provider:model'` error.
  </behavior>
  <action>
Write the eleven cases above. Use `app._dispatch_line("/model <ref>")` (or type into `#prompt` and
press enter, matching whichever style the neighbouring test uses) to drive dispatch, then
`await pilot.pause()`. Read the transcript with the file's existing idiom:
`"\n".join(str(line) for line in transcript.lines)`.

Assert the strict errors by their real substrings so a future reword of `_build_provider`'s message
would be caught rather than silently swallowed. Do NOT touch `tests/tui/test_pickers.py` (Task 1
owns it).

Never hit the network: cold-cache tests monkeypatch `agent86.cognitive.catalog.fetch_catalog`, as
`test_model_picker_fetches_then_opens` already does. `OllamaProvider` construction is local and
offline (`test_commands.py::test_model_command_switches_active_model` already relies on this), so a
successful ollama switch needs no server. For cases 8 and 9, keep the blocking `fetch_catalog`
release deterministic (set the event from the test, then `await _wait_until(...)` on an observable
condition) — no bare `asyncio.sleep` polling for widget state, per the 04-08 lesson in STATE.md. Give
each blocking fake a hard timeout on its wait so a bug cannot hang the suite.

**RED proof (project convention, per 260813-adr).** Before finalizing, `git stash` the Task 2 source
changes (or check out `app.py`/`messages.py` at the pre-Task-2 commit), rerun
`tests/tui/test_app.py`, and record in the SUMMARY which cases FAILED pre-fix — cases 1, 6, 7, 8 and
9 (the new behavior) must fail; cases 2, 3, 4, 5, 10 and 11 are pins on already-correct behavior and
may pass both before and after. Restore the source and confirm green.
  </action>
  <verify>
    <automated>C:\Projects\agent86CLI\.venv\Scripts\python.exe -m pytest tests/tui/test_app.py tests/tui/test_commands.py -q</automated>
    <automated>C:\Projects\agent86CLI\.venv\Scripts\python.exe -m pytest tests/tui/ -q</automated>
    <automated>C:\Projects\agent86CLI\.venv\Scripts\python.exe -m pytest -q</automated>
  </verify>
  <done>All eleven cases pass; RED evidence for cases 1/6/7/8/9 recorded in the SUMMARY; full suite is
  at the documented baseline plus the new tests — `436 passed, 6 skipped, 1 failed` where the ONE
  failure is the pre-existing `tests/unit/test_memory.py::test_build_embedder_falls_back_without_torch`
  (not fixed, not a regression).</done>
</task>

</tasks>

<verification>
1. `C:\Projects\agent86CLI\.venv\Scripts\python.exe -m pytest -q` — baseline + new tests, with only
   the known pre-existing `test_build_embedder_falls_back_without_torch` failure.
2. `git diff --stat` lists exactly: `src/agent86/tui/screens/model_picker.py`,
   `src/agent86/tui/app.py`, `src/agent86/tui/messages.py`, `tests/tui/test_pickers.py`,
   `tests/tui/test_app.py`, `tests/tui/test_commands.py`.
3. `git diff src/agent86/ui/repl.py src/agent86/types.py src/agent86/cognitive/catalog.py src/agent86/tui/commands.py`
   is EMPTY — the plain loop, `ModelRef.parse`, the bare-id catalog contract, and the strict command
   adapter are all untouched.
4. `C:\Projects\agent86CLI\.venv\Scripts\python.exe -m ruff check src tests` shows no NEW errors
   beyond the 4 documented pre-existing ones (E501 `app.py:560`/`:586`, I001+E501 `test_app.py`).
5. `pytest tests/tui/test_lazy_import.py -q` still passes — no new eager imports.
</verification>

<success_criteria>
- Typing `/model nemotron-3.5-lightning:latest` with ollama active and the model present in the
  ollama catalog switches the model and echoes `resolved to ollama:nemotron-3.5-lightning:latest`.
- A typo or a foreign-provider ref produces the existing strict error, byte-unchanged, with no
  fallback attempt and no `resolved to` line.
- An already-valid `provider:model` ref switches on the strict path without touching the catalog.
- A ref naming a known provider that fails to build (missing key, SDK error) produces its strict
  error immediately — no catalog fetch, no `fetching … catalog` line.
- A cold catalog resolves through `CatalogReady(purpose="model_fallback")` without blocking the UI;
  a failed or empty fetch falls through to the strict error.
- A pending entry is validated only against the catalog of the provider active at its own dispatch
  time, even when an intervening successful `/model` switch changed the active provider mid-flight.
- Overlapping `/model` dispatches each produce exactly one visible outcome, with exactly one fetch
  issued per provider.
- `handle_command` / `ui/repl.py` / `run --json` keep strict parsing — the fallback is TUI-only and
  documented as such.
- `ModelRef.parse`, `fetch_catalog`, and `tui/commands.py` are unmodified.
</success_criteria>

<output>
After completion, create
`.planning/quick/260813-atc-catalog-validated-provider-fallback-for-/260813-atc-SUMMARY.md`
</output>
</content>
