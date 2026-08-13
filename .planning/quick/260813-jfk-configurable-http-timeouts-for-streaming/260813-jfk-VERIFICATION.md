---
phase: quick-260813-jfk-configurable-http-timeouts-for-streaming
verified: 2026-08-13T00:00:00Z
status: passed
score: 9/9 must-haves verified
---

# Quick Task 260813-jfk: Configurable HTTP timeouts for streaming — Verification Report

**Task Goal:** Add configurable HTTP timeouts to the streaming model providers so a stalled
backend fails cleanly with a `ProviderError` instead of hanging the harness forever. Fixes a real
20+ minute hang caused by `httpx.stream(..., timeout=None)` in both streaming providers.

**Verified:** 2026-08-13
**Status:** passed

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| - | ----- | ------ | -------- |
| 1 | A stalled stream (server accepts connection, then sends no more bytes) fails with `ProviderError` after the read timeout, not forever | ✓ VERIFIED | `tests/unit/test_provider_timeouts.py::test_stalled_ollama_stream_raises_provider_error` / `test_stalled_openai_stream_raises_provider_error` drive a real loopback socket in `stall` mode, wrapped in a 15s hard `ThreadPoolExecutor` timeout; both pass, `elapsed < 5.0` |
| 2 | A slow-but-progressing stream whose TOTAL duration exceeds the read timeout still succeeds (read timeout = max inter-chunk gap, not total deadline) | ✓ VERIFIED | `test_slow_but_progressing_stream_succeeds_past_the_read_timeout` (parametrized ollama+openai): 6 chunks × 0.25s gap (~1.5s) vs `read_timeout_s=0.6`; asserts `completion.text` == full concat AND explicit `assert elapsed > read_timeout_s`. Both pass |
| 3 | `read_timeout_s`/`connect_timeout_s` are per-provider `ProviderConfig` knobs, resolve through layered config load, survive `plan_edit`/`apply_edit` round trip | ✓ VERIFIED | `config.py:76-77` fields with 300.0/10.0 defaults; `test_config.py` per-provider-isolation test (ollama override doesn't smear onto openai); `test_config_writer.py::test_read_timeout_s_roundtrip_through_load_config` round-trips `900.0` through `plan_edit`/`apply_edit`/`load_config()` |
| 4 | A timeout `ProviderError` message names WHICH limit fired, its value, and the config key to raise it | ✓ VERIFIED | `http_timeouts.py::timeout_error` — read branch names `read_timeout_s`, its `.read` value, and states it bounds inter-chunk gap not total time; connect branch names `connect_timeout_s`; both append `[providers.{section}]` or a generic fallback when `section=None` (no `None` leak, tested) |
| 5 | Ollama `ConnectError` message byte-unchanged: "Cannot reach Ollama at {base_url}. Is it running? Start it with 'ollama serve'." | ✓ VERIFIED | `ollama_provider.py:134-138` untouched; `test_ollama_connect_error_message_unchanged` asserts `==` against the exact literal |
| 6 | The fix covers llama.cpp, LM Studio, OpenRouter, Groq, Azure, vLLM (all route through `OpenAIProvider`) | ✓ VERIFIED | `LlamaCppProvider` subclasses `OpenAIProvider` (`llamacpp_provider.py:18`); `openai_provider.py` is the single shared call site bounded for all OpenAI-compatible backends |
| 7 | `LlamaCppProvider` built from a config with no `base_url` still honours `read_timeout_s`/`connect_timeout_s` | ✓ VERIFIED | `llamacpp_provider.py:26` uses `config.model_copy(update={"base_url": ...})` instead of reconstructing a bare `ProviderConfig`; `test_llamacpp_preserves_timeout_fields_with_no_base_url` passes |
| 8 | A timeout surfaces as a plain `error:` line in `run --json`/plain loop, never a traceback | ✓ VERIFIED | `timeout_error()` returns `ProviderError`; `cli.py:158`, `ui/repl.py:260`, `ui/repl.py:304` all still present and unmodified (`git diff --stat 911c01c` empty for both files), already catch `(ProviderError, HarnessError)` |
| 9 | No new dependency; no Textual/keyring/tomlkit reaches the `run` one-shot path | ✓ VERIFIED | `pyproject.toml` diff-free vs baseline; no `pytest-timeout`/`py-spy` string anywhere in it; `tests/tui/test_lazy_import.py` — 2 passed |

**Score:** 9/9 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `src/agent86/cognitive/http_timeouts.py` | `stream_timeout`/`timeout_error` helper | ✓ VERIFIED | 67 lines (≥40), exports both via `__all__`, imports `httpx` + `ProviderError` + `ProviderConfig`, no cycle |
| `src/agent86/config.py` | `connect_timeout_s`/`read_timeout_s` fields | ✓ VERIFIED | Lines 76-77, defaults 10.0/300.0, documented; still no `import httpx` in the file |
| `src/agent86/cognitive/ollama_provider.py` | Bounded timeout + `TimeoutException` handling | ✓ VERIFIED | `timeout=self._timeout` (line 103), `except httpx.TimeoutException` clause (139-146) appended after untouched `ConnectError` clause (134-138) |
| `src/agent86/cognitive/openai_provider.py` | Same, covers all OpenAI-compatible backends | ✓ VERIFIED | `timeout=self._timeout` (line 144), `except httpx.TimeoutException` clause (173-179) after untouched `ConnectError` clause (171-172) |
| `tests/unit/test_provider_timeouts.py` | Real-loopback stall/slow-drip tests, config-reaches-httpx, ConnectError pins | ✓ VERIFIED | 482 lines (≥150), 22 tests, all pass consistently across repeated runs (~7s each) |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `ollama_provider.py::stream` | `httpx.stream` | `timeout=self._timeout` | ✓ WIRED | Line 103, never `None` |
| `openai_provider.py::stream` | `httpx.stream` | `timeout=self._timeout` | ✓ WIRED | Line 144, never `None` |
| `ollama_provider.py` | `http_timeouts::timeout_error` | `except httpx.TimeoutException` | ✓ WIRED | Lines 139-146 |
| `openai_provider.py` | `http_timeouts::timeout_error` | `except httpx.TimeoutException` | ✓ WIRED | Lines 173-179 |
| `ProviderConfig` | `http_timeouts::stream_timeout` | `config.read_timeout_s`/`connect_timeout_s` read at construction | ✓ WIRED | `ollama_provider.py:40`, `openai_provider.py:50` both call `stream_timeout(config)` in `__init__` |
| `llamacpp_provider.py` | `ProviderConfig` | `model_copy(update={'base_url': ...})` | ✓ WIRED | Line 26, preserves all other fields |

### Data-Flow Trace (Level 4)

Not applicable in the UI-rendering sense — this is a backend HTTP-client change, not a
data-rendering component. The equivalent trace (config value → httpx.Timeout → actual httpx call)
is covered above by the key-link table and directly proven end-to-end by the real-loopback-server
tests (`test_ollama_passes_overridden_timeout`, `test_openai_passes_overridden_timeout`,
`test_llamacpp_preserves_timeout_fields_with_no_base_url`, and the four Task-3 real-socket tests),
which assert the configured value reaches the live `httpx.stream(...)` call and produces the
expected fail-fast/succeed behavior.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Full suite green apart from documented pre-existing failure | `python -m pytest -q` | 479 passed, 6 skipped, 1 failed (`test_build_embedder_falls_back_without_torch`, pre-existing/OOS) | ✓ PASS |
| Targeted timeout suite, stable across repeated runs | `python -m pytest tests/unit/test_provider_timeouts.py -q` (x2) | 22 passed, ~7s both runs | ✓ PASS |
| Lazy-import contract intact | `python -m pytest tests/tui/test_lazy_import.py -q` | 2 passed | ✓ PASS |
| No `timeout=None` call sites remain | `grep -rn "timeout=None" src/agent86/` | Only a docstring reference in `http_timeouts.py:3` (prose, not code) and a stale `.pyc` binary match; zero live call sites | ✓ PASS |
| No new ruff errors | `ruff check .` vs worktree baseline `911c01c` | 40 errors both sides; file:line:col:code sets are byte-identical (path-prefix only difference from worktree location) | ✓ PASS |
| No new dependency | `pyproject.toml` diff / grep | diff-free vs baseline; `pytest-timeout`/`py-spy` absent | ✓ PASS |
| httpx exception hierarchy claim (disjoint siblings) | Live `httpx.__version__`/MRO check | `httpx==0.28.1`; `ConnectTimeout` MRO under `TimeoutException`←`TransportError`; `ConnectError` MRO under `NetworkError`←`TransportError`; `issubclass(ConnectError, TimeoutException) == False` | ✓ PASS |
| "Untouched by design" files really untouched | `git diff --stat 911c01c -- config_writer.py cli.py ui/repl.py tui/ tools/mcp_client.py cognitive/catalog.py types.py pyproject.toml` | Empty diff | ✓ PASS |
| Error-surfacing catch clauses present | `grep -n "except (ProviderError, HarnessError)" cli.py ui/repl.py` | All three present at documented line numbers | ✓ PASS |

### Requirements Coverage

No `.planning/REQUIREMENTS.md` entries reference `260813-jfk` (expected — this quick task carries
its own self-contained `requirements: [QUICK-260813-jfk]` tag in the PLAN frontmatter and is not
tracked in the phase-level requirements ledger). Not a gap.

### Anti-Patterns Found

None. No `TODO`/`FIXME`/`placeholder` markers, no empty handlers, no hardcoded-empty stub returns
in any of the five touched `src/` files or the new test file. The `ConnectError` clauses in both
providers are provably byte-identical to their pre-task state (diff-minimal, append-only design).

### Human Verification Required

None. This task is fully backend/HTTP-client logic with deterministic, automatable behavior
(real-loopback-socket tests already prove the wall-clock semantics that would otherwise need
manual/human timing verification).

### Gaps Summary

No gaps found. All 9 must-have truths verified against live source, all 5 required artifacts pass
existence/substance/wiring checks, all 6 key links are wired, the full suite matches the executor's
claimed counts exactly (479 passed / 6 skipped / 1 pre-existing-and-out-of-scope failure), ruff
introduces zero new errors (confirmed via worktree diff against the pre-task baseline commit), no
new dependency was added, the lazy-import contract holds, the pinned `ConnectError` message is
byte-unchanged, D-3 (Anthropic deferral) and D-4 (`mcp_client.py` out of scope) are both
comment-only / no-diff as designed, and the critical D-1 semantic (split timeout, read = max
inter-chunk gap, never a total-request deadline) is proven against a real socket with an explicit
`elapsed > read_timeout_s` assertion rather than a fake that could prove nothing.

---

_Verified: 2026-08-13_
_Verifier: Claude (gsd-verifier)_
