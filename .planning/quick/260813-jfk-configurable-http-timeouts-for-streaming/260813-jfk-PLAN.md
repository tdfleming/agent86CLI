---
phase: quick-260813-jfk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/agent86/config.py
  - src/agent86/cognitive/http_timeouts.py
  - src/agent86/cognitive/ollama_provider.py
  - src/agent86/cognitive/openai_provider.py
  - src/agent86/cognitive/llamacpp_provider.py
  - src/agent86/cognitive/anthropic_provider.py
  - tests/unit/test_config.py
  - tests/unit/test_config_writer.py
  - tests/unit/test_provider_timeouts.py
autonomous: true
requirements: [QUICK-260813-jfk]

must_haves:
  truths:
    - "A streaming request whose server accepts the connection and then never sends another byte fails with a ProviderError after the configured read timeout, instead of blocking forever (the 20+ minute wedge diagnosed by py-spy at ollama_provider.py:108 can no longer happen)."
    - "A slow-but-progressing stream whose TOTAL duration exceeds the read timeout still SUCCEEDS, because httpx's read timeout is the maximum gap BETWEEN received chunks, not a total-request deadline."
    - "Both `read_timeout_s` and `connect_timeout_s` are per-provider config knobs on `ProviderConfig`, resolved through the normal layered config load, and survive a `config_writer.plan_edit`/`apply_edit` round trip."
    - "A timeout ProviderError message names WHICH limit fired, its current value, and the exact config key to raise it."
    - "The existing Ollama `ConnectError` message is byte-unchanged: \"Cannot reach Ollama at {base_url}. Is it running? Start it with 'ollama serve'.\""
    - "The OpenAI-compatible fix covers llama.cpp, LM Studio, OpenRouter, Groq, Azure and vLLM, because `LlamaCppProvider` subclasses `OpenAIProvider` and every custom `[providers.*]` block with a `base_url` routes to `OpenAIProvider`."
    - "A `LlamaCppProvider` built from a config with no `base_url` still honours that config's `read_timeout_s`/`connect_timeout_s` (they are not dropped by the default-base-url substitution)."
    - "A timeout surfaces as a normal `error:` line in the plain loop and `run --json`, never a traceback, because it is a `ProviderError` and both surfaces already catch it."
    - "No new dependency, and no Textual/keyring/tomlkit import reaches the `run` one-shot path."
  artifacts:
    - path: "src/agent86/cognitive/http_timeouts.py"
      provides: "The single place that turns a ProviderConfig into a split httpx.Timeout, and an httpx.TimeoutException into an actionable ProviderError"
      exports: ["stream_timeout", "timeout_error"]
      min_lines: 40
    - path: "src/agent86/config.py"
      provides: "`connect_timeout_s` / `read_timeout_s` fields on ProviderConfig with documented defaults"
      contains: "read_timeout_s"
    - path: "src/agent86/cognitive/ollama_provider.py"
      provides: "Bounded httpx.stream timeout + TimeoutException -> ProviderError, ConnectError branch untouched"
      contains: "httpx.TimeoutException"
    - path: "src/agent86/cognitive/openai_provider.py"
      provides: "Bounded httpx.stream timeout + TimeoutException -> ProviderError (covers llamacpp/openrouter/groq/azure/vllm)"
      contains: "httpx.TimeoutException"
    - path: "tests/unit/test_provider_timeouts.py"
      provides: "Real-loopback-server stall + slow-drip tests, config-reaches-httpx tests, ConnectError-unchanged pins"
      min_lines: 150
  key_links:
    - from: "src/agent86/cognitive/ollama_provider.py::stream"
      to: "httpx.stream"
      via: "timeout=self._timeout (never timeout=None)"
      pattern: "timeout=self\\._timeout"
    - from: "src/agent86/cognitive/openai_provider.py::stream"
      to: "httpx.stream"
      via: "timeout=self._timeout (never timeout=None)"
      pattern: "timeout=self\\._timeout"
    - from: "src/agent86/cognitive/ollama_provider.py"
      to: "agent86.cognitive.http_timeouts::timeout_error"
      via: "except httpx.TimeoutException -> raise timeout_error(...)"
      pattern: "except httpx\\.TimeoutException"
    - from: "src/agent86/cognitive/openai_provider.py"
      to: "agent86.cognitive.http_timeouts::timeout_error"
      via: "except httpx.TimeoutException -> raise timeout_error(...)"
      pattern: "except httpx\\.TimeoutException"
    - from: "agent86.config.ProviderConfig"
      to: "agent86.cognitive.http_timeouts::stream_timeout"
      via: "config.read_timeout_s / config.connect_timeout_s read at provider construction"
      pattern: "config\\.read_timeout_s"
    - from: "src/agent86/cognitive/llamacpp_provider.py"
      to: "agent86.config.ProviderConfig"
      via: "model_copy(update={'base_url': ...}) preserves the timeout fields"
      pattern: "model_copy"
