---
phase: 09-release
subsystem: observability/packaging/cli/orchestration/memory/ci
tags: [trace-redaction, trace-rotation, otel-exporter, trace-export, pypi, trusted-publishing, packaging-tests, scripting-contract, error-messages, degradation-matrix]
requirements: [OBS-01, OBS-02, OBS-03, OBS-04, PKG-01, PKG-02, HARD-01, HARD-02, HARD-03]
status: complete
completed: 2026-09-21
---

# Phase 9 — Release

**Goal:** ship it. After v0.9 the harness was complete against `docs/ARCHITECTURE.md` except for
three rows in that document's own §15 "described above, deliberately not built" table, and those
three rows were the whole of v1.0: OpenTelemetry spans were emitted into the **no-op global
provider**, so with the extra installed and the switch on they were created and dropped on the
floor; the flight recorder — the one file that sees *everything* the harness sees — was
append-only, unbounded and unredacted, which made the most useful artifact for a bug report the
one artifact nobody could safely share; and there was no distribution at all, so "install agent86"
meant "clone this repository". Alongside them, the contract a script depends on (`run`,
`run --json`, `--plain`) was something a reader inferred from the code rather than something tests
stated.

**Requirements:** OBS-01 (trace redaction), OBS-02 (trace rotation), OBS-03 (OTel exporter),
OBS-04 (trace export and filters), PKG-01 (PyPI metadata and packaging tests), PKG-02 (release
workflow), HARD-01 (scripting contract), HARD-02 (error messages), HARD-03 (degradation matrix).

Like Phases 5–8, this phase was executed as a review-driven pass rather than a numbered plan set:
every item was a candidate recorded at the close of v0.9 in `PROJECT.md` § "Next milestone
candidates" and `docs/BACKLOG.md` §§ "Observability" and "Release". Nothing here changes the
scripting contract — it is the phase that *pins* it. Work is grouped below by workstream; commits
are listed oldest-first within each group.

---

## Workstream 1 — Observability (OBS-01…OBS-04)

**The recorder was the problem and the solution at once.** Everything the harness sees flows
through it: the user's task text, the model's tool arguments, whatever a tool read off disk. That
is exactly why it is the first thing to reach for when something goes wrong, and exactly why it
could not be shared — a key pasted into a prompt, or a `.env` a tool happened to `cat`, landed in
plain text in a file that outlives the session. Everything below follows from treating the trace
as an artifact that will be *handed to someone else*.

**Redaction, as one gate** (`281403e`). `observability/redact.redact_event` sits between every
event and the file. Every string, at any depth, is rewritten with the **same regexes the guardrail
tier already uses** — `guardrails/scanners.py` for provider key shapes and credential
assignments, `secrets.py` for the key-shaped-token catch-all. They are *imported*, never
re-spelled: two copies of a secret regex is one copy that will be forgotten when a provider
invents a new prefix. A match becomes `***REDACTED***`, chosen to be unmistakable when grepping a
trace. Size is a separate axis: the big free-text fields (`arguments`, `task`, `content`, `error`,
`outcome`) are clipped to `[observability] max_field_chars` with a visible
`…[truncated N chars]`, and truncation is **inherited** — once inside `arguments`, every nested
string is a candidate, because the model chooses those key names and the harness cannot enumerate
them. The function never raises: a value that cannot be walked or serialised falls back to
`str()`, and a redaction failure degrades to the *untouched* event, on the judgement that a trace
which silently drops events is worse than a trace with one long line in it. The imports of the
scanner internals go through `getattr` and are guarded, because those are private names in modules
this file does not own, and an observability import must never be the thing that breaks the
harness. `redact = "none"` is an explicit, local opt-out rather than the default.

