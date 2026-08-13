---
quick_id: 260813-jfk
description: Configurable HTTP timeouts for streaming (bound the two unbounded httpx.stream reads)
completed: 2026-08-13
commits:
  - b2dc151
  - 8c1ed1d
  - a7a63f4
  - 6616da8
  - c600987
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
---

# Quick Task 260813-jfk: Configurable HTTP timeouts for streaming — Summary

**One-liner:** Both `httpx.stream(..., timeout=None)` call sites (Ollama, OpenAI-compatible) now
pass a split `httpx.Timeout` derived from new per-provider `read_timeout_s`/`connect_timeout_s`
config knobs (defaults 300.0/10.0), with `httpx.TimeoutException` converted to an actionable
`ProviderError` — proved against a real loopback socket that a stall fails fast while a
slow-but-progressing stream whose total duration exceeds the read timeout still succeeds.

## What Was Wrong

`httpx.stream(..., timeout=None)` at `ollama_provider.py:101` and `openai_provider.py:142` meant
"no timeout at all." A server that accepted a request and then stopped sending — exactly what
happened when Ollama's keep-alive expired and its `llama-server` runner wedged mid-teardown
without closing the socket — blocked the turn worker in `recv()` forever, with nothing to wake
it. The TUI status line sat on "working" at 0% CPU until the user killed it (py-spy diagnosed the
wedge at `ollama_provider.py:108`, a 20+ minute hang).

## Fix