---

<objective>
Bound the two unbounded streaming HTTP reads that caused a real 20+ minute hang, and make the
bound user-configurable per provider.

Purpose: `httpx.stream(..., timeout=None)` at `ollama_provider.py:101` and
`openai_provider.py:142` means a server that accepts a request and then stops sending — exactly
what happened when Ollama's keep-alive expired and its `llama-server` runner wedged mid-teardown
without closing the socket — blocks the turn worker in `recv()` forever. Nothing wakes it. The TUI
status line sat on "working" at 0% CPU until the user killed it.

Output: a `connect_timeout_s`/`read_timeout_s` pair on `ProviderConfig`, one shared
`cognitive/http_timeouts.py` helper, both call sites bounded, `httpx.TimeoutException` converted to
an actionable `ProviderError` in both providers, and a test suite that proves a stall fails fast
while a long-but-progressing generation still succeeds.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md

@src/agent86/config.py
@src/agent86/cognitive/ollama_provider.py
@src/agent86/cognitive/openai_provider.py
@src/agent86/cognitive/llamacpp_provider.py
@src/agent86/cognitive/anthropic_provider.py
@src/agent86/cognitive/base.py
@src/agent86/cognitive/catalog.py
@src/agent86/config_writer.py
@tests/unit/test_ollama_provider.py
@tests/unit/test_openai_provider.py
@tests/unit/test_config.py
@tests/unit/test_config_writer.py

<interfaces>
<!-- Contracts the executor needs. Do NOT go exploring — these are current as of planning. -->

Current (BROKEN) call sites — `timeout=None` means "no timeout at all", not "default":

    # src/agent86/cognitive/ollama_provider.py:100-102
    with httpx.stream(
        "POST", f"{self._base_url}/api/chat", json=payload, timeout=None
    ) as resp:

    # src/agent86/cognitive/openai_provider.py:141-143
    with httpx.stream(
        "POST", self._url, json=payload, headers=headers, timeout=None
    ) as resp:

Existing ConnectError branches (their wording is a pin — must not change):

    # ollama_provider.py:132-136
    except httpx.ConnectError as exc:
        raise ProviderError(
            f"Cannot reach Ollama at {self._base_url}. Is it running? "
            "Start it with 'ollama serve'."
        ) from exc

    # openai_provider.py:169-170
    except httpx.ConnectError as exc:
        raise ProviderError(f"Cannot reach {self._url}: {exc}") from exc

httpx exception hierarchy (relevant, verified): `TimeoutException` and `NetworkError` are SIBLINGS
under `TransportError`. `ConnectTimeout`/`ReadTimeout`/`WriteTimeout`/`PoolTimeout` subclass
`TimeoutException`; `ConnectError` subclasses `NetworkError`. They are DISJOINT — adding an
`except httpx.TimeoutException` clause cannot shadow or alter the existing `ConnectError` clause.

    # src/agent86/config.py:55-61 (current)
    class ProviderConfig(BaseModel):
        api_key_env: str | None = None
        base_url: str | None = None
        num_ctx: int | None = None

    # src/agent86/cognitive/catalog.py:29-30 — the naming precedent to follow
    #: Every network call here is a UI-blocking catalog fetch behind a worker thread; keep it short.
    _TIMEOUT_S = 10.0

    # src/agent86/cognitive/base.py:31
    class ProviderError(RuntimeError): ...

    # src/agent86/cognitive/llamacpp_provider.py:21-24 — note the field-dropping bug
    def __init__(self, model, config, api_key=UNRESOLVED):
        if not config.base_url:
            config = ProviderConfig(base_url=_DEFAULT_LOCAL_BASE, api_key_env=config.api_key_env)
        super().__init__(model=model, config=config, require_key=False, api_key=api_key)

    # src/agent86/config_writer.py — generic over key paths; `read_timeout_s` is NOT in
    # _FORBIDDEN_LEAF_KEYS, so plan_edit(["providers","ollama","read_timeout_s"], 900.0) already
    # works. NO change to config_writer.py is required — only a round-trip test.