**Rotation, between events** (`b3b5217`). The live file is capped at `max_trace_bytes` (50 MB);
crossing it shifts `trace.jsonl` → `trace.1.jsonl` … `trace.N.jsonl` and drops the oldest
generation past `keep_traces` (5). The ordering is load-bearing: rotation happens *between*
events — flush, then rename — so no event is ever half-written across a boundary. The rename
retries briefly, because on Windows `os.replace` fails with `PermissionError` while any other
process (a `tail`, an editor, an antivirus scanner) holds the file open; giving up after the
retries is safe rather than fatal, since the writer just keeps appending to the current file and
tries again at the next crossing. Reading back was rewritten at the same time, and for the same
reason a capped file needs it: `read_events` streams and keeps at most `limit` records in memory,
and `trace_generations` walks the rotated files newest-first when the tail of the live file does
not hold enough **matching** events. That is what makes `trace show --kind tool_call -n 50` show
fifty tool calls rather than whatever few survive the last fifty events of any kind.

**A provider of our own** (`17c1e80`). The tracer only ever called `trace.get_tracer`, which
returns a handle on the no-op global provider unless something else in the process has already
installed one — so `otel = true` plus the extra produced spans that went nowhere, silently, which
is the worst shape a telemetry bug can take. `Tracer` now builds its own `TracerProvider`: a
`Resource` carrying `service.name = "agent86"` and `service.version`, an exporter chosen by
`[observability] otel_exporter` (`otlp` over gRPC, falling back to HTTP when only the HTTP
exporter is installed; `console` to stderr; `none`), and a `BatchSpanProcessor` flushed by
`Tracer.close()` from `Harness.close()`. The standard `OTEL_EXPORTER_OTLP_ENDPOINT` and
`OTEL_EXPORTER_OTLP_HEADERS` are honoured — the exporters read them themselves, which is how every
other instrumented process on a machine is configured — with `otel_endpoint` as the override for
when config, not environment, is the source of truth.

The decision worth recording is what the tracer does *not* do: it never calls
`set_tracer_provider`. agent86 is importable inside a host that owns its own tracing, and taking
over the global provider would make that a side effect of an import. The cost is that spans only
flow through the handle the harness holds, which is all the harness emits anyway. Every failure
path is swallowed onto `Tracer.note` — a missing extra, a missing collector, a broken exporter —
so the degradation is "no traces" with a one-line reason a surface can print, never "no agent";
and nothing in the module imports `opentelemetry` at module scope, so `agent86 run` pays nothing.
The span tree is `turn` (`session.id`, `gen_ai.request.model`) → `model_call` (`gen_ai.system`,
usage tokens, finish reasons) / `tool_call` (`tool.name`, `gen_ai.tool.name`): GenAI semantic
conventions where a name exists, `agent86.*` where one does not.

**Reading and exporting** (`8cd5013`). `trace show` gained `-k/--kind` (repeatable) and
`--since 30m|2h|7d`, plus `in` / `out` / `cost` columns filled only on a `model_call` — the only
event where they mean anything — and a totals line under the table. `trace export` is new:
`-s/--session`, `-n/--limit`, `--since`, `-o/--out`, and `-f/--format` over `jsonl` (the filtered
events), `json` (one array) and **`otlp-json`**, which reconstructs a span tree from the
recorder's own `turn_start` / `turn_end` / `model_call` / `tool_call` events — so a trace captured
on a laptop with no collector running can still be handed to one afterwards. Span ids are
*derived* rather than random, so exporting the same trace twice produces identical output and
re-exporting is idempotent. Both commands go through one reader (`_read_trace`) that applies the
filters **before** the limit; the alternative — tail N, then filter — is what makes a filtered
`-n` a lie. Everything the recorder writes that is not span-shaped (guardrail hits, compactions,
routing decisions) stays in the JSONL views, where it is greppable.

**`1e5f972`** annotates the recorder's file handle so `mypy` stops inferring its type from the
first assignment and rejecting the rotation path.

---

## Workstream 2 — Packaging (PKG-01, PKG-02)