**Task 1** (`b2dc151` RED, `8c1ed1d` GREEN): `ProviderConfig` gains `connect_timeout_s = 10.0`
and `read_timeout_s = 300.0` (per D-2: read is sized for time-to-first-token — prompt evaluation
on slow local hardware can run for minutes before the first chunk arrives — 300s is ~4.4x the
incident's own preceding legitimate request (1m8s), bounding a wedged server to 5 minutes instead
of the 20+ minutes actually observed; connect matches `catalog.py`'s existing `_TIMEOUT_S = 10.0`).
New `src/agent86/cognitive/http_timeouts.py` (D-5, one shared helper so the two providers cannot
drift) exports `stream_timeout(config) -> httpx.Timeout` (always split — `connect`/`read`/`write`/
`pool`, never a scalar, per D-1) and `timeout_error(exc, *, endpoint, timeout, section,
connect_hint) -> ProviderError`, which names the limit that actually fired, its current value,
and the exact config key/section to raise it; the read-timeout message explicitly states it
bounds the gap between chunks, not total generation time, so a user reading it cannot conclude
their long generation was killed for being long. `config.py` still imports no `httpx` (verified:
`grep -n "^import httpx" src/agent86/config.py` empty).

**Task 2** (`a7a63f4` RED, `6616da8` GREEN): Both call sites replaced `timeout=None` with
`timeout=self._timeout` (`stream_timeout(config)`, computed once in `__init__`). Both gained a new
`except httpx.TimeoutException as exc: raise timeout_error(...) from exc` clause appended AFTER
the existing `except httpx.ConnectError` clause — the two exception types are disjoint siblings
under `httpx.TransportError` (verified against the installed httpx 0.28.1), so append-only keeps
the diff minimal and the pinned `ConnectError` wording provably byte-unchanged. Ollama passes
`section="ollama"` and the existing `"Is it running? Start it with 'ollama serve'."` hint;
`OpenAIProvider` passes `section=None` (per D-6 — a custom `[providers.myvllm]` block routes here
with `self.name == "openai"`, so it cannot know its own config section without scope-creeping
`_build_provider` to plumb it through for a message string).

**`llamacpp_provider.py` field-dropping fix** (found while implementing Task 2, exactly as the
plan's interfaces section flagged): the default-base-url substitution built a bare
`ProviderConfig(base_url=..., api_key_env=...)`, silently discarding every other field on the
user's config — which, as of this task, includes `read_timeout_s`/`connect_timeout_s`. Replaced
with `config.model_copy(update={"base_url": _DEFAULT_LOCAL_BASE})`, which preserves every other
field including any future ones. This was explicitly specified by the plan, not a live deviation.

**`anthropic_provider.py`** (D-3, comment-only, no behaviour change): a comment above
`anthropic.Anthropic(**kwargs)` records the deliberate deferral — the SDK applies its own ~600s
default so this path cannot hang unbounded (the bug class this task closes doesn't exist here),
and the SDK's `timeout=` is a total-request budget with its own retry layer, a different meaning
than `read_timeout_s`'s "max inter-chunk gap"; wiring the knob in would silently change semantics
and could kill a legitimate long generation, exactly the failure the split timeout exists to
prevent.

**`tools/mcp_client.py`** (D-4): confirmed out of scope and untouched — its
`httpx.AsyncClient(headers=...)` has no `timeout=` argument, so it inherits httpx's bounded 5s
default across connect/read/write/pool; not a hang risk, not this task's bug.

**Task 3** (`c600987`, tests-only): the D-1 guarantee — a stalled socket dies, a slow-but-progressing
one doesn't — is a property of REAL httpx, so a hand-rolled fake would prove nothing. Added a
module-level `_ServerState`/`_handler_factory`/`loopback_server` fixture: `http.server.
ThreadingHTTPServer` bound to `("127.0.0.1", 0)`, `protocol_version = "HTTP/1.0"` (body delimited
by connection close, letting the handler dribble chunks with plain writes rather than hand-rolling
chunked transfer encoding), routed on `self.path` (`/api/chat` → Ollama NDJSON, `/v1/chat/
completions` → OpenAI SSE), with two selectable behaviours: `stall` (headers sent, then blocks on
a `threading.Event` set only in fixture teardown — the incident, reproduced) and `slow_drip` (N
chunks, each flushed then followed by a real `time.sleep(gap)`). Every provider call runs through
`_call_with_hard_timeout` — `concurrent.futures.ThreadPoolExecutor(max_workers=1)` +
`future.result(timeout=<hard>)`, deliberately NOT used as a context manager (an implicit
`shutdown(wait=True)` on `__exit__` would itself block forever joining the very thread being timed
out on) — so a real regression fails the test with a clear message instead of hanging the suite.
Four tests: a stalled Ollama stream and a stalled OpenAI stream both raise `ProviderError`
mentioning `read_timeout_s` in well under the 15s hard budget (`elapsed < 5.0`); a stall is not
masked by a generous `connect_timeout_s=5.0` (fires on the much shorter `read_timeout_s=0.5`
instead); and — the key semantic guarantee, parametrized over both wire formats — 6 chunks at a
0.25s gap (~1.5s total) against `read_timeout_s=0.6` still SUCCEEDS with the full, untruncated
concatenated text, with an **explicit** `assert elapsed > read_timeout_s` proving total duration
exceeding the read timeout does not fail the call (without this assertion the test could silently
degrade into a fast path and prove nothing, per this task's own critical test note). No
`pytest-timeout`/`py-spy` dependency was added.

## Verification

```
pytest tests/unit/test_provider_timeouts.py tests/unit/test_config.py \
  tests/unit/test_config_writer.py tests/unit/test_ollama_provider.py \
  tests/unit/test_openai_provider.py -q                    # 56 passed
pytest tests/unit/test_provider_timeouts.py -q             # 22 passed, ~7s (x3 consecutive, stable)
pytest -q                                                   # 479 passed, 6 skipped, 1 failed
pytest tests/tui/test_lazy_import.py -q                     # 2 passed
grep -rn "timeout=None" src/agent86/                        # no call-site matches (only a docstring)
grep -n "py-spy" pyproject.toml                              # absent
ruff check .                                                 # 40 errors — byte-identical set to the
                                                               # pre-task baseline (911c01c), confirmed
                                                               # via a worktree diff; zero new errors
```

The one full-suite failure is the pre-existing, environment-dependent
`tests/unit/test_memory.py::test_build_embedder_falls_back_without_torch` — not fixed, not a
regression, per this task's own environment notes. 479 passed is 454 (documented baseline) + 25
new tests added by this task (9 in `test_config.py`/`test_config_writer.py` combined, 22 in the
new `test_provider_timeouts.py`, minus the split across two RED/GREEN commits which doesn't
change the final count).

`git diff --stat` against the pre-task commit (`911c01c`) for the plan's explicitly
"untouched by design" file list — `src/agent86/config_writer.py`, `src/agent86/cli.py`,
`src/agent86/ui/repl.py`, `src/agent86/tui/`, `src/agent86/tools/mcp_client.py`,
`src/agent86/cognitive/catalog.py`, `src/agent86/types.py`, `pyproject.toml` — is EMPTY. The three
`except (ProviderError, HarnessError)` clauses in `cli.py:158`, `ui/repl.py:260`, and
`ui/repl.py:304` are confirmed present and unmodified — no change was needed there, since a
timeout now surfaces as an ordinary `ProviderError` that those clauses already catch and render as
a plain `error:` line with no traceback, for both `--plain`/`run --json` and the TUI.

**Ruff scope note:** this task's own `environment_notes` documented only 4 pre-existing ruff
errors, but a full-repo `ruff check .` on the pre-task baseline actually reports 40 (in files this
task never touches, e.g. `secrets.py`, `tui/commands.py`, several `tests/tui/*.py` files). This
task's own new/modified files (`test_config.py`, `test_config_writer.py`,
`test_provider_timeouts.py`, and all five touched `src/` files) contribute zero new errors —
verified by diffing the full `ruff check . --output-format=concise` output against a `git
worktree` checkout of `911c01c`: the two listings are byte-identical.

## Success Criteria

- [x] Neither `httpx.stream` call site passes `timeout=None`; both pass a split `httpx.Timeout`
      derived from `ProviderConfig`.
- [x] A stalled stream raises `ProviderError` within the configured read budget, proved against a
      real loopback socket with a hard test-level timeout guarding against a hang.
- [x] A slow-but-progressing stream whose TOTAL duration exceeds the read timeout still succeeds,
      with an explicit `elapsed > read_timeout_s` assertion, for both NDJSON and SSE.
- [x] `read_timeout_s` / `connect_timeout_s` are per-provider config knobs that resolve through the
      layered load, round-trip through `config_writer`, and demonstrably reach the httpx call for
      Ollama, OpenAI-compatible, and llama.cpp.
- [x] Timeout `ProviderError` messages name the limit that fired, its current value, and how to
      raise it; the read message explicitly states it bounds the inter-chunk gap, not total
      generation time.
- [x] The existing Ollama `ConnectError` message is byte-unchanged.
- [x] Anthropic (D-3) and `tools/mcp_client.py` (D-4) are explicitly, deliberately unchanged.
- [x] Full suite green apart from the one documented pre-existing failure; no new ruff errors; no
      new dependency.

## Deviations from Plan

None — plan executed exactly as written, including all five load-bearing constraints called out in
this task's own provenance note (split `httpx.Timeout`, no total-request deadline, `ConnectError`/
`TimeoutException` clause order left append-only, `ollama_provider.py`'s `ConnectError` wording
byte-identical, no `pytest-timeout`/`py-spy` added). The `LlamaCppProvider` field-dropping fix was
explicitly specified by the plan's Task 2 action steps, not a live discovery requiring a deviation
rule.

## Self-Check

- `src/agent86/cognitive/http_timeouts.py` — FOUND, exports `stream_timeout`, `timeout_error`.
- `src/agent86/config.py` — FOUND, contains `read_timeout_s`.
- `src/agent86/cognitive/ollama_provider.py` — FOUND, contains `httpx.TimeoutException`.
- `src/agent86/cognitive/openai_provider.py` — FOUND, contains `httpx.TimeoutException`.
- `tests/unit/test_provider_timeouts.py` — FOUND, 22 tests covering Tasks 1-3.
- Commit `b2dc151` — FOUND in `git log`.
- Commit `8c1ed1d` — FOUND in `git log`.
- Commit `a7a63f4` — FOUND in `git log`.
- Commit `6616da8` — FOUND in `git log`.
- Commit `c600987` — FOUND in `git log`.

## Self-Check: PASSED