Error-surfacing sites that already catch ProviderError (so NO change is needed in either):

    # src/agent86/cli.py:158        except (ProviderError, HarnessError) as exc:  # run / run --json
    # src/agent86/ui/repl.py:260    except (ProviderError, HarnessError) as exc:  # plain loop
    # src/agent86/ui/repl.py:304    except (ProviderError, HarnessError) as exc:  # rich loop
</interfaces>

<design_decisions>
**D-1 — Split timeout, never a scalar.** Use
`httpx.Timeout(connect=..., read=..., write=..., pool=...)`. httpx's `read` timeout is the maximum
gap between received chunks, NOT a total request deadline. That is precisely the right semantic for
streaming: a long-but-progressing generation is never penalised, a stalled socket dies. A single
scalar or any total-duration deadline would break long legitimate generations — do not impose one.
`write` and `pool` take the connect value (the request body is a small JSON POST).

**D-2 — Defaults: `read_timeout_s = 300.0`, `connect_timeout_s = 10.0`.**
Read is sized for time-to-first-token, not for the total turn: prompt evaluation on slow local
hardware can run for minutes before the first chunk arrives, and the read timeout must not fire
during it. The incident's own preceding, legitimate request took 1m8s end to end; 300s gives ~4.4x
headroom over that observed worst case while still bounding a dead socket to 5 minutes instead of
the 20+ minutes actually observed. Connect is 10.0 to match `catalog.py`'s `_TIMEOUT_S = 10.0` — a
TCP connect that has not completed in 10s is a down endpoint, not a slow one.

**D-3 — Anthropic: DEFER to the SDK, do not wire the knob.** `anthropic_provider.py:93` builds
`anthropic.Anthropic(**kwargs)` with no explicit timeout, so the SDK's own default (~600s) applies
and the unbounded-hang class of bug does not exist there. Wiring our `read_timeout_s` into it would
be actively wrong: the SDK's `timeout=` is a total-request budget with its own retry layer on top,
so passing a value whose documented meaning here is "max inter-chunk gap" would silently change
semantics and could kill a legitimate long generation — the exact failure D-1 exists to prevent.
Action: add a short comment at the client-construction site recording this deliberate deferral so it
is not re-litigated. No behaviour change.

**D-4 — `tools/mcp_client.py:266` is OUT OF SCOPE.** `httpx.AsyncClient(headers=...)` with no
`timeout=` inherits httpx's 5s default across connect/read/write/pool. That is bounded, so it is not
a hang risk and not this task's bug. No change; recorded here so the omission is deliberate.

**D-5 — One shared helper, not two copies.** `cognitive/http_timeouts.py` owns both the
`ProviderConfig -> httpx.Timeout` conversion and the `TimeoutException -> ProviderError` message, so
the two providers cannot drift and the message logic is unit-testable in isolation. It imports
`httpx` (already a core top-level import in both providers) and `ProviderError` from
`cognitive.base`; `base.py` does not import it, so there is no cycle. Nothing lazy-imported here —
no Textual/keyring/tomlkit involvement at all.