**`2ee8700` — metadata that is true.** Full PyPI classifiers (audience, OS, Python 3.11/3.12/3.13,
topics, `Typing :: Typed`), keywords, an explicit `license`, and the `[project.urls]` block. The
**MIT `LICENSE` file** the metadata had claimed all along was added here — a license named in
metadata and absent from the tree is the kind of thing nobody notices until a packager does. The
sdist became an allowlist (source, `README.md`, `CHANGELOG.md`, `LICENSE`,
`docs/ARCHITECTURE.md`) and development scaffolding — `.github`, `.planning`, `.claude`, `tests`,
caches — is excluded from both artifacts. `build` and `twine` joined the `dev` extra, because the
release path must be runnable from a dev install.

**`753a63f` — assert the artifact, not the tree.** The packaging tests build a *real* sdist and
wheel with `python -m build` and install the wheel into a throwaway virtualenv, then assert
against that: the wheel's contents and metadata, the version equality between `pyproject.toml` and
`agent86.__version__`, the `agent86` console entry point actually running, and the lazy-import
contract holding in an installed copy. Testing the source tree would prove nothing about what a
user receives. That costs roughly 25s on a warm cache, which is far too slow for the default run,
so everything in `tests/packaging/` carries a `packaging` marker and `pyproject.toml` sets
`addopts = "-m 'not packaging'"`; a command-line `-m` is appended *after* `addopts` and therefore
wins, which is how CI and the release workflow opt in.

**`e10dc51` — one version, checked once per release.** `scripts/check_release.py` verifies, in
order, that the git tag, `project.version` and `agent86.__version__` all name the same version;
that `CHANGELOG.md` has a `## [<version>]` section with a body; that `## [Unreleased]` is empty;
and that `README.md`, `LICENSE` and `docs/ARCHITECTURE.md` exist. Every check runs even after one
fails, so one run shows every problem. The version stays a **literal** in `__init__.py` rather
than being derived from `importlib.metadata`: that is a real import on the cold-start path, which
is an explicit constraint of this project, and `version()` raises `PackageNotFoundError` when the
package is on `sys.path` but not installed — a source checkout, a vendored copy, a zipapp — which
turns `--version` into a crash exactly where it is least expected. The duplication is real; this
script is where it is caught.

**`76aeeec` — a tag is the whole ritual.** `.github/workflows/release.yml` on `push` of `v*`:
pre-flight first and fail-fast, `uv build`, `twine check dist/*`, the packaging tests against the
freshly built artifacts, then **trusted publishing** to PyPI through the `pypi` GitHub environment
(OIDC — no API token is stored in this repository), then a GitHub Release whose body is that
version's CHANGELOG section, extracted by `scripts/changelog_section.py`, which shares its parser
with the pre-flight so the check and the extraction cannot disagree. `workflow_dispatch` runs the
same pipeline against **TestPyPI** with `skip-existing`, so the publish path can be rehearsed —
worth having, because a filename on PyPI can never be reused, so a version number is spent the
first time it is tried. The publish jobs are separate from `build` so that `id-token: write` and
the environment are scoped away from the job that runs test code, and concurrency is grouped per
ref but **not** cancel-in-progress: a publish that has started must not be interrupted half-way.
The same pre-flight and build run in CI's `package` job on Ubuntu *and* Windows on every push,
which catches version/CHANGELOG drift long before anyone tags.

---

## Workstream 3 — Hardening (HARD-01…HARD-03)

**`ec9fff3` — say what the contract is.** `tests/integration/test_scripting_contract.py` states
everything a script or a CI job may depend on: `run --json` writes **one** object with the keys
`session_id`, `output`, `steps`, `usage`, `turn` (additive — new keys may appear, these five may
not be removed or renamed); the egress guardrail applies to that JSON as much as to streamed text,
so a `redact` config cannot leak a key through the machine-readable path; a provider failure is
exit 1 with the message on **stderr** and nothing on stdout, so `run … > out.json` never leaves a
half-file that parses as success; piped and without `--yes`, side-effecting tools are declined;
`--session` continues rather than starting fresh; `--plain` never imports Textual; and the
read-only inspection commands work with no config and no keys. No network: the provider is faked
at the router seam (`provider_for_model`), the one place every path — `Harness.__init__`,
`set_model`, per-turn routing — goes through.

