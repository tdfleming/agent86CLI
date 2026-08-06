# Phase 4: MCP Config UI - Research

**Researched:** 2026-08-06
**Domain:** MCP client lifecycle (anyio/asyncio task-scope teardown), TOML write-back deletion, TUI modal composition
**Confidence:** HIGH (D-23 task-scope mechanics verified against official `modelcontextprotocol/python-sdk` issue tracker; everything else grounded directly in this repo's source)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Add / edit input flow**
- D-01: Two peer entry paths — "Add from JSON" and "Add manually". Neither is a fallback.
- D-02: JSON path accepts both the bare server object and the wrapped `{"mcpServers": {"name": {...}}}` form.
- D-03: Manual path captures command+args as one shell-ish line, split with `shlex`.
- D-04: Server name is typed, required; a name collision blocks (no silent overwrite).
- D-05: Validation errors surface inline in the form via the `MCPServerConfig` validator's own message; Continue disabled until it parses. Do not re-derive per-field rules.
- D-06: `transport` is inferred via the existing rule (`command`→stdio, `url`→http); offer an http/sse toggle only once `url` is present.
- D-07: Editing reuses the same form, pre-filled; saving writes a diff over that server's keys.
- D-08: The server list shows static config facts only (name, transport, endpoint, enabled/disabled). Opening the manager must be instant, never spawn a subprocess or open a transport.

**Enable / disable and removal**
- D-09: Disabled server = `enabled: bool = True` on `MCPServerConfig` (net-new field); `build_mcp` skips falsy ones. Not a `[mcp] disabled=[...]` list, not a commented-out table.
- D-10: `config_writer` gains delete via a module-level `DELETE` sentinel used in the same `changes` list — `plan_edit(scope, [(["mcp","servers","foo"], DELETE)])`. One code path, one diff.
- D-11: Removal confirmed by the existing `SaveDiffModal` diff preview, not an extra dialog.
- D-12: Disabling goes through the same scope → diff → confirm flow as every other write. No silent fast-path toggle.

**Live apply**
- D-13: After a save, only the affected server is reconnected and its tools mounted — `MCPManager` gains a per-server add path. Not a full manager restart, not next-launch-only. Reuses the connection the pre-save test just proved.
- D-14: Removing or disabling a mounted server unmounts its tools and closes its session immediately (symmetric with add). Requires a tool-removal method on `ToolRegistry` (none exists today).
- D-15: A mid-session mount change is picked up by the next turn with no notice injected into the conversation.
- D-16: When config write succeeds but live mount fails, report both — save succeeded, mount did not, with error + "available next launch" hint. Do not roll back a confirmed config write.

**Connection test, tool listing & auth**
- D-17: Auth secrets are referenced from config, never stored in it — `Authorization = "Bearer ${GITHUB_TOKEN}"` (headers) or `TOKEN = "${GITHUB_TOKEN}"` (stdio env); resolved at connect time, env var first then OS keyring (same precedence as `resolve_api_key`). Plaintext tokens in `config.toml` are rejected, not merely discouraged (SEC-01).
- D-18: An unresolved `${VAR}` at test time chains into the existing masked `KeyEntryModal` — the same no-key-→-enter-key path Phase 3 built. No second masked field.
- D-19: Test result shows a tool count plus a scrollable list of tool names (with descriptions).
- D-20: Test uses the same worker-thread + hard-timeout pattern as `ConnectionTestModal`, timeout raised to ~30s (matches `MCPManager.start()`'s existing 30s budget for first-run `npx` downloads).

**Carried forward from Phase 3 (not re-decided)**
- "Save anyway" override on test failure (D-13 Phase 3).
- Scope chosen at save time, user pre-selected, project one arrow key away.
- TOML diff shown before every commit, with target path.
- No secret ever rendered on screen or written to config.
- A stored secret can be set and explicitly cleared, never revealed.

### Claude's Discretion
- D-21: Command surface — `/config mcp` is the expected shape (mirrors `/config model`), but Claude may choose otherwise if the registry makes a cleaner shape. Must be a `COMMANDS` entry.
- D-22: Exact modal composition, widget ids, CSS, screen count, form-screen split — consistent with `ModalScreen[T]` conventions in `tui/screens/*.py`.
- D-23: Mechanics of per-server teardown on `MCPManager`'s background event loop (the current single shared `AsyncExitStack` cannot release one server).
- D-24: How duplicate MCP tool names across servers are handled on remount (`default_registry` currently swallows `ValueError`; whether the new mount path surfaces the collision is Claude's call).
- D-25: Where `${VAR}` expansion lives (resolver beside `secrets.py`, or inside `_open_transport`) and whether it applies to `command`/`args`/`url` as well as `headers`/`env`.
- D-26: Whether `[mcp] enabled` master switch is exposed in the manager, and whether the read-only Typer commands gain an `enabled` column.
- D-27: Whether project-scope shadowing a user-scope server of the same name needs UI treatment beyond what `_deep_merge` already does.

### Deferred Ideas (OUT OF SCOPE)
- Editing MCP servers from the non-interactive `agent86 mcp` CLI (`mcp add`/`mcp remove`) — Typer commands stay read-only this phase.
- Per-server tool allow/deny lists.
- OAuth / dynamic client registration for remote MCP servers — static header auth only this phase.
- Live status polling / health checks in the server list (D-08 rejected this).
- Remembering a session's last test result per row.
- Rolling back a config write when the live mount fails (explicitly rejected, D-16).
- Plaintext tokens in config with a warning (explicitly rejected, D-17 — contradicts SEC-01).
- Packaging / lazy-import hardening as a verified contract — Phase 5 (TUI-06).
- Theming for the new modals — v2 (POL-01).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MCP-01 | List, add, remove, and enable/disable MCP servers from within the app, with a connection test that validates the server and enumerates its tools before saving | Standard Stack, Architecture Patterns (per-server teardown, `${VAR}` resolver, `DELETE` sentinel), Code Examples, Common Pitfalls |
| SEC-01 (constraint on D-17) | Config never contains a plaintext secret | Common Pitfalls #3 (`_FORBIDDEN_LEAF_KEYS` gap), Code Examples (guard extension) |
</phase_requirements>

## Summary

This phase's engineering risk is concentrated in one place: `MCPManager._connect()` currently
opens every configured server's transport and `ClientSession` into a single shared
`AsyncExitStack`, all inside one coroutine run via `run_coroutine_threadsafe` on the manager's
background event loop. That coroutine's frame is the "task" anyio's cancel-scope bookkeeping
cares about. `AsyncExitStack.aclose()` for one server can only be safely awaited from *the exact
task that entered its context managers* — anyio raises `RuntimeError: Attempted to exit cancel
scope in a different task than it was entered in` otherwise. This is confirmed directly against
the `modelcontextprotocol/python-sdk` issue tracker (issues #79, #922, #252, #521, #577, #922),
which is unanimous: never call `run_coroutine_threadsafe` (or `asyncio.create_task`) for open and
a *different* `run_coroutine_threadsafe`/task for close on the same `AsyncExitStack`. The fix
pattern used across the ecosystem (LangChain's MCP adapters, `google/adk-python`,
`microsoft/agent-framework` bug reports converge on the same shape) is a **dedicated,
long-lived asyncio Task per server** that owns its `AsyncExitStack` for its entire lifetime: it
opens the transport + session, signals readiness back to the launcher, then blocks on an
`asyncio.Event` until told to shut down — at which point its own `async with` block unwinds in
the same task that entered it. This is the "task-per-server" option `MCPManager`'s D-23 discretion
names explicitly, and it is the one to implement.

The remaining decisions are all mechanical extensions of patterns Phase 3 already established and
proven in this codebase: `config_writer.plan_edit`'s `changes` list gets a `DELETE` sentinel
value (D-10) instead of a parallel deletion API; `ConnectionTestModal`'s worker-thread +
hard-timeout shape is reused verbatim for the MCP test with the timeout raised to 30s (D-20);
`KeyEntryModal` is reused verbatim for `${VAR}` resolution (D-18); `ProviderManagerModal` /
`provider_rows(cfg)` is the direct skeleton for the server list. The one **real security gap**
this phase must close (SEC-01/D-17) is that `_FORBIDDEN_LEAF_KEYS` in `config_writer.py` does not
include `authorization`, so a bearer token under `headers.Authorization` would pass the existing
guard today — the fix must also be careful not to block the *legitimate* `${VAR}`-reference case
that D-17 requires (`Authorization = "Bearer ${GITHUB_TOKEN}"` must be allowed to save; a literal
`Authorization = "Bearer sk-live-..."` must not).

**Primary recommendation:** Restructure `MCPManager` around one persistent asyncio Task per
server (each owning its own `AsyncExitStack`, parked on an `asyncio.Event` until told to close),
add a `DELETE` sentinel to `config_writer.plan_edit`, add `ToolRegistry.unregister(name)`, extend
`_FORBIDDEN_LEAF_KEYS` with a `${VAR}`-reference exception, and reuse `resolve_api_key(var, var)` /
`store_api_key(var, ...)` directly (keyed by variable name, not provider name) as the `${VAR}`
resolver — no new keyring plumbing needed.

## Standard Stack

### Core (already in the codebase — no new dependencies)

| Library | Version (installed) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mcp` | 1.28.1 (floor `mcp>=1.0` in `pyproject.toml`) | MCP client SDK (`ClientSession`, `stdio_client`, `sse_client`, `streamable_http_client`) | Already the project's only MCP client; this phase extends its usage, does not replace it |
| `anyio` | pulled in transitively by `mcp` | Structured-concurrency primitives (`AsyncExitStack`, task/cancel-scope semantics) underlying every MCP transport context manager | Not a direct dependency to add — understanding its task-affinity rule is the crux of D-23 |
| `textual` | already a core-but-lazy dep (Phase 1-3) | `ModalScreen[T]`, `@work(thread=True)`, `OptionList`, `RadioSet` | Existing TUI stack; MCP manager modals are new files in `tui/screens/`, same conventions |
| `tomlkit` | already a core-but-lazy dep (Phase 3) | Comment-preserving TOML round-trip via `config_writer.plan_edit`/`apply_edit` | `DELETE` sentinel is an addition to the existing write path, not a new writer |
| `keyring` | already a core-but-lazy dep (Phase 3) | `${VAR}` resolution's keyring fallback, via the existing `secrets.py` functions | Reused as-is; no new keyring surface needed (see Pattern 3) |

**No new packages required for this phase.** `pyproject.toml`'s `mcp` extra (`mcp = ["mcp>=1.0"]`)
is unchanged; `MCPManager.start()`'s existing `except ImportError` degrade-with-a-note path must
be preserved for every new method added (`start_server`, `stop_server`), not just the original
bulk `start()`.

**Version verification:** `pip show mcp` in this environment reports `1.28.1`, well above the
`pyproject.toml` floor of `mcp>=1.0`. `pip show anyio` was not separately checked — it is
resolved transitively by `mcp`; no direct pin exists or is needed since this phase does not import
`anyio` directly (all task/event primitives used are the stdlib `asyncio` equivalents, which is
what the current `mcp_client.py` already uses — `asyncio.Event`, not `anyio.Event`, is correct
here, since the manager's own loop is a plain `asyncio` loop, not an `anyio` runner).

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Task-per-server (D-23 recommendation) | Full manager restart on every add/remove | Rejected by D-13/D-14 explicitly — tears down healthy sessions, violates "only the affected server" requirement |
| Task-per-server | Close-in-reverse-order-of-creation (LIFO) workaround seen in SDK issue #922 | Only works for a single shared stack closed all-at-once at shutdown; does not support closing one arbitrary server while N others stay open, which is exactly D-14's requirement |
| Reusing `resolve_api_key(var, var)` for `${VAR}` refs | A new parallel `mcp_secrets.py` module with its own env/keyring precedence | `resolve_api_key`'s signature `(provider_name, api_key_env)` already does exactly "env var named X, else keyring account X" when both args are the same string — no new precedence logic to write or test |

## Architecture Patterns

### Recommended Project Structure (additions only)
```
src/agent86/
├── tools/
│   └── mcp_client.py          # MCPManager restructured for per-server tasks (D-23); start_server/stop_server
├── tools/registry.py          # ToolRegistry.unregister() added (D-14)
├── config.py                  # MCPServerConfig.enabled: bool = True (D-09)
├── config_writer.py           # DELETE sentinel added to plan_edit (D-10); _FORBIDDEN_LEAF_KEYS extended (SEC-01/D-17)
├── secrets.py                 # find_var_refs()/expand_var_refs()/MissingSecretRef added (D-25) — reuses resolve_api_key/store_api_key
├── orchestration/loop.py      # Harness gains add_mcp_server()/remove_mcp_server() (D-13/D-14/D-15)
├── tui/
│   ├── commands.py            # /config mcp COMMANDS entry (D-21)
│   ├── app.py                 # chain wiring: manager -> add/edit form -> test -> diff -> apply -> live mount
│   └── screens/
│       ├── mcp_manager.py     # new: server list modal + add/edit form screen(s) (D-22)
│       └── mcp_test.py        # new: connection-test modal, mirrors connection_test.py but 30s + tool list (D-19/D-20)
└── cli.py                     # mcp_app list/tools stay read-only (unchanged); optional `enabled` column (D-26, discretion)
```

### Pattern 1: Task-per-server MCP lifecycle (D-23)

**What:** Replace the single shared `AsyncExitStack` opened by one `_connect()` coroutine with
one persistent `asyncio.Task` per server. Each task owns its own `AsyncExitStack` for its entire
life: open transport → open `ClientSession` → `initialize()` → `list_tools()` → signal ready →
`await` a per-server `asyncio.Event` → (when set) let its own `async with` unwind. Because the
task that enters the context managers is the same task that lets them exit, anyio's cancel-scope
affinity rule is satisfied for every server independently.

**When to use:** Any add (D-13), remove/disable (D-14), or bulk startup — bulk startup becomes
"launch N per-server tasks concurrently and wait for all readiness futures", not "one shared
open".

**Example (sketch — the concrete shape to implement, not existing code):**
```python
# Source: derived from confirmed root-cause analysis in
# github.com/modelcontextprotocol/python-sdk issues #79, #922, #252, #521
# (anyio requires cancel scopes entered/exited in the same task)

class MCPManager:
    def __init__(self, servers: dict[str, MCPServerConfig]):
        self.servers = servers
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, Any] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._close_events: dict[str, asyncio.Event] = {}
        self._server_tools: dict[str, list[str]] = {}   # for D-14 unmount bookkeeping
        self._tools: list[MCPTool] = []
        self.note: str | None = None

    def start_server(self, name: str, cfg: MCPServerConfig, timeout: float = 30.0) -> list["MCPTool"]:
        """Launch one server's owning task; block the caller until ready or failed/timed out."""
        fut = asyncio.run_coroutine_threadsafe(self._launch(name, cfg), self._loop)
        return fut.result(timeout=timeout)   # raises on failure/timeout — caller (test modal) surfaces it

    async def _launch(self, name: str, cfg: MCPServerConfig) -> list["MCPTool"]:
        close_event = asyncio.Event()
        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(self._serve(name, cfg, ready, close_event))
        self._tasks[name] = task
        self._close_events[name] = close_event
        return await ready   # resolves (or raises) once _serve has opened+initialized+listed tools

    async def _serve(self, name, cfg, ready: asyncio.Future, close_event: asyncio.Event) -> None:
        try:
            async with AsyncExitStack() as stack:
                streams = await stack.enter_async_context(_open_transport(cfg))
                read, write = streams[0], streams[1]
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listed = await session.list_tools()
                tools = [MCPTool(self, name, t.name, t.description or "", t.inputSchema or {})
                         for t in listed.tools]
                self._sessions[name] = session
                self._server_tools[name] = [t.name for t in tools]
                if not ready.done():
                    ready.set_result(tools)
                await close_event.wait()          # <-- parked here until stop_server() fires
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
        finally:
            self._sessions.pop(name, None)

    def stop_server(self, name: str, timeout: float = 10.0) -> None:
        """Signal the owning task to unwind its OWN stack, then wait for it to finish."""
        close_event = self._close_events.pop(name, None)
        task = self._tasks.pop(name, None)
        if close_event is None or task is None:
            return
        async def _stop() -> None:
            close_event.set()
            await task    # awaiting a task from a different task is fine — no scope exited here
        asyncio.run_coroutine_threadsafe(_stop(), self._loop).result(timeout=timeout)
        self._server_tools.pop(name, None)
```

`start()` (bulk startup) becomes a thin wrapper: for each configured (and `enabled`) server, call
`start_server` — either sequentially or via `asyncio.gather` of `_launch` coroutines scheduled in
one `run_coroutine_threadsafe` call, catching per-server exceptions individually so one bad server
still degrades to a `note` rather than blocking the others (preserves the existing `except
Exception as exc: self.note = ...` per-server catch in the current `_connect`). `close()` (full
shutdown) becomes: for every remaining `name` in `self._tasks`, call `stop_server(name)` (or the
`_stop` coroutine batched via `asyncio.gather`), then stop the loop exactly as today.

**Test-then-adopt flow (D-13's "reuses the connection the pre-save test just proved"):** the
connection test (D-19/D-20) should call `MCPManager.start_server(name, cfg)` on the *live*
manager instance directly (not a throwaway manager) — if the test passes, the server is *already*
mounted (its task is already parked on `close_event.wait()`); there is nothing further to
"adopt". If the user cancels at the `SaveDiffModal` step, the caller must call
`manager.stop_server(name)` to tear down the just-started task before returning — otherwise a
cancelled add leaves an orphaned, unconfigured server running for the rest of the session.

### Pattern 2: `DELETE` sentinel in `config_writer.plan_edit` (D-10)

**What:** A module-level sentinel object; `plan_edit`'s `changes` list accepts `(key_path, DELETE)`
tuples alongside ordinary `(key_path, value)` tuples in the same call, producing one diff and one
write for a combined edit (e.g. delete server "foo" while setting `enabled = false` on server
"bar" in the same save).

**When to use:** Any removal path (D-10/D-11) and — per D-09 — is *not* used for disabling
(disabling sets `enabled = false`, an ordinary value write, not a delete).

**Example:**
```python
# Source: this repo, agent86/config_writer.py (extension)
DELETE = object()   # module-level sentinel; identity-compared, never equality-compared

def plan_edit(scope: str, changes: list[tuple[list[str], Any]]) -> ConfigEdit:
    ...
    for key_path, value in changes:
        if not key_path:
            raise ValueError("empty key path in changes")
        if value is DELETE:
            _apply_delete(doc, key_path)
            continue
        leaf = key_path[-1].lower()
        if leaf in _FORBIDDEN_LEAF_KEYS and not _is_var_ref(value):
            raise ValueError(...)
        # existing set logic unchanged
        ...

def _apply_delete(doc, key_path: list[str]) -> None:
    """No-op if the path doesn't exist — deleting twice, or a server already removed
    by hand, must not crash the modal."""
    node: Any = doc
    for part in key_path[:-1]:
        if not hasattr(node, "get"):
            return
        nxt = node.get(part)
        if nxt is None:
            return
        node = nxt
    if hasattr(node, "__contains__") and key_path[-1] in node:
        del node[key_path[-1]]
```

**Known edge case to flag for the planner, not silently fix:** deleting the only remaining server
under `[mcp.servers]` leaves an empty `[mcp.servers]` table header behind (tomlkit does not
auto-prune empty parent tables). This is cosmetically visible in the diff and in the resulting
file but is not a correctness bug — `_normalize()`/`load_config()` already treats an empty
`mcp_servers` dict as "no servers configured" regardless. Decide in planning whether this is worth
a follow-up prune-if-empty step or left as acceptable cosmetic debt.

### Pattern 3: `${VAR}` resolution reusing `resolve_api_key` (D-17/D-25)

**What:** A small pure-function resolver, placed in `secrets.py` (recommended placement — it is
directly testable without a running app or transport, and keeps every secret-resolution
precedence rule in one file), applied at the `_open_transport`/`_serve` boundary in
`mcp_client.py` — i.e. resolved fresh at connect time, never cached into `MCPServerConfig` or
written back to disk.

**Where it applies:** `args` (each element), `env` values, `url`, and `headers` values. **Not**
`command`, which stays a literal executable name — allowing `${VAR}` expansion in `command` would
let an env var or keyring entry redirect what subprocess gets spawned, a foot-gun with no
legitimate use case named in CONTEXT.md's scope.

**Precedence reuse:** `resolve_api_key(provider_name, api_key_env)` already implements exactly
"env var named X, else OS keyring account X, else None" when `provider_name == api_key_env == X`.
Passing the `${VAR}` name as *both* arguments reuses this without adding a second precedence
implementation to test.

**Example:**
```python
# Source: this repo, agent86/secrets.py (extension) — reuses existing resolve_api_key/store_api_key
import re

_VAR_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

class MissingSecretRef(RuntimeError):
    """A ${VAR} reference in an MCP server config has no env var or keyring entry (D-18)."""
    def __init__(self, var_name: str):
        self.var_name = var_name
        super().__init__(f"'${{{var_name}}}' is not set (checked env, then OS keyring)")

def find_var_refs(*texts: str) -> set[str]:
    """Every distinct ${VAR} name referenced across the given strings."""
    names: set[str] = set()
    for text in texts:
        names.update(_VAR_REF_RE.findall(text or ""))
    return names

def expand_var_refs(text: str, overrides: dict[str, str] | None = None) -> str:
    """Substitute every ${VAR} in `text`. `overrides` (from KeyEntryModal, not yet persisted —
    D-18/D-14 pattern) wins over env/keyring, mirroring the connection-test-before-store flow."""
    overrides = overrides or {}
    def _sub(m: re.Match) -> str:
        name = m.group(1)
        if name in overrides:
            return overrides[name]
        val = resolve_api_key(name, name)   # env first, then keyring — same precedence, reused
        if val is None:
            raise MissingSecretRef(name)
        return val
    return _VAR_REF_RE.sub(_sub, text)
```

In `mcp_client.py`'s `_open_transport`/`_serve`, call `expand_var_refs` on each field before
constructing `StdioServerParameters`/passing `headers=`/`url=`; the connection-test flow (D-18)
pre-flights with `find_var_refs` across all four fields, and for each unresolved name pushes a
`KeyEntryModal(var_name, keyring_available())` — looping until all are resolved or the user
cancels — building an `overrides` dict that `expand_var_refs` consults first, and that only gets
written via `store_api_key(var_name, value)` *after* the test passes (mirrors D-14's
"key persisted only once the test proves it").

### Anti-Patterns to Avoid
- **Closing a shared `AsyncExitStack` from a `run_coroutine_threadsafe` call issued from a
  different logical task than the one that opened it** — this is the exact anyio violation
  documented in `python-sdk` issues #79/#922/#252/#521 and is what the current `close()`/`_connect`
  split already narrowly avoids only because it closes *everything at once, in the same original
  task* (never per-server). Any per-server close path must preserve same-task symmetry.
- **A parallel `plan_delete` function or `deletions=` kwarg on `plan_edit`** — explicitly rejected
  by D-10; splits one logical edit into two diffs/writes.
- **Leaf-key-name-only secret blocking that also blocks legitimate `${VAR}` values** — would make
  D-17's own example (`TOKEN = "${GITHUB_TOKEN}"`, leaf `token` is already in
  `_FORBIDDEN_LEAF_KEYS`) unsavable. The guard must distinguish "looks like a live secret" from
  "is a `${VAR}` reference", not just check the key name.
- **Rebuilding `Harness.registry`/`Harness.mcp` from scratch on every add/remove** — explicitly
  rejected by D-13 ("not a full manager restart, which would tear down healthy sessions").

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Env-var-then-keyring precedence for `${VAR}` refs | A new resolver with its own env/keyring fallback logic | `resolve_api_key(var_name, var_name)` from `secrets.py` | Identical precedence already implemented, tested, and lazily-imports keyring correctly |
| Persisting a resolved `${VAR}` value | New keyring-write helper | `store_api_key(var_name, value)` from `secrets.py` | Same service name (`"agent86"`), just a different account string; no new keyring surface |
| Masked secret entry for an unresolved `${VAR}` | A new masked-input modal | `KeyEntryModal` (reused verbatim per D-18) | Already echo-hardened (`event.stop()` first statement — closed a real transcript-leak bug in Phase 3, plan 03-10) |
| Worker-thread + hard-timeout connection probing | New threading boilerplate in the MCP test modal | The same `threading.Event` + daemon-thread + `app.call_from_thread` shape as `ConnectionTestModal` | Proven pattern; only the timeout constant (30s vs 15s) and the success payload (tool list vs none) differ |
| TOML diff + scope selection UI | A parallel diff modal for MCP | `SaveDiffModal` unchanged, once `plan_edit` can express `DELETE` | Works for MCP edits with zero modal-level changes — it already renders whatever `plan_edit` returns |

**Key insight:** every hard problem this phase touches (secret precedence, masked entry, diff
preview, worker-thread testing) was already solved correctly in Phase 3. The only genuinely new
engineering is the per-server async lifecycle (D-23) and the `DELETE` sentinel (D-10) — everything
else is composition of existing, tested primitives.

## Common Pitfalls

### Pitfall 1: Cancel-scope violation on per-server teardown (D-23)
**What goes wrong:** Calling `asyncio.run_coroutine_threadsafe(some_close_coro(), loop)` where
`some_close_coro` calls `.aclose()` on an `AsyncExitStack` that was populated by a *different*
`run_coroutine_threadsafe` call (i.e., a different task) raises `RuntimeError: Attempted to exit
cancel scope in a different task than it was entered in`, or a worse variant where anyio's
internal task-group bookkeeping silently gets corrupted (SDK issue #922: a second `ClientSession`
overwrites the first one's bound cancel scope).
**Why it happens:** `mcp`'s transport clients (`stdio_client`, `sse_client`,
`streamable_http_client`) and `ClientSession` are anyio-based async context managers that bind
internal task groups/cancel scopes to whatever asyncio task is executing `__aenter__`.
`AsyncExitStack.aclose()` must run its stored callbacks (which call `__aexit__`) from that exact
task.
**How to avoid:** One persistent task per server (Pattern 1) — that task both enters and, later,
lets its own `async with` exit. Never open in one `run_coroutine_threadsafe` call and close in
another for the same stack.
**Warning signs:** Any `RuntimeError` mentioning "cancel scope" or "different task" during
`stop_server`/`close`; intermittent hangs on shutdown; a second server's teardown mysteriously
affecting an unrelated server's session.

### Pitfall 2: `${VAR}` guard blocks its own intended use case (SEC-01/D-17)
**What goes wrong:** `_FORBIDDEN_LEAF_KEYS` already contains `token`, and D-17's own canonical
example is `TOKEN = "${GITHUB_TOKEN}"` in stdio `env`. A naive fix that just adds `authorization`
to the forbidden set (to close the real hole) without an exception for `${VAR}`-shaped values
would make the feature's headline example unsavable — `plan_edit` would raise `ValueError` on the
very config `TOKEN = "${GITHUB_TOKEN}"` the phase is supposed to produce.
**Why it happens:** The current guard is a blanket leaf-key-name check with no awareness of
value shape.
**How to avoid:** Guard on (leaf key looks like a secret name) AND (value is not itself a `${VAR}`
reference) — use the same `_VAR_REF_RE` regex as the resolver to decide "is a reference", not a
loose `"${" in value` substring check (which a hostile/careless literal like
`"abc${notreal}xyz"` could exploit to bypass the guard with a real embedded secret).
**Warning signs:** Existing test `test_no_plaintext_secret_in_output` in
`tests/unit/test_config_writer.py` still using literal (non-`${}`) values in its assertions — any
new test for the MCP path must add both a rejected-literal case and an accepted-`${VAR}` case.

### Pitfall 3: `Harness.config` goes stale after a live MCP edit (mirrors an existing gap)
**What goes wrong:** `Agent86App._on_save_confirmed` already reassigns `self.repl.cfg =
apply_edit(edit)` after a Phase-3 model-config save — but `self.repl.harness.config` (the object
`Harness.__init__` stored) is a *different* object and is never updated. If the new MCP
add/remove/disable flow follows the same pattern, `harness.config.mcp_servers` will silently
diverge from `repl.cfg.mcp_servers` for the rest of the session.
**Why it happens:** No existing seam refreshes `Harness.config` after a live config write; Phase 3
worked around this by mutating `Harness` state directly (`harness.set_model()`) rather than
relying on `harness.config` being current.
**How to avoid:** MCP add/remove must go through explicit `Harness` methods
(`harness.add_mcp_server(name, cfg)` / `harness.remove_mcp_server(name)`) that mutate
`harness.mcp`/`harness.registry` directly — the same "mutate the live object, don't rely on
`self.config` staying fresh" discipline `set_model()` already uses. Do not read `enabled`/server
membership back out of `harness.config.mcp_servers` after a live edit; track it in the mutated
objects (`MCPManager.servers`, `harness.registry`) instead.
**Warning signs:** A `/config` or `/tools` command issued later in the same session showing the
old server list even after a successful add/remove.

### Pitfall 4: Duplicate tool names silently dropped on remount (D-24)
**What goes wrong:** `default_registry`'s `except ValueError: pass` (registry.py line ~102-103)
means a newly-added server whose tool names collide with an already-mounted server's tools will
have those specific tools silently vanish — the user sees "connected, N tools" in the test result,
but fewer tools actually become callable, with no error surfaced anywhere.
**Why it happens:** The startup-time swallow was reasonable for "don't crash the whole harness
over one bad server at boot" but is the wrong default for an *explicit, single-server* add action
where the user is watching and can act on a collision.
**How to avoid:** In the new mount path (not `default_registry`, which stays for bulk startup),
surface collisions to the D-16 "report both" channel: attempt each tool registration, collect any
`ValueError`s, and report "server added, N of M tools mounted (collisions: ...)" rather than
silently dropping them. This is Claude's call per D-24, but silent dropping in an explicit,
watched action is inconsistent with D-16's "report both" precedent for a similar half-success case.
**Warning signs:** Tool count in the test result (D-19) not matching the tool count actually
callable after save.

### Pitfall 5: `enabled=false` server still gets attempted at bulk startup
**What goes wrong:** If the D-09 `enabled` field is added to `MCPServerConfig` but `MCPManager`'s
bulk-start path isn't updated to filter on it (only `build_mcp` is), a disabled server would still
get a task launched at every app startup, defeating the purpose of `enabled`.
**Why it happens:** `build_mcp(config)` today does `if not config.mcp.enabled or not
config.mcp_servers: return None` then passes *all* of `config.mcp_servers` to `MCPManager` — the
per-server `enabled` filter needs to happen either in `build_mcp` (filter the dict before
construction) or in `MCPManager.start()` itself. CONTEXT.md's D-09 says "`build_mcp` skips falsy
ones" — so the filter belongs in `build_mcp`, not deep inside `MCPManager`.
**How to avoid:** `build_mcp` filters `{name: cfg for name, cfg in config.mcp_servers.items() if
cfg.enabled}` before constructing `MCPManager`. `MCPManager.servers` should only ever contain
servers that are supposed to be running — bulk `start()` has no separate enabled-check to forget.
**Warning signs:** A server explicitly disabled via the manager still shows up in `/tools` or the
live registry after an app restart.

## Code Examples

### `ToolRegistry.unregister` (D-14)
```python
# Source: this repo, agent86/tools/registry.py (extension)
class ToolRegistry:
    ...
    def unregister(self, name: str) -> bool:
        """Remove one tool by name. Returns True if it was present."""
        return self._tools.pop(name, None) is not None
```
`MCPManager` should track, per server, which sanitized tool names it registered
(`self._server_tools[name]`, already sketched in Pattern 1) so `Harness.remove_mcp_server(name)`
can do `for tool_name in self.mcp._server_tools.get(name, []): self.registry.unregister(tool_name)`
before calling `self.mcp.stop_server(name)`.

### `Harness` live mount/unmount seam (D-13/D-14/D-15)
```python
# Source: this repo, agent86/orchestration/loop.py (extension — new methods on Harness)
def add_mcp_server(self, name: str, cfg: MCPServerConfig) -> list[MCPTool]:
    """Mount one already-tested, already-connected server's tools into the live registry.

    Called AFTER the connection test (D-19/D-20) has already started this server on
    self.mcp via MCPManager.start_server — this method only wires the resulting tools
    into self.registry (D-24 collision handling) and records the server in self.mcp.servers
    so a later /tools or manager-reopen reflects it. Never spawns a transport itself.
    """
    tools = self.mcp.tools_for(name)         # already-connected; see MCPManager bookkeeping
    mounted, collisions = [], []
    for tool in tools:
        try:
            self.registry.register(tool)
            mounted.append(tool.name)
        except ValueError:
            collisions.append(tool.name)
    self.mcp.servers[name] = cfg
    return mounted, collisions              # caller (app.py) renders the D-16 "report both" line

def remove_mcp_server(self, name: str) -> None:
    """Unmount a server's tools and close its session immediately (D-14)."""
    for tool_name in list(self.mcp._server_tools.get(name, [])):
        self.registry.unregister(tool_name)
    self.mcp.stop_server(name)
    self.mcp.servers.pop(name, None)
```
D-15 ("picked up by the next turn, no injected notice") requires no code beyond this: tool specs
are read from `self.registry.specs()` fresh inside `_build_request` on every model call
(`orchestration/loop.py` line ~177) — nothing caches the tool list per-session, so a mount change
between turns is automatically visible on the next `run_turn` call with zero additional wiring.

### `_FORBIDDEN_LEAF_KEYS` guard extended for `${VAR}` (SEC-01/D-17)
```python
# Source: this repo, agent86/config_writer.py (extension)
_FORBIDDEN_LEAF_KEYS = frozenset({
    "api_key", "apikey", "key", "token", "secret", "password",
    "authorization",   # NEW — closes the SEC-01 hole: headers.Authorization was unguarded
})

def _is_var_ref(value: Any) -> bool:
    """True if value is (or fully resolves via) a ${VAR}-style reference, never a literal secret."""
    from agent86.secrets import find_var_refs
    return isinstance(value, str) and bool(find_var_refs(value))

# in plan_edit's per-change loop:
leaf = key_path[-1].lower()
if leaf in _FORBIDDEN_LEAF_KEYS and not _is_var_ref(value):
    raise ValueError(
        f"refusing to write '{'.'.join(key_path)}' to config: secrets belong in the OS "
        "keyring or a ${VAR} reference, never a literal value"
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `mcp.client.streamablehttp_client` (all-in-one) | `mcp.client.streamable_http.streamable_http_client` (caller-provided `httpx.AsyncClient`) | Already adopted in this repo's `_streamable_http` (see docstring: "the older all-in-one ... is deprecated") | No action needed this phase — already correct |
| One shared `AsyncExitStack` for all MCP servers | Per-server owning task + per-server `AsyncExitStack` | This phase (D-23) | Enables independent add/remove without disturbing other servers — the entire point of MCP-01 success criterion 3 |

**Deprecated/outdated:** None newly identified. The codebase's existing choice of
`streamable_http_client` over the deprecated `streamablehttp_client` is already correct per the
module's own docstring and does not need revisiting.

## Open Questions

1. **Should `_apply_delete` raise or silently no-op when the target path doesn't exist?**
   - What we know: Pattern 2 sketches a silent no-op (matches "removal is idempotent" UX
     expectations — deleting an already-gone server shouldn't error).
   - What's unclear: Whether the planner wants this surfaced as "No changes." in `SaveDiffModal`
     (which already has that exact code path for a no-op edit) or as an explicit error.
   - Recommendation: silent no-op, relying on `ConfigEdit.is_noop` (already exists) to render
     "No changes." in `SaveDiffModal` — zero new UI states needed.

2. **Does the empty-`[mcp.servers]`-table-after-last-delete cosmetic (Pitfall/Pattern 2) need a
   prune step?**
   - What we know: `load_config`/`_normalize` treat an empty `mcp_servers` dict identically to a
     missing one — functionally harmless.
   - What's unclear: Whether a user hand-reading their `config.toml` would find a bare
     `[mcp.servers]` header with nothing under it confusing.
   - Recommendation: leave unpruned for this phase (matches the "don't over-build" MODEL-02
     precedent of not chasing every tomlkit cosmetic); revisit only if UAT flags it.

3. **Bulk `start()` concurrency: sequential per-server launch or `asyncio.gather`?**
   - What we know: The current `_connect()` opens servers sequentially in a `for` loop (one at a
     time) inside the single shared-stack coroutine; a slow/hanging stdio server (e.g. an `npx`
     download) currently delays every subsequent server's startup within the same 30s budget.
   - What's unclear: Whether concurrent launch (each server's `_launch` scheduled via `gather`)
     is worth the added complexity, given D-20 already raises the *per-connection-test* budget to
     30s specifically to tolerate a slow first-run install.
   - Recommendation: keep bulk `start()` sequential for this phase (matches existing behavior,
     lowest risk) — the D-23 restructure is about *independent per-server teardown*, not bulk
     startup latency, which is out of this phase's success criteria.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing suite: 341+ passed as of Phase 3 completion) |
| Config file | `pyproject.toml` (`[tool.pytest]`/dev deps) — no separate pytest.ini found |
| Quick run command | `pytest tests/unit/test_mcp.py tests/unit/test_config.py tests/unit/test_config_writer.py tests/unit/test_secrets.py tests/tui/test_mcp_manager.py -q` (new + touched files; adjust filenames to whatever the plan creates) |
| Full suite command | `pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|--------------------|-------------|
| MCP-01 (list) | Manager modal lists configured servers with transport/status, no subprocess spawned on open | unit/TUI | `pytest tests/tui/test_mcp_manager.py -k list -x` | ❌ Wave 0 |
| MCP-01 (add stdio) | Add-from-JSON and add-manually both validate, test (spawn+list tools), and write on save | integration | `pytest tests/integration/test_mcp_client.py -k per_server -x` and a new TUI Pilot test | ❌ Wave 0 (extends existing `test_mcp_client.py`) |
| MCP-01 (add sse/http) | Connection test enumerates tools before save, over a real transport | integration (live) | `pytest tests/integration/test_mcp_live.py -x` (extend `_CASES`/add a stdio case using a real subprocess, or add server-add-specific assertions) | ✅ exists, extend |
| MCP-01 (remove/disable) | Removal/disable updates config non-destructively (comments preserved) and unmounts live tools immediately | unit + integration | `pytest tests/unit/test_config_writer.py -k delete -x` and `pytest tests/unit/test_mcp.py -k unregister -x` | ❌ Wave 0 (DELETE sentinel, unregister are net-new) |
| SEC-01 (D-17 guard) | A literal secret under `headers.Authorization`/`env.TOKEN` is rejected; the equivalent `${VAR}` reference is accepted | unit | `pytest tests/unit/test_config_writer.py -k forbidden_var_ref -x` | ❌ Wave 0 |
| D-23 (task-scope safety) | Adding server B while server A is running, then stopping A, does not raise a cancel-scope RuntimeError and leaves B's session intact | integration (live) | `pytest tests/integration/test_mcp_client.py -k independent_teardown -x` using `tests/integration/live_mcp_server.py` (spin up two live server instances, or one server twice under different names) | ❌ Wave 0 |
| D-25 (`${VAR}` expansion) | `expand_var_refs` resolves env-first-then-keyring by variable name; raises `MissingSecretRef` when neither has it | unit | `pytest tests/unit/test_secrets.py -k var_ref -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the quick run command above, scoped to touched modules
- **Per wave merge:** `pytest -q` (full suite)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/tui/test_mcp_manager.py` — new Pilot test module for the list/add/edit/remove modal
      chain, xfail-scaffolded against the interfaces this phase's plan will define (mirrors
      `tests/tui/test_provider_manager.py`'s Wave-0 pattern from Phase 3).
- [ ] `tests/tui/test_mcp_test_modal.py` (or extend an existing screens test file) — worker-thread
      + 30s-timeout + tool-list-rendering coverage for the new connection-test modal, mirroring
      `tests/tui/test_connection_test.py`.
- [ ] Extend `tests/unit/test_mcp.py` — `ToolRegistry.unregister`, `MCPManager.start_server`/
      `stop_server` unit coverage against fakes (no real transport).
- [ ] Extend `tests/integration/test_mcp_client.py` — a real-but-fast case proving independent
      per-server teardown does not raise a cancel-scope error (this is the single highest-value
      new test in the phase — it is the direct regression guard for D-23).
- [ ] Extend `tests/unit/test_config_writer.py` — `DELETE` sentinel round-trip (diff shows a
      removed table, comments elsewhere preserved) and the `${VAR}`-exception case for
      `_FORBIDDEN_LEAF_KEYS`.
- [ ] Extend `tests/unit/test_secrets.py` — `find_var_refs`/`expand_var_refs`/`MissingSecretRef`
      unit coverage (pure functions, no transport or app needed).
- [ ] Extend `tests/unit/test_config.py` — `MCPServerConfig.enabled` default-True, `build_mcp`
      filtering disabled servers out before `MCPManager` construction.

## Sources

### Primary (HIGH confidence)
- This repository, read directly: `src/agent86/tools/mcp_client.py`, `src/agent86/config.py`,
  `src/agent86/config_writer.py`, `src/agent86/secrets.py`, `src/agent86/tools/registry.py`,
  `src/agent86/tools/base.py`, `src/agent86/orchestration/loop.py`,
  `src/agent86/tui/{app.py,commands.py}`, `src/agent86/tui/screens/{connection_test.py,
  key_entry.py,save_diff.py,provider_manager.py}`, `src/agent86/cli.py` (mcp_app),
  `tests/integration/{test_mcp_client.py,test_mcp_live.py,live_mcp_server.py}`,
  `tests/unit/test_config_writer.py`, `tests/tui/test_lazy_import.py`, `pyproject.toml`
- `pip show mcp` in this environment — confirms `mcp==1.28.1` installed, above the
  `pyproject.toml` `mcp>=1.0` floor
- github.com/modelcontextprotocol/python-sdk issues #79, #922 — fetched directly; official SDK
  repo, root-cause analysis of the exact cancel-scope error D-23 must avoid, and the recommended
  same-task-open-and-close pattern

### Secondary (MEDIUM confidence)
- WebSearch result list surfacing github.com/modelcontextprotocol/python-sdk issues #252, #521,
  #577 and third-party framework bug reports (`google/adk-python` #2196,
  `microsoft/agent-framework` #2846, `microsoft/semantic-kernel` #12627) — not individually
  fetched, but titles/context corroborate the same root cause across independent MCP client
  implementations, increasing confidence in the task-per-server fix pattern being the ecosystem
  consensus, not a one-off workaround

### Tertiary (LOW confidence)
- None relied upon for a load-bearing claim in this document.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; installed `mcp` version verified directly
- Architecture (D-23 task-per-server): HIGH — root cause and fix pattern confirmed against the
  official `modelcontextprotocol/python-sdk` issue tracker, not training-data recall; the concrete
  code sketch is original synthesis grounded in that confirmed constraint plus this repo's
  existing `MCPManager` shape
- Architecture (DELETE sentinel, `${VAR}` resolver, registry unregister): HIGH — directly derived
  from reading the actual source files these changes extend
- Pitfalls: HIGH for #1-3 and #5 (each traced to a specific line/behavior in this repo's source or
  the SDK issue tracker); MEDIUM for #4 (D-24 is explicitly Claude's discretion — the
  recommendation is a design judgment, not a verified fact)

**Research date:** 2026-08-06
**Valid until:** ~30 days (stable domain — the `mcp` SDK's async lifecycle semantics and this
repo's Phase 3 patterns are unlikely to shift meaningfully in that window); re-verify the
installed `mcp` version if planning is delayed past that window, since MCP SDK releases have been
frequent.