**D-6 — Config section name in the message.** Ollama knows its section is `[providers.ollama]` and
says so exactly. `OpenAIProvider` does NOT know its section (a custom `[providers.myvllm]` block
routes here with `self.name == "openai"`), so it passes `section=None` and the helper renders a
generic "the [providers.*] block for this endpoint" phrasing. Do not plumb the section name through
`_build_provider` — that is scope creep for a message string.
</design_decisions>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add the per-provider timeout knobs and the shared httpx timeout helper</name>
  <files>
    src/agent86/config.py,
    src/agent86/cognitive/http_timeouts.py,
    tests/unit/test_config.py,
    tests/unit/test_config_writer.py
  </files>
  <behavior>
    - `ProviderConfig()` (no args) has `read_timeout_s == 300.0` and `connect_timeout_s == 10.0`.
    - A user config.toml with `[providers.ollama] read_timeout_s = 900.0` resolves through
      `load_config()` to `cfg.providers["ollama"].read_timeout_s == 900.0`, while
      `cfg.providers["openai"].read_timeout_s` stays at the 300.0 default (per-provider isolation,
      proving the deep-merge does not smear one provider's value onto another).
    - `stream_timeout(ProviderConfig())` returns an `httpx.Timeout` with `.read == 300.0`,
      `.connect == 10.0`, `.write == 10.0`, `.pool == 10.0`.
    - `stream_timeout(ProviderConfig(read_timeout_s=42.0, connect_timeout_s=3.0))` returns
      `.read == 42.0` and `.connect == .write == .pool == 3.0`.
    - `timeout_error(httpx.ReadTimeout("x"), endpoint="http://h/api/chat", timeout=<t>,
      section="ollama")` returns a `ProviderError` whose message contains the endpoint, the read
      limit value, the words `read_timeout_s` and `[providers.ollama]`, and states that the limit is
      the gap between chunks rather than the total generation time.
    - `timeout_error(httpx.ConnectTimeout("x"), ..., section="ollama",
      connect_hint="Is it running? Start it with 'ollama serve'.")` returns a `ProviderError`
      naming `connect_timeout_s`, its value, and containing the hint verbatim.
    - `timeout_error(..., section=None)` still produces a usable message (no `None` leaks into the
      text, no `[providers.None]`).
    - A `plan_edit`/`apply_edit` round trip of
      `(["providers", "ollama", "read_timeout_s"], 900.0)` writes valid TOML that `load_config()`
      reads back as `900.0`, and the hand-written comments in
      `tests/fixtures/config_with_comments.toml` survive.
  </behavior>
  <action>
Write the tests first (RED), then the implementation.

**1. `src/agent86/config.py` — extend `ProviderConfig` (per D-2).**
Add two module-level constants immediately above the class, following `catalog.py:30`'s
`_TIMEOUT_S = 10.0` naming style:

```python
#: httpx's `read` timeout is the maximum gap between received chunks, NOT a total-request
#: deadline — so a long but *progressing* generation is never penalised, while a stalled socket
#: fails. Sized for time-to-first-token: prompt evaluation on slow local hardware can run for
#: minutes before the first chunk arrives. 300s is ~4.4x the longest legitimate request observed
#: (1m8s) and bounds a wedged server to 5 minutes instead of the 20+ minutes actually seen.
_DEFAULT_READ_TIMEOUT_S = 300.0
#: A TCP connect that has not completed in 10s is a down endpoint, not a slow one.
#: Matches cognitive/catalog.py's _TIMEOUT_S.
_DEFAULT_CONNECT_TIMEOUT_S = 10.0
```

Add the fields to `ProviderConfig`, each with a comment explaining the semantic (mirroring how
`num_ctx` documents *why* it exists), and keep them provider-scoped so a slow local backend and a
fast cloud one tune independently:

```python
    # Streaming HTTP limits, per provider. read_timeout_s is the maximum gap BETWEEN streamed
    # chunks (httpx semantics), not the total generation time — raise it for slow local hardware
    # with long prompt-eval times; a genuinely wedged server still fails instead of hanging.
    connect_timeout_s: float = _DEFAULT_CONNECT_TIMEOUT_S
    read_timeout_s: float = _DEFAULT_READ_TIMEOUT_S
```

Do NOT import httpx in `config.py` — it stays a leaf module. Do not touch anything else in the file.

**2. Create `src/agent86/cognitive/http_timeouts.py`.**
Module docstring must state the read-timeout semantic (max inter-chunk gap, not total duration) and
reference the hang it prevents. Top-level `import httpx`; `from agent86.cognitive.base import
ProviderError`; `from agent86.config import ProviderConfig`.

```python
def stream_timeout(config: ProviderConfig) -> httpx.Timeout:
    """Split timeout for a streaming request. Never a scalar, never None."""
    return httpx.Timeout(
        connect=config.connect_timeout_s,
        read=config.read_timeout_s,
        write=config.connect_timeout_s,
        pool=config.connect_timeout_s,
    )


def timeout_error(
    exc: httpx.TimeoutException,
    *,
    endpoint: str,
    timeout: httpx.Timeout,
    section: str | None = None,
    connect_hint: str = "",
) -> ProviderError:
    """Convert an httpx timeout into a ProviderError naming the limit that fired."""
```

`timeout_error` branches on `isinstance(exc, httpx.ConnectTimeout)`:
- connect case: name `connect_timeout_s`, its value (`{timeout.connect:g}`), the endpoint, append
  `connect_hint` when non-empty, and say where to raise it.
- everything else (read/write/pool): name `read_timeout_s`, its value (`{timeout.read:g}`), the
  endpoint, and state explicitly that this is the maximum gap between streamed chunks rather than
  the total generation time — a user reading this must not conclude their long generation was
  killed for being long.
Both cases end with the config location: `[providers.{section}]` when `section` is given, otherwise
`the [providers.*] block for this endpoint`. Build that suffix once in a local variable so `None`
can never reach the rendered text. Keep every line under 100 chars (ruff line-length 100).
Export `__all__ = ["stream_timeout", "timeout_error"]`.

**3. Tests.**
- Append to `tests/unit/test_config.py`: the defaults test and the per-provider TOML override
  test (follow the file's existing `monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", ...)` +
  `textwrap.dedent` pattern; patch BOTH `USER_CONFIG_PATH` and `PROJECT_CONFIG_PATH`).
- Append to `tests/unit/test_config_writer.py`: the round-trip test. IMPORTANT — `apply_edit` calls
  `load_config()`, which reads `agent86.config`'s OWN module globals, so patch
  `config_writer.USER_CONFIG_PATH` **and** `agent86.config.USER_CONFIG_PATH` **and**
  `agent86.config.PROJECT_CONFIG_PATH` (the existing `test_comments_preserved_roundtrip` only
  patches the first, which is why it asserts on file text rather than on the reloaded Config).
- Put the `stream_timeout` / `timeout_error` unit tests in the NEW file
  `tests/unit/test_provider_timeouts.py` (created here, extended by Tasks 2 and 3) with a module
  docstring noting the file covers the streaming-timeout fix.
  </action>
  <verify>
    <automated>C:/Projects/agent86CLI/.venv/Scripts/python.exe -m pytest tests/unit/test_config.py tests/unit/test_config_writer.py tests/unit/test_provider_timeouts.py -q</automated>
  </verify>
  <done>
    `ProviderConfig` exposes `connect_timeout_s`/`read_timeout_s` with the D-2 defaults;
    `cognitive/http_timeouts.py` exists exporting `stream_timeout` and `timeout_error`; the config
    layer, the writer round trip, and both helpers are covered by passing tests; `config.py` still
    imports no httpx.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Bound both streaming call sites and convert timeouts to ProviderError</name>
  <files>
    src/agent86/cognitive/ollama_provider.py,
    src/agent86/cognitive/openai_provider.py,
    src/agent86/cognitive/llamacpp_provider.py,
    src/agent86/cognitive/anthropic_provider.py,
    tests/unit/test_provider_timeouts.py
  </files>
  <behavior>
    - `OllamaProvider("m", ProviderConfig())` passes `timeout=` to `httpx.stream` as an
      `httpx.Timeout` with `.read == 300.0` and `.connect == 10.0` — never `None`.
    - `OllamaProvider("m", ProviderConfig(read_timeout_s=900.0, connect_timeout_s=3.0))` passes
      `.read == 900.0`, `.connect == 3.0` (per-provider override reaches httpx).
    - Both hold identically for `OpenAIProvider("m", ProviderConfig(base_url=...),
      require_key=False)`.
    - `LlamaCppProvider("m", ProviderConfig(read_timeout_s=900.0))` — i.e. a config with NO
      `base_url`, taking the default-local-base substitution path — still passes `.read == 900.0`.
    - An `httpx.ReadTimeout` raised from inside `httpx.stream` surfaces from `provider.complete(...)`
      as a `ProviderError` (not an `httpx` exception) whose message names `read_timeout_s`, its
      value, and the endpoint — for BOTH providers.
    - An `httpx.ConnectTimeout` surfaces as a `ProviderError` naming `connect_timeout_s`; the Ollama
      one additionally contains "Start it with 'ollama serve'".
    - `httpx.ConnectError` still produces its EXACT existing message for both providers:
      Ollama == "Cannot reach Ollama at http://x. Is it running? Start it with 'ollama serve'."
      and OpenAI startswith "Cannot reach " + the url.
    - `tests/unit/test_ollama_provider.py` and `tests/unit/test_openai_provider.py` still pass
      unmodified (their fakes ignore kwargs, so adding `timeout=` must not break them).
  </behavior>
  <action>
Write the tests first (RED — confirm the timeout assertions fail against the current `timeout=None`
source before implementing), then implement.

**1. `ollama_provider.py`.**
- `from agent86.cognitive.http_timeouts import stream_timeout, timeout_error`.
- In `__init__`, after `self._num_ctx = config.num_ctx`, add `self._timeout = stream_timeout(config)`.
- In `stream`, replace `timeout=None` with `timeout=self._timeout`.
- Leave the existing `except httpx.ConnectError` block byte-identical, and add a NEW clause after it
  (the two exception types are disjoint siblings, so order is irrelevant — appending simply keeps
  the diff minimal and the existing wording provably untouched):

```python
        except httpx.TimeoutException as exc:
            raise timeout_error(
                exc,
                endpoint=f"{self._base_url}/api/chat",
                timeout=self._timeout,
                section="ollama",
                connect_hint="Is it running? Start it with 'ollama serve'.",
            ) from exc
```

**2. `openai_provider.py`.**
- Same import.
- In `__init__`, set `self._timeout = stream_timeout(config)` immediately after `self._url` is
  built and BEFORE the key-resolution block, so the attribute exists on every construction path
  (that block can raise `ProviderError`).
- Replace `timeout=None` with `timeout=self._timeout`.
- Add the matching clause after the existing `except httpx.ConnectError`, with
  `endpoint=self._url` and `section=None` (per D-6 this provider cannot know its config section —
  a custom `[providers.myvllm]` block routes here with `self.name == "openai"`), no `connect_hint`.

**3. `llamacpp_provider.py` — fix the field-dropping substitution.**
`ProviderConfig(base_url=_DEFAULT_LOCAL_BASE, api_key_env=config.api_key_env)` silently discards
every OTHER field on the user's config, which from now on includes `read_timeout_s` and
`connect_timeout_s` — a user's `[providers.llamacpp] read_timeout_s = 900` would be thrown away
whenever `base_url` is unset. Replace with:

```python
        if not config.base_url:
            config = config.model_copy(update={"base_url": _DEFAULT_LOCAL_BASE})
```

Add a one-line comment saying the copy is what preserves the caller's timeout (and any future)
fields. Everything else in the file is unchanged.

**4. `anthropic_provider.py` — comment only, per D-3.**
Immediately above `self._client = anthropic.Anthropic(**kwargs)` add a short comment recording the
deliberate deferral: the SDK applies its own ~600s default so this path cannot hang unbounded, and
its `timeout=` is a total-request budget whose meaning differs from `read_timeout_s` (max
inter-chunk gap), so wiring the knob here would silently change semantics and could kill a
legitimate long generation. **No behaviour change — do not add a `timeout` kwarg.**

**5. Tests** — extend `tests/unit/test_provider_timeouts.py`. Use the monkeypatched-`httpx.stream`
style already established in `tests/unit/test_ollama_provider.py` / `test_openai_provider.py`
(`monkeypatch.setattr(mod.httpx, "stream", ...)` with a capture dict and a small fake CM), plus
variants whose fake raises `httpx.ReadTimeout("stalled")` / `httpx.ConnectTimeout("no route")` /
`httpx.ConnectError("refused")`. Assert the Ollama ConnectError message with `==` against the exact
literal so any future rewording is caught. Do NOT modify `test_ollama_provider.py` or
`test_openai_provider.py` — that they still pass unmodified is part of the verification.
  </action>
  <verify>
    <automated>C:/Projects/agent86CLI/.venv/Scripts/python.exe -m pytest tests/unit/test_provider_timeouts.py tests/unit/test_ollama_provider.py tests/unit/test_openai_provider.py tests/unit/test_providers_key_seam.py -q</automated>
  </verify>
  <done>
    Neither provider passes `timeout=None` anywhere (`grep -n "timeout=None" src/agent86/` returns
    nothing); both pass a config-derived `httpx.Timeout`; `httpx.TimeoutException` becomes an
    actionable `ProviderError` in both; the two existing ConnectError messages are pinned unchanged;
    `LlamaCppProvider` preserves the caller's timeout fields; `anthropic_provider.py` carries the
    D-3 deferral comment and no behaviour change.
  </done>
</task>

<task type="auto">
  <name>Task 3: Prove the semantics against a real socket — stall fails, slow-but-progressing succeeds</name>
  <files>tests/unit/test_provider_timeouts.py</files>
  <action>
This is the load-bearing task: the guarantee in D-1 is a property of **real httpx**, so it cannot be
proved by a fake we wrote ourselves (that would be circular). Drive both providers against a real
loopback HTTP server.

**Server harness** (module-level in the test file):
- `http.server.ThreadingHTTPServer` bound to `("127.0.0.1", 0)`; read the assigned port from
  `srv.server_address[1]`. Serve it on a daemon thread; shut it down in a pytest fixture's teardown
  (`srv.shutdown()` + `srv.server_close()` + `thread.join(timeout=5)`).
- Keep `BaseHTTPRequestHandler`'s default `protocol_version = "HTTP/1.0"`. With no `Content-Length`
  the body is delimited by connection close, which is exactly what lets us dribble chunks out
  without hand-rolling chunked transfer encoding.
- The handler MUST read `Content-Length` bytes of the request body before responding, or the client
  can block on write.
- Silence the per-request stderr log (`def log_message(self, *a): pass`) so the suite output stays
  clean.
- Two behaviours, selected by a module-level mutable holder the tests set:
  * `stall`: `send_response(200)`, `send_header("Content-Type", ...)`, `end_headers()`,
    `wfile.flush()`, then wait on a `threading.Event` that is only set in fixture teardown —
    headers arrive (so the `with httpx.stream(...)` block is entered) and then not one further byte
    ever comes. This is the incident, reproduced.
  * `slow_drip`: same headers, then N chunks each followed by `wfile.flush()` and
    `time.sleep(gap)`.
- Route on `self.path`: `/api/chat` emits Ollama NDJSON (one JSON object per line, the last with
  `"done": true`); `/v1/chat/completions` emits OpenAI SSE (`data: {...}` lines, then
  `data: [DONE]`). Reuse the exact payload shapes from `tests/unit/test_ollama_provider.py` and
  `test_openai_provider.py`.

**Hard test-level timeout.** There is no `pytest-timeout` plugin in this project (see
`pyproject.toml` `[project.optional-dependencies] dev`) and you must NOT add one. Instead run every
provider call through `concurrent.futures.ThreadPoolExecutor(max_workers=1)` and
`future.result(timeout=<hard>)`. A `concurrent.futures.TimeoutError` there means the fix regressed
and the test FAILS rather than hanging the suite. Wrap it so the failure message says so. Put this
in a small local helper, e.g. `_call_with_hard_timeout(fn, hard_s)`.

**Tests to write:**

1. `test_stalled_ollama_stream_raises_provider_error` — server in `stall` mode,
   `OllamaProvider("m", ProviderConfig(base_url=f"http://127.0.0.1:{port}", read_timeout_s=0.5,
   connect_timeout_s=2.0))`. Hard timeout 15s. Assert a `ProviderError` is raised (NOT an httpx
   exception), that its message mentions `read_timeout_s`, and that the elapsed time is comfortably
   under the hard timeout (e.g. `< 5.0`) so "it eventually failed for some other reason" cannot pass.

2. `test_stalled_openai_stream_raises_provider_error` — same against
   `OpenAIProvider("m", ProviderConfig(base_url=f"http://127.0.0.1:{port}/v1",
   read_timeout_s=0.5, connect_timeout_s=2.0), require_key=False)`.

3. `test_slow_but_progressing_stream_succeeds_past_the_read_timeout` — **the key semantic
   guarantee; make it unambiguous.** Server in `slow_drip` mode: 6 chunks, 0.25s gap ⇒ ~1.5s total.
   Configure `read_timeout_s=0.6`. Then:
   - assert the call SUCCEEDS and `completion.text` equals the full concatenation of all 6 chunks
     (nothing truncated);
   - assert `elapsed > read_timeout_s` **explicitly**, with a comment stating that this is the
     whole point: total duration exceeding the read timeout must not fail, because the read timeout
     bounds the gap between chunks (max 0.25s here), not the total. Without this assertion the test
     could silently degrade into a fast path and prove nothing.
   Parametrize over both providers (ollama NDJSON and openai SSE) so the guarantee is proved for
   both wire formats.

4. `test_stall_is_not_masked_by_a_generous_connect_timeout` (cheap, high value) — `stall` mode with
   `connect_timeout_s=5.0, read_timeout_s=0.5`; assert it still fails in well under 5s, proving the
   read limit (not the connect limit) is what fires.

**Timing tolerance:** these are the only wall-clock-sensitive tests in the suite. Keep gaps/limits
generous relative to scheduler jitter on Windows (0.25s gap vs a 0.6s limit is >2x headroom) and
never assert an upper bound tighter than ~3x the expected value. Do not use `time.sleep` in the
test body to synchronise with the server — use the server's own event/flush ordering.
  </action>
  <verify>
    <automated>C:/Projects/agent86CLI/.venv/Scripts/python.exe -m pytest tests/unit/test_provider_timeouts.py -q</automated>
  </verify>
  <done>
    A stalled real socket produces a `ProviderError` in under a second of configured budget instead
    of hanging; a real stream whose total duration exceeds the read timeout still completes with
    full text for both wire formats; every provider call is wrapped in a hard test-level timeout so
    a regression fails the suite rather than wedging it; no new dependency was added.
  </done>
</task>

</tasks>

<verification>
Run from the repo root with the project venv (bare `python` lacks agent86):

1. Targeted: `C:/Projects/agent86CLI/.venv/Scripts/python.exe -m pytest tests/unit/test_provider_timeouts.py tests/unit/test_config.py tests/unit/test_config_writer.py tests/unit/test_ollama_provider.py tests/unit/test_openai_provider.py -q`
2. Full suite: `C:/Projects/agent86CLI/.venv/Scripts/python.exe -m pytest -q`
   Expect **454 + new tests passed, 6 skipped, 1 failed**. The single failure
   `tests/unit/test_memory.py::test_build_embedder_falls_back_without_torch` is PRE-EXISTING and
   environment-dependent — do NOT fix it and do NOT report it as a regression.
3. No unbounded reads remain: `grep -rn "timeout=None" src/agent86/` returns nothing.
4. Lazy-import contract intact: `C:/Projects/agent86CLI/.venv/Scripts/python.exe -m pytest tests/tui/test_lazy_import.py -q` (2 passed). No Textual/keyring/tomlkit reaches the `run` path.
5. Lint: `C:/Projects/agent86CLI/.venv/Scripts/python.exe -m ruff check .` — must introduce no NEW
   errors. 4 errors are pre-existing and out of scope: E501 in `src/agent86/tui/app.py`, and
   I001 + E501 in `tests/tui/test_app.py`.
6. Untouched by design (confirm with `git diff --stat`): `src/agent86/config_writer.py`,
   `src/agent86/cli.py`, `src/agent86/ui/repl.py`, `src/agent86/tui/`,
   `src/agent86/tools/mcp_client.py` (D-4), `src/agent86/cognitive/catalog.py`,
   `src/agent86/types.py`, `pyproject.toml`. `ModelRef.parse` and `fetch_catalog`'s bare-id
   contract are unchanged, so quick tasks 260813-adr / 260813-atc are unaffected.
   `py-spy` must NOT appear in `pyproject.toml`.
7. The plain loop / `run --json` contract: no change is required there because a timeout is now a
   `ProviderError`, which `cli.py:158`, `ui/repl.py:260` and `ui/repl.py:304` already catch and
   render as a plain `error:` line. Confirm those three clauses are still present and unmodified.
</verification>

<success_criteria>
- Neither `httpx.stream` call site passes `timeout=None`; both pass a split `httpx.Timeout` derived
  from `ProviderConfig`.
- A stalled stream raises `ProviderError` within the configured read budget, proved against a real
  loopback socket with a hard test-level timeout guarding against a hang.
- A slow-but-progressing stream whose TOTAL duration exceeds the read timeout still succeeds, with
  an explicit `elapsed > read_timeout_s` assertion, for both NDJSON and SSE.
- `read_timeout_s` / `connect_timeout_s` are per-provider config knobs that resolve through the
  layered load, round-trip through `config_writer`, and demonstrably reach the httpx call for
  Ollama, OpenAI-compatible, and llama.cpp.
- Timeout `ProviderError` messages name the limit that fired, its current value, and how to raise
  it; the read message explicitly states it bounds the inter-chunk gap, not total generation time.
- The existing Ollama `ConnectError` message is byte-unchanged.
- Anthropic (D-3) and `tools/mcp_client.py` (D-4) are explicitly, deliberately unchanged.
- Full suite green apart from the one documented pre-existing failure; no new ruff errors; no new
  dependency.
</success_criteria>

<output>
After completion, create
`.planning/quick/260813-jfk-configurable-http-timeouts-for-streaming/260813-jfk-SUMMARY.md`.
Record: the chosen defaults and their justification, the D-3 Anthropic and D-4 mcp_client
decisions, the `LlamaCppProvider` field-dropping fix found along the way, RED evidence for the
timeout assertions, and the final full-suite counts.
</output>
</content>
</invoke>