**`c3af5e8` — start on a machine that has nothing.** Every command surface is run in a *real*
subprocess (`python -m agent86`) under a temp HOME with no config file and no API keys — the state
a first-time user or a CI runner is actually in — with a deliberately absolute bar: exit 0, no
traceback. A CLI that crashes before it can tell you what is missing is the worst possible first
impression, and it is invisible to in-process tests, which share the developer's environment. The
cold-start guard lives here rather than in `tests/tui` because it is a property of the *scripting*
path: `run` and `--plain` must not pay for `textual`, `keyring`, `tomlkit`, `opentelemetry` or
`torch`. The import-graph half is deterministic and always runs; `AGENT86_SKIP_PERF=1` skips only
the wall-clock half, for a slow or loaded runner.

**`f91077e` — every error names a fix.** An audit of the user-facing failure paths found three
that reached the user as a Rich traceback rather than a sentence, and several that named a symptom
without a fix. A malformed `--model` ref fails in `ModelRef.parse` with a `ValueError` *before any
provider exists*, so `run` and `run_repl` now catch it alongside `ProviderError`. A config file
that does not parse broke **every** command — including the `config path` one would run to find
the file — and is now a message naming the file. A memory database that will not open (locked by a
second agent86, an unwritable home) raised a bare `sqlite3` error several frames deep;
`MemoryStoreError` names the file and offers all three fixes, and the harness **degrades to no
memory with a visible note** instead of refusing to start. Every model failure carries the same
shared next step (`agent86 models`, then `--model provider:model`), and memory-disabled /
no-MCP-servers / unknown-skill each name the config key or command that changes them.
Missing-key messages continue to name the environment **variable** and never its value, with a
test holding `agent86 models` to that.

**`327a936` — and the `trace` sub-app with them.** The audit gave every command the `_load()`
wrapper, but `trace path`, `trace show` and `trace export` still called `load_config()` directly,
so a malformed config reached the user as a traceback from exactly the commands they would reach
for while diagnosing one. Three lines; the point is that "every command" has to be checked
command by command, because the wrapper is opt-in by call site.

**`816737e` — title the session after what you typed.** `@file` mentions are expanded before the
turn runs, so a prompt whose body was an inlined file named the session after 60 characters of
that file's contents. `run_turn` gained a keyword-only `display_text`: the model still gets the
expanded text, while the session title and the trace's `turn_start` get the line the user actually
typed. It defaults to the expanded text, so no existing caller changed.

**`12fe2bd` — degradation as a matrix.** One integration test per optional dependency — `mcp`,
`keyring`, `sentence-transformers`, Docker, `opentelemetry`, `beautifulsoup4`, PyYAML — each
hiding it by poisoning `sys.modules` for the parent package **and** any already-imported submodule
(so a cached `opentelemetry.sdk.trace` cannot sneak the import back in), building a real `Harness`
around a fake provider in a temp workspace, and running one turn. Docker is the exception, because
nothing imports a `docker` module — availability is the executable — so its absence is simulated
where the code actually looks. The rule asserted is the same every time: the feature degrades, the
harness says so in a one-line note, and the turn goes through. Nothing raises, and nothing is
silently skipped.

---

## What this phase closed, and what it opened

`docs/ARCHITECTURE.md` §15 lost its last three contract rows (OTel exporter, trace redaction,
trace rotation); what remains in that table is either an explicit non-goal, an alternative
implementation of something that already works, or an evaluation not yet written. There is no
next milestone scoped.

Opened, and recorded in `docs/BACKLOG.md`:

- **The `Development Status` classifier flip.** `pyproject.toml` still declares `4 - Beta`, on
  purpose: the classifier is a claim about a *published* artifact, and nothing is published at the
  moment a tag is cut. It becomes `5 - Production/Stable` in the first release after 1.0 is live
  on PyPI.
- **Compaction is still invisible in the trace UI.** The `compaction` event and the archived
  originals exist; `trace show` has no view of *what* was summarized. Carried from v0.8, and now
  the only §9-area row left in the architecture's not-built table.
