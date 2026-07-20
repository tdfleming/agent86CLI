# Phase 1: TUI Skeleton + Live Status Line - Research

**Researched:** 2026-07-19
**Domain:** Textual (Python full-screen TUI framework), threaded worker/UI bridging
**Confidence:** HIGH (framework APIs verified via Context7 + official docs), MEDIUM (approval-blocking mechanism — verified via docs + community discussion, no live test run against installed textual in this repo)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**UI framework**
- Use **Textual** for a full-screen app (`Agent86App(App)`). Chosen over prompt_toolkit Application and incremental Rich.
- New package: `src/agent86/tui/` — do NOT bloat `ui/repl.py`. Keep `ui/status.py` pure logic.

**App layout**
- Vertical layout: scrollable **transcript** pane (top, expands) · **prompt input** (bottom) · **footer status bar** (bottom-most).
- Transcript is a scrollable log widget (e.g. `RichLog` or a custom `VerticalScroll` of widgets) that appends streamed model text and tool-announce lines.
- Footer renders `format_status_line(StatusState)` from `ui/status.py` — reuse the existing formatter; do not reinvent it.

**The turn bridge (load-bearing)**
- `Harness.run_turn(goal, state)` is a **synchronous generator** yielding `Delta` objects. Do NOT make it async.
- Run it in a **worker thread** via Textual's `run_worker(thread=True)`.
- The worker posts Textual `Message` subclasses back to the app (e.g. `TurnDelta`, `ToolAnnounce`, `ApprovalRequest`, `TurnDone`, `TurnError`) using the thread-safe post path (`app.call_from_thread(...)` or `post_message`).
- **Reuse the existing pattern** in `ui/repl.py::_run_turn_rich` (queue drain + `threading.Event` approval blocking). Lift the reusable core into `src/agent86/tui/turn_bridge.py` so the app and (optionally) the legacy loop can share it. Do not duplicate the approval/streaming logic.

**Live status line (the headline requirement)**
- `ui/status.py::StatusState` already has `working: bool` and `phase: str` fields and `format_status_line` already renders a "working" branch — this is currently dead code. Make it live.
- Model the footer on a **reactive** `StatusState`: set `working=True` and update `phase` ("thinking", `running <tool>`) as messages arrive from the worker; Textual's event loop keeps ticking so the footer re-renders continuously during the turn.
- Update tokens/cost/ctx% from `state` per step (mirror `_Repl._refresh_status` in `ui/repl.py`).
- Derive the tool phase label the same way `ui/repl.py::_tool_label` does (`[tool] name(...)`).

**Approval modal**
- Replace the inline `input("run it? [y/N]")` with a Textual **modal screen** (`ModalScreen[bool]`). The worker thread blocks on a `threading.Event`; the modal's result sets the shared box and fires the event — same contract as `approval_cb` in `ui/repl.py::_run_turn_rich`, just rendered as a dialog.
- The approval callback is wired via `self.harness.gate.prompt = approval_cb` (existing seam).

**Slash commands**
- Port the existing dispatch (`/help /config /models /model /tools /skills /memory /mode /cost /clear /exit`) so behavior matches today. Typed commands are fine this phase; the palette is Phase 2. Reuse `_Repl.dispatch` logic where practical (consider extracting shared command handlers so both the TUI and plain loop call the same functions).

**Entry point & fallback**
- `cli.py::main` currently calls `run_repl(cfg, resume, plain)`. Route the default (rich-capable, TTY) path to the new TUI. Keep `--plain` / `AGENT86_PLAIN` / non-TTY → plain loop unchanged.
- If Textual import fails or the app can't start on this terminal, **fall back to the plain loop** with a dim note (mirror the existing `try/except` fallback in `run_repl`).
- **Lazy-import Textual** inside the TUI entry path only — never at module import time in `cli.py`, so `agent86 run` / `--plain` cold-start is unaffected.

**Scope guardrails**
- Do NOT modify the harness, cognitive loop, providers, or config schema in this phase.
- `run --json` and the plain loop must keep passing their existing tests.

### Claude's Discretion
- Exact widget choice for the transcript (`RichLog` vs custom `VerticalScroll`), reactive-vs-`set_interval` mechanism for footer refresh, exact Message subclass shapes, exact push_screen mechanism for the modal (callback vs `push_screen_wait`), test structure/tasks under `App.run_test()`.

### Deferred Ideas (OUT OF SCOPE)
- Autocompleting command palette + descriptions → Phase 2 (TUI-03).
- Arrow-key selectable menus/modals for choices → Phase 2 (TUI-04).
- Theming / color schemes → v2 (POL-01).
- Session picker UI → v2 (POL-02).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TUI-01 | Full-screen Textual app launches as default interactive UI (no subcommand), with scrollable transcript, prompt input, footer status bar | Standard Stack, Architecture Patterns (App shell, layout), Lazy-import/fallback pattern |
| TUI-02 | Status bar stays live and updates model/ctx%/tokens/cost/phase *while a turn is processing* | Architecture Patterns (reactive `StatusState` + `watch_` + `set_interval`), Code Examples (footer widget) |
| TUI-05 | Tool-approval requests appear as a modal dialog, resolving the worker thread's approval event | Architecture Patterns (Modal + `threading.Event` bridge), Common Pitfalls (deadlock avoidance) |
</phase_requirements>

## Summary

Phase 1 builds a Textual `App` shell around the harness's existing synchronous, generator-based
`run_turn`. The critical architectural fact, confirmed against current Textual docs (installed/
latest PyPI version **8.2.8**, docs fetched live via Context7 `/textualize/textual`), is that
Textual's **thread worker** model (`@work(thread=True)` or `self.run_worker(fn, thread=True)`) is
purpose-built for exactly this: a blocking synchronous callable runs off the event loop, and the
thread communicates back via two thread-safe primitives — `post_message` (safe to call directly
from any thread) and `App.call_from_thread(callback, *args, **kwargs)` (runs a sync or async
callback on the main thread and blocks the calling thread until it completes, raising
`RuntimeError` if called from the app's own thread or before the app is running).

For the approval modal, the codebase's own locked decision — reuse the exact
`threading.Event` + shared-result-box pattern already proven in `ui/repl.py::_run_turn_rich` — is
also the safest choice technically. Textual does offer `push_screen_wait()` (a coroutine, callable
only from within a worker context) as a more "Textual-native" alternative, but it introduces an
unverified constraint (it must run inside a worker's async context, and calling it via
`call_from_thread` from a *thread* worker has not been confirmed not to raise
`NoActiveWorker`). The Event-based approach has zero such ambiguity: `post_message` (thread-safe)
delivers an `ApprovalRequest` message to the app; the main-thread message handler pushes the
`ModalScreen[bool]` with a plain callback (not `push_screen_wait`); the callback sets the shared
result and calls `event.set()` (safe to call from the main thread against an `Event` the worker
thread is blocked on). This exactly mirrors the existing `_run_turn_rich` contract and requires no
new synchronization primitives to reason about.

**Primary recommendation:** Use `run_worker(self._run_turn_worker, thread=True)` for the turn,
`post_message` for all worker→app delivery, a reactive `StatusState`-backed footer `Static`
widget updated via `watch_status` + a `set_interval` heartbeat only if `working` (to catch the
"thinking…" ellipsis / elapsed-time feel — optional polish), `RichLog(markup=True, wrap=True)`
for the transcript, and the existing `threading.Event` + result-box pattern (lifted into
`src/agent86/tui/turn_bridge.py`) for the approval modal — not `push_screen_wait`.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| textual | >=1.0,<9 (pin `>=6.0` minimum; latest verified 8.2.8, 2026-07) | Full-screen TUI framework | Actively maintained, built on Rich (already a dep), the only mainstream Python full-screen terminal framework with a first-class worker/threading story |

**Version verification:** `python -m pip index versions textual` (run 2026-07-19) shows latest
release **8.2.8**. Context7 also resolves both `/websites/textual_textualize_io` (docs mirror) and
`/textualize/textual` (repo docs, versions tagged v4.0.0 / v6.6.0 in Context7's index — Context7's
tagged snapshots lag the PyPI release cadence, which is normal; treat PyPI as authoritative for
the version to pin). Recommend pinning `textual>=1.0` as a floor (very conservative — nearly any
recent 1.x+ release has thread workers, reactive, `RichLog`, `ModalScreen`, and `run_test`/`Pilot`,
all of which are stable, long-standing APIs, not new additions) and let the resolver pick current.
Do not over-pin (e.g. `==8.2.8`) — that fights the "kept light" dependency philosophy and forces
frequent bumps; a floor is enough since this phase uses only long-stable APIs.

**Installation:**
```bash
pip install "textual>=1.0"
```
Add to `pyproject.toml` `[project.dependencies]` (core, not an extra) — CONTEXT.md and PROJECT.md
both call Textual a "core-but-lazy" dependency: it ships in the base install so `pip install
agent86` gets the TUI, but the *import* is deferred to the TUI entry path only (see Lazy Import
pattern below). This differs from `anthropic`/`openai`/`mcp` which are true optional extras.

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rich | >=13.7 (already a dep) | Renderables inside `RichLog`, markup strings | Already used throughout `ui/repl.py`; Textual depends on Rich internally too so no new transitive weight |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `run_worker(thread=True)` + `post_message`/`call_from_thread` | `asyncio` + running `run_turn` via `asyncio.to_thread` manually, bypassing Textual's worker system | Textual's worker system already handles cancellation-on-screen-change, `Worker.state` events, and exception propagation via `Worker.error`; hand-rolling loses those for no benefit |
| `RichLog` for transcript | Custom `VerticalScroll` of `Static`/`Markdown` widgets, one per message | Only worth it if per-message interactivity (click-to-expand, selectable blocks) is needed later; out of scope this phase — `RichLog` is simpler and directly supports incremental `write()` |
| `threading.Event` + result-box for approval | `push_screen_wait()` from a thread worker via `call_from_thread` | `push_screen_wait` is coroutine-only and documented as callable "only from a worker" (async worker context) — calling it via `call_from_thread` from a *thread* worker is an edge case not explicitly documented/tested; the Event pattern is already proven in this exact codebase |
| Pin exact textual version | Floor-only (`>=1.0`) | Exact pin fights fast-moving upstream and the project's "kept light" philosophy; a floor keeps CI/dev current while still guaranteeing the APIs this phase needs |

## Architecture Patterns

### Recommended Project Structure
```
src/agent86/tui/
├── __init__.py         # nothing at import time beyond re-export names; NO textual import here
├── app.py              # Agent86App(App) — compose(), bindings, message handlers, lazy-imports textual inside functions/module (see Lazy Import pitfall below)
├── turn_bridge.py       # run_turn_worker(...) — the thread body; posts Message subclasses; pure w.r.t. Textual widget classes (only needs Message + a "poster" callable), reusable/testable without a running App
├── messages.py          # TurnDelta, ToolAnnounce, ApprovalRequest, TurnDone, TurnError (Message subclasses)
├── widgets/
│   ├── transcript.py    # thin wrapper/helpers around RichLog if needed
│   └── status_footer.py # StatusFooter(Static) reactive on StatusState
├── screens/
│   └── approval.py      # ApprovalModal(ModalScreen[bool])
└── commands.py           # thin adapter reusing/extracting _Repl.dispatch-equivalent handlers
```

### Pattern 1: Thread worker driving a sync generator, posting messages
**What:** The blocking `Harness.run_turn()` generator runs entirely inside a `@work(thread=True)`
method (or `self.run_worker(fn, thread=True)`); every `Delta`/approval/completion crossing back to
the UI goes through `self.post_message(...)` (thread-safe, no `call_from_thread` needed for pure
message posting).
**When to use:** Any time a synchronous, blocking, non-cancelable-by-asyncio API must drive
Textual UI state.
**Example:**
```python
# Source: https://github.com/textualize/textual/blob/main/docs/guide/workers.md (Context7, verified)
from textual.worker import get_current_worker

@work(thread=True)
def send_prompt(self, prompt: str, response: Response) -> None:
    response_content = ""
    llm_response = self.model.prompt(prompt, system=SYSTEM)
    for chunk in llm_response:
        response_content += chunk
        self.call_from_thread(response.update, response_content)
```
Adapted for agent86 (illustrative — not literal code to ship as-is; planner should design the
concrete `turn_bridge.py` shape):
```python
def run_turn_worker(harness, line, state, post, approval_cb) -> None:
    """Runs on a Textual thread worker. `post` is App.post_message (thread-safe)."""
    harness.gate.prompt = approval_cb
    try:
        for delta in harness.run_turn(line, state):
            post(TurnDelta(text=delta.text))
        post(TurnDone())
    except BaseException as exc:
        post(TurnError(exc))
```
Note: `post_message` is thread-safe and does not require `call_from_thread` — confirmed by
Context7-fetched docs ("Posting messages > Thread Safety": *"`post_message` is an exception and is
thread-safe, making it suitable for direct calls from worker threads without additional
synchronization."*). Reserve `call_from_thread` for cases that need a *return value* synchronously
from the main thread (not needed for streaming deltas, but see the approval pattern below where
the *return value* — the user's decision — is exactly what's needed, hence still using the
`threading.Event` box instead of `call_from_thread`+`push_screen_wait`).

### Pattern 2: Live footer via reactive `StatusState` + `watch_`
**What:** Wrap `StatusState` in a Textual `reactive` on a `Static`-derived footer widget (or plain
attribute + explicit `.update()` calls); every time the app processes a `TurnDelta`/`ToolAnnounce`
message on the main thread, mutate the reactive status object (or reassign a dataclass copy — see
pitfall below on reactive mutation) and call `format_status_line(status)` to re-render.
**When to use:** For UI state that must reflect frequently-changing worker-thread progress.
**Example (adapted `TimeDisplay` pattern from Context7):**
```python
# Source: https://github.com/textualize/textual/blob/main/docs/blog/posts/spinners-and-pbs-in-textual.md
from textual.reactive import reactive
from textual.widgets import Static

class StatusFooter(Static):
    status: reactive[StatusState] = reactive(StatusState(...), always_update=True)

    def watch_status(self, status: StatusState) -> None:
        self.update(format_status_line(status))
```
`always_update=True` is required because Textual's reactive change-detection is by `!=` on the
whole object by default (a dataclass mutated in place — `status.working = True` — wouldn't trigger
`__eq__`-based skip logic correctly unless you always replace the object or force update). Simplest
robust approach: **do not rely on in-place mutation** — reassign `self.status = replace(status,
working=True, phase="thinking")` (dataclasses.replace) each time, or set `always_update=True` and
mutate in place, whichever reads more clearly to the planner; both work. Because `StatusState` is a
plain (non-frozen) `@dataclass`, `always_update=True` + in-place mutation is simplest and needs no
`dataclasses.replace` boilerplate on every field. **No `set_interval` heartbeat is required** to
satisfy TUI-02 literally (the footer already re-renders every time a `TurnDelta`/`ToolAnnounce`
message updates `status.phase`, which happens continuously while tokens/tool-events stream) — a
`set_interval` is only needed for optional pure-time-based polish (e.g. an animated "…" ellipsis
with no new deltas arriving, such as during a long tool call). Recommend keeping the interval as
**discretionary polish**, not a required task, since deltas alone already satisfy the "live during
processing" requirement in the common case (see Open Questions).

### Pattern 3: Approval modal blocking the worker thread (no deadlock)
**What:** The proven, existing pattern in this codebase — a `threading.Event` plus a shared
mutable result box — reimplemented with Textual message/modal plumbing instead of
`print`/`input()`.
**When to use:** Exactly the TUI-05 approval flow.
**Example (concrete shape planner should follow):**
```python
# worker thread (inside turn_bridge.run_turn_worker):
def approval_cb(tool_name: str, preview: str) -> bool:
    event = threading.Event()
    box: dict[str, bool] = {}
    app.post_message(ApprovalRequest(tool_name, preview, event, box))  # thread-safe
    event.wait()               # blocks the WORKER thread only — UI stays responsive
    return box.get("ok", False)

# main thread, in Agent86App:
def on_approval_request(self, message: ApprovalRequest) -> None:
    def _resolve(approved: bool | None) -> None:
        message.box["ok"] = bool(approved)
        message.event.set()    # wakes the worker thread; safe from main thread
    self.push_screen(ApprovalModal(message.tool_name, message.preview), _resolve)
```
**Why not `push_screen_wait` from the thread worker:** `push_screen_wait()` is an async coroutine
documented as callable "only from a worker" — Context7-fetched docs show its own canonical example
using an **async** `@work` method (`@work async def on_mount(self): if await
self.push_screen_wait(...)`). Calling it *from a thread worker* would require
`self.app.call_from_thread(self.push_screen_wait, modal)`; `call_from_thread` does support
coroutine callbacks and blocks the calling (worker) thread until the coroutine finishes — verified
via the official API docs (`call_from_thread(callback, *args, **kwargs)` — *"accepts both
synchronous callbacks and coroutine functions"*, *"blocks until completion"*) — but whether
`push_screen_wait`'s own internal "must run inside a worker" check is satisfied when scheduled this
way (rather than by `@work` directly) is not confirmed in the docs fetched. **Recommendation:
skip this uncertainty entirely** — the `post_message` + `push_screen` (with callback) +
`threading.Event` pattern above has no such ambiguity, exactly matches `_run_turn_rich`'s existing,
tested contract, and is therefore the prescribed approach for this phase.

### Anti-Patterns to Avoid
- **Calling `self.query_one(...)`, mutating reactive attributes, or calling other App/Widget
  methods directly from the worker thread:** Textual's own docs are explicit — *"you should avoid
  calling methods on your UI directly from a threaded worker, or setting reactive variables"* —
  route everything through `post_message` (fire-and-forget) or `call_from_thread` (need a
  synchronous return value).
- **Calling `call_from_thread` from the app's own (main) thread:** raises `RuntimeError` (verified
  via official API docs) — a real risk if any "worker" code path is accidentally invoked from
  `on_mount`/an event handler instead of the actual background thread.
  Reserve `call_from_thread` for the rare case that truly needs a synchronous return from the
  worker's perspective; this phase's design avoids needing it at all (see Pattern 3).
- **Awaiting `Screen.dismiss()`'s return value from within that screen's own message handler:**
  Textual explicitly raises `ScreenError` for this (verified: `dismiss()` source comment). Not
  directly relevant to the Event-based pattern above (which never awaits `dismiss`), but relevant
  if a future phase adopts `push_screen_wait`.
- **Importing `textual` (or any of its submodules) at module level in `cli.py` or any module
  imported transitively from `cli.py`'s top level:** breaks the lazy-import/fast-startup
  constraint. See Lazy Import section below.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-thread UI updates / synchronization | Custom queue-drain polling loop (as `_run_turn_rich` currently does with `queue.Queue` + `q.get(timeout=...)`) | Textual `post_message` (thread-safe) + the app's own message-pump / event loop | Textual's message pump already does exactly this dispatch; a manual polling queue was necessary for the *prompt_toolkit* loop (no async event loop to hook into) but is redundant and adds latency/complexity inside a Textual app, which already has an event loop ticking |
| Spinner / "still working" animation during tool calls | Reimplementing `ui/spinner.py`'s carriage-return spinner inside the TUI | Reactive footer text (`status.phase`) re-rendered on each incoming message, optionally with a `set_interval`-driven ellipsis/elapsed-timer widget using the `TimeDisplay` pattern from Textual's own docs | Textual repaints declaratively; a `\r`-based spinner is a terminal-raw-mode technique that fights Textual's own screen buffer |
| Headless testing harness for TTY interaction | Custom subprocess+pty simulation | `App.run_test()` / `Pilot` (`Pilot.press`, `Pilot.click`, `Pilot.pause()`) | Built into Textual specifically for this; verified via Context7 official testing guide |

**Key insight:** Nearly everything `_run_turn_rich` currently reimplements by hand (thread-safe
delivery, "still working" indication, blocking-with-timeout polling) exists as a first-class,
tested primitive inside Textual once the UI runs on Textual's own event loop. The main piece that
*must* be preserved exactly as-is is the **approval-blocking `threading.Event` contract** — that's
inherent to bridging a synchronous generator API to any async UI and isn't something Textual
provides out of the box (Textual's own recommended pattern, `push_screen_wait`, assumes an async
caller, which `Harness.run_turn` is not, by explicit design/lock).

## Common Pitfalls

### Pitfall 1: Textual imported at module load time defeats lazy-import
**What goes wrong:** If `src/agent86/tui/__init__.py` or `src/agent86/tui/app.py` is imported (even
just to check "is Textual available") anywhere reachable from `cli.py`'s top-level imports, `agent86
run` / `--plain` cold start regresses (contradicts PROJECT.md's explicit constraint and TUI-06's
future gate).
**Why it happens:** Easy to accidentally `from agent86.tui.app import Agent86App` near the top of
`cli.py` for type-hinting or convenience.
**How to avoid:** Mirror the exact pattern already in `cli.py::main` — `from agent86.ui.repl import
run_repl` is deferred *inside* the `if ctx.invoked_subcommand is None:` branch, not at module top.
Do the same for the TUI: `cli.py` should decide (based on `_use_rich`-style TTY/plain checks) *and
then* do `try: from agent86.tui.app import run_tui except ImportError: <fallback note>; run_repl(...,
plain=True)` — the `import textual` (transitively, via `agent86.tui.app`) must not execute unless
this exact code path runs. Also keep `agent86/tui/__init__.py` empty of Textual imports so merely
having the package on the Python path doesn't trigger anything.
**Warning signs:** A cold-start timing test (already implied by TUI-06 in Phase 5, but worth a
smoke check in this phase's tests) shows `python -c "import agent86.cli"` importing `textual`;
check via `sys.modules` after import, or via `python -X importtime`.

### Pitfall 2: Reactive `StatusState` dataclass doesn't trigger `watch_` on in-place mutation
**What goes wrong:** Textual's `reactive` descriptor compares old vs new value by default (`!=`);
mutating a dataclass instance's field in place doesn't create a new object, so naive code that does
`self.status.phase = "thinking"` (without reassigning `self.status = self.status` or without
`always_update=True`) may not fire `watch_status`, and the footer silently stops updating — exactly
reproducing the "dead code" bug this phase is meant to fix, just in a new form.
**Why it happens:** `StatusState` (in `ui/status.py`) is currently a plain mutable `@dataclass`
designed for a synchronous prompt_toolkit toolbar callback (`status_line()` called fresh on every
prompt refresh) — it was never designed with Textual's reactive-descriptor semantics in mind.
**How to avoid:** Set `always_update=True` on the reactive (simplest, no dataclass changes needed),
OR reassign the whole object (`self.status = dataclasses.replace(self.status, phase="thinking")`)
on every update. Recommend `always_update=True` — least code churn, keeps `ui/status.py` unchanged
as CONTEXT.md requires ("reuse `format_status_line`... as-is").
**Warning signs:** Footer text visually "sticks" during a turn even though messages are clearly
being posted and handled (add a debug counter/log if this is suspected during implementation).

### Pitfall 3: Worker/approval deadlock if the modal's dismiss callback never fires
**What goes wrong:** If `event.set()` is not called in every code path (e.g. the modal is dismissed
via `Escape` without going through the expected button callback, or an exception is raised inside
`_resolve`), the worker thread hangs forever on `event.wait()`, freezing that turn (though the UI
itself stays responsive since only the background thread is blocked).
**Why it happens:** Modal screens can be dismissed multiple ways (button click, `Escape` binding,
programmatic `pop_screen()`) and it's easy to wire the callback to only one of them.
**How to avoid:** Route *every* dismissal path through `ModalScreen.dismiss(result)` with an
explicit `bool` (default `False`/deny on `Escape`), and ensure `push_screen`'s callback parameter
(which fires on any dismissal, regardless of route) is what sets `box["ok"]` and calls
`event.set()` — never gate `event.set()` behind a specific button's `on_button_pressed`. Also wrap
the whole worker body in `try/except BaseException`/`finally` so an exception before reaching
`event.wait()` doesn't leave the app main thread's UI in a stuck "approve?" state.
**Warning signs:** App appears to hang after dismissing an approval modal a non-standard way (e.g.
clicking outside, pressing Escape) during manual testing.

### Pitfall 4: `RichLog` write-per-token vs write-per-line semantics
**What goes wrong:** `RichLog.write()` (per official docs) is designed to write a string or Rich
renderable as an appended entry; calling it once per streamed token (`delta.text`) without managing
partial-line continuation can end up with tokens each rendered as if on a separate wrapped
line/entry rather than concatenated into one flowing line, unlike raw `sys.stdout.write` (used
today by `_emit` in `ui/repl.py`).
**Why it happens:** `RichLog` (and `Log`) are line-buffer-oriented widgets — appending is
optimized around discrete "lines," not arbitrary partial-token concatenation like a raw terminal
stream.
**How to avoid:** Accumulate the current in-flight assistant "line"/response into a string buffer
on the main thread as `TurnDelta` messages arrive, and use `RichLog.write(buffer, expand=False)`
— actually re-writing repeatedly duplicates content, so prefer instead tracking the *last written
line's* content and using the pattern from the "Send Prompt and Stream" Context7 example: update a
single `Response`-like widget's content (`response.update(response_content)` in that example uses
`Static`/`Markdown`.update, not `RichLog`). **Concrete recommendation for the planner:** consider
whether the transcript uses `RichLog` purely for completed lines/entries (tool announces, turn
separators) while the *currently streaming* assistant response renders into a separate
always-at-bottom `Static`/`Markdown` widget that gets replaced wholesale on each delta (cheap,
since text sizes here are small), then on `TurnDone` that content is appended as a final entry into
the `RichLog`/scrollback and the streaming widget is cleared for the next turn. This exactly
mirrors the Context7-verified `send_prompt`/`Response.update` chat-UI pattern, which is the
closest verified precedent to agent86's "prefix_shown"/token-by-token accumulation logic in
`_run_turn_rich`. Flag as **Open Question** for the planner to finalize the concrete widget split
(see below) — both approaches are viable and this is Claude's Discretion per CONTEXT.md.

## Code Examples

### Thread worker + message posting (verified pattern)
```python
# Source: Context7 /textualize/textual — docs/guide/workers.md
from textual.worker import get_current_worker

@work(thread=True)
def update_weather(self) -> None:
    worker = get_current_worker()
    if worker.is_cancelled():
        return
    # ... blocking synchronous work ...
    self.call_from_thread(self.update_ui, data)   # only needed when you must run ON the main
                                                     # thread synchronously; post_message suffices
                                                     # for fire-and-forget delivery like TurnDelta
```

### Reactive + watch_ (verified pattern, adapted)
```python
# Source: Context7 /textualize/textual — docs/blog/posts/spinners-and-pbs-in-textual.md
from textual.reactive import reactive
from textual.widgets import Static

class TimeDisplay(Static):
    time = reactive(0.0)

    def on_mount(self) -> None:
        self.update_timer = self.set_interval(1 / 60, self.update_time, pause=True)

    def watch_time(self, time: float) -> None:
        self.update(f"{time:.2f}")
```

### Modal screen + push_screen with callback (verified base pattern, adapted for bool result)
```python
# Source: Context7 /textualize/textual — docs/guide/screens.md
from textual.screen import ModalScreen
from textual.widgets import Button, Label
from textual.containers import Container

class ApprovalModal(ModalScreen[bool]):
    def __init__(self, tool_name: str, preview: str) -> None:
        super().__init__()
        self.tool_name, self.preview = tool_name, preview

    def compose(self):
        yield Container(
            Label(f"approve {self.tool_name}? {self.preview}"),
            Button("Run it", id="approve", variant="warning"),
            Button("Deny", id="deny"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve")

    def on_key(self, event) -> None:  # Escape -> deny, not left hanging
        if event.key == "escape":
            self.dismiss(False)

# in Agent86App:
def on_approval_request(self, message: ApprovalRequest) -> None:
    def _resolve(approved: bool | None) -> None:
        message.box["ok"] = bool(approved)
        message.event.set()
    self.push_screen(ApprovalModal(message.tool_name, message.preview), _resolve)
```

### Headless test skeleton (verified pattern)
```python
# Source: Context7 /textualize/textual — docs/guide/testing.md
import pytest

async def test_app_launches():
    app = Agent86App(harness=fake_harness)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#transcript") is not None
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| prompt_toolkit `PromptSession` + manual `queue.Queue` polling loop for streaming/approval (`ui/repl.py::_run_turn_rich`) | Textual `App` + thread worker + `post_message`/message-pump dispatch | This phase (v0.6 milestone) | Removes the hand-rolled polling loop and spinner-vs-cursor bookkeeping (`at_line_start`, `prefix_shown` flags) in favor of Textual's built-in message pump and reactive re-render; those flags/patterns are *not* needed in the TUI (though the underlying `_tool_label`/status-refresh *logic* is reused) |

**Deprecated/outdated:** Nothing in Textual itself is deprecated for this use case — thread
workers, `reactive`, `ModalScreen`, `RichLog`/`Log`, and `run_test`/`Pilot` are all long-stable,
core, actively-documented APIs as of the 8.2.8 release verified today.

## Open Questions

1. **`RichLog` vs split "streaming widget + finalized log" for the transcript**
   - What we know: `RichLog.write()` appends discrete entries; a chat-style Context7-verified
     example (`send_prompt`) streams into a single `Static`/`Markdown` widget via repeated
     `.update()`, not `RichLog`.
   - What's unclear: Whether agent86's transcript (which also needs scrollback across many turns,
     tool-announce lines interleaved with streamed text, and Rich markup like
     `[bold cyan]agent86[/bold cyan]`) is better served by `RichLog` alone (accepting that a
     streaming response is written incrementally as repeated `write()` calls forming one wrapped
     block) or by the split approach above.
   - Recommendation: Planner/implementer should prototype both quickly in Wave 0; given CONTEXT.md
     explicitly allows `RichLog` *or* a custom scroll container and marks widget choice as Claude's
     Discretion, this is not blocking — but the plan should include an explicit task to verify
     `RichLog.write()`'s exact behavior for repeated partial-text appends (no confirmed Context7
     example of this specific usage) before committing to it, OR default to the split-widget
     approach which *is* directly verified against a real chat-streaming example.

2. **`push_screen_wait` from a thread worker — genuinely unsupported, or just undocumented?**
   - What we know: `push_screen_wait` is documented as async, callable "only from a worker" (its
     own canonical example uses `@work async def`); `call_from_thread` explicitly supports
     coroutine callbacks and blocks the calling thread.
   - What's unclear: Whether `push_screen_wait`'s internal worker-context check
     (likely `get_current_worker()`/a context-var check) is satisfied when the coroutine is
     scheduled onto the event loop via `call_from_thread` from a *thread* worker rather than being
     itself decorated with `@work`.
   - Recommendation: **Moot for this phase** — the plan should use the `threading.Event` +
     `post_message` + `push_screen(callback=...)` pattern (Pattern 3 above), which sidesteps this
     question entirely and is already proven in this exact codebase. Revisit only if a future
     phase wants to simplify further.

3. **Is a `set_interval` heartbeat needed for TUI-02, or do delta-driven updates suffice?**
   - What we know: `format_status_line` already renders `"{model} · {phase}…"` whenever
     `state.working` is true; every `TurnDelta`/`ToolAnnounce` message naturally re-renders this on
     the main thread as it's processed.
   - What's unclear: Whether the success criteria ("updates ... *while a turn is processing*")
     implicitly expects visible motion even during long silent gaps (e.g. a slow local-model
     token-by-token stall, or a long-running tool with no intermediate output) — in which case a
     `set_interval`-driven "…"-animation or elapsed-time counter would visibly satisfy "live" even
     with zero new deltas.
   - Recommendation: Treat the `set_interval` heartbeat as optional polish (nice differentiator
     from the current dead "working" branch, cheap to add given the `TimeDisplay` pattern is
     directly verified) rather than a hard requirement; the plan can include it as a low-priority
     task without blocking phase completion criteria.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.2+ with `pytest-asyncio` (already dev deps in `pyproject.toml`), plus Textual's own `App.run_test()`/`Pilot` (ships with `textual`, no extra test dep) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `asyncio_mode = "auto"` already set, which is what Textual's async `run_test()` tests need |
| Quick run command | `pytest tests/tui/ -x -q` |
| Full suite command | `pytest -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TUI-01 | App launches with transcript/input/footer widgets present, in a headless run | integration (Pilot) | `pytest tests/tui/test_app_shell.py -x` | ❌ Wave 0 |
| TUI-01 | `--plain`/non-TTY still routes to plain loop unchanged | unit (existing) | `pytest tests/unit/test_repl*.py -x` (verify no regression) | ✅ existing (confirm path/name during planning) |
| TUI-02 | Footer text reflects `status.working`/`phase` while a fake/stub turn streams deltas | unit (widget-level, no full App needed) or integration (Pilot posting fake `TurnDelta` messages) | `pytest tests/tui/test_status_footer.py -x` | ❌ Wave 0 |
| TUI-02 | `format_status_line`'s working-branch output is unchanged (regression guard on existing pure function) | unit | `pytest tests/unit/test_status.py -x` (extend existing file if present) | Check: `tests/unit/` for existing `ui/status.py` coverage |
| TUI-05 | Approval modal dismissal (approve / deny / escape) correctly sets the worker's `threading.Event`/result box, in all three dismissal paths (Pitfall 3) | integration (Pilot simulating key/button presses against a stubbed worker+Event) | `pytest tests/tui/test_approval_modal.py -x` | ❌ Wave 0 |
| TUI-05 | `run --json` and plain-loop approval prompt (`input("run it? [y/N]")`) still work unchanged | unit (existing) | `pytest tests/unit/ -k repl or approval -x` | ✅ existing (confirm exact file names during planning) |
| (cross-cutting) | Textual is not imported at `agent86.cli` module import time | unit (Pitfall 1 guard) | a small `pytest` test asserting `"textual" not in sys.modules` immediately after `importlib.import_module("agent86.cli")` in an isolated subprocess/fresh interpreter | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/tui/ -x -q` (fast, headless, no real model calls — turn_bridge
  tests should use a stub `Harness`/fake generator, matching the existing test-fixture style
  implied by `tests/support.py` and `tests/unit/`).
- **Per wave merge:** `pytest -x -q` (full suite, including existing `run`/`--plain`/`--json`
  regression tests).
- **Phase gate:** Full suite green before `/gsd:verify-work`, plus a manual smoke test in a real
  Windows Terminal session (Pilot/headless tests cannot fully substitute for confirming the app
  actually paints correctly on the target platform — CONTEXT.md explicitly calls out "test the TUI
  in the native Windows terminal early").

### Wave 0 Gaps
- [ ] `tests/tui/__init__.py` + `tests/tui/conftest.py` — new test package; likely needs a fixture
      building a stub `Harness` (fake `run_turn` generator, fake `gate`) so tests don't need real
      provider credentials, mirroring how `tests/unit/` presumably stubs the harness today (check
      `tests/support.py` and `tests/conftest.py` during planning for the existing stub-harness
      pattern to reuse rather than reinvent).
- [ ] `tests/tui/test_app_shell.py` — covers TUI-01 (widgets present on launch)
- [ ] `tests/tui/test_status_footer.py` — covers TUI-02 (live status during processing)
- [ ] `tests/tui/test_approval_modal.py` — covers TUI-05 (modal resolves the worker's Event on all
      dismissal paths)
- [ ] Confirm/extend an existing `tests/unit/test_status.py`-equivalent for `ui/status.py`'s
      working-branch formatting (pure-function regression guard, independent of Textual)
- [ ] No new framework install needed beyond adding `textual` to `pyproject.toml` core deps (`pip
      install -e .[dev]` picks it up automatically once added; `Pilot`/`run_test()` ship with the
      `textual` package itself, no separate test-support package required)

## Sources

### Primary (HIGH confidence)
- Context7 `/textualize/textual` — `docs/guide/workers.md` (thread workers, `call_from_thread`,
  `post_message` thread-safety), `docs/guide/reactivity.md` + `docs/blog/posts/spinners-and-pbs-in-textual.md`
  (`reactive` + `watch_` + `set_interval` pattern), `docs/guide/screens.md` (`ModalScreen`,
  `push_screen`, `push_screen_wait`, `dismiss()` semantics), `docs/widgets/rich_log.md` +
  `docs/widgets/log.md` (`RichLog` vs `Log`), `docs/guide/testing.md` (`run_test()`/`Pilot`),
  `docs/blog/posts/anatomy-of-a-textual-user-interface.md` (verified chat-streaming
  `@work(thread=True)` + `call_from_thread` example)
- `https://textual.textualize.io/api/app/` (WebFetch, official docs) — `App.call_from_thread`
  exact signature, blocking behavior, `RuntimeError` conditions
- `https://textual.textualize.io/guide/screens/#waiting-for-screens` (WebFetch, official docs) —
  `push_screen_wait` canonical async example and "only from a worker" constraint
- PyPI (`pip index versions textual`, run 2026-07-19) — confirms latest release **8.2.8**

### Secondary (MEDIUM confidence)
- WebSearch: "textual call_from_thread push_screen_wait from worker thread modal approval" —
  cross-referenced Textual's own GitHub Discussions (#2559, #6209, #6227) confirming the general
  shape of the thread-worker + `call_from_thread` pattern for UI updates and the worker-context
  requirement of `push_screen_wait`, but did not surface a definitive answer to Open Question 2
  above (hence the recommendation to sidestep it).
- WebSearch: Textual-on-Windows compatibility — multiple 2025-dated blog/community sources agree
  Textual targets modern terminals (Windows Terminal, iTerm2, kitty) and has known issues on
  legacy `cmd.exe`; agent86 already reconfigures stdout/stderr to UTF-8 in `cli.py`, which
  addresses the encoding half of Windows terminal issues but not raw-mode/ANSI capability — the
  existing constraint ("must also work on macOS/Linux", "test the TUI in the native Windows
  terminal early") already anticipates this; no code-level mitigation is knowable from docs alone
  beyond "test on Windows Terminal specifically, not legacy Console Host."

### Tertiary (LOW confidence)
- None used as load-bearing claims; all WebSearch findings above were cross-checked against
  Context7/official docs before being included.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — version and core API surface (`run_worker`, `reactive`, `ModalScreen`,
  `RichLog`, `run_test`) verified directly against Context7-fetched current docs and PyPI.
- Architecture: HIGH for the thread-worker/message-posting/reactive-footer patterns (directly
  matches verified docs); MEDIUM for the exact approval-modal wiring specifics only insofar as it
  deliberately avoids the one genuinely under-documented API (`push_screen_wait` from a thread
  worker) in favor of a pattern already proven in this codebase.
- Pitfalls: MEDIUM-HIGH — Pitfalls 1-3 verified against official docs/source; Pitfall 4 (RichLog
  per-token append behavior) is a reasoned inference from documented `RichLog`/chat-streaming
  examples rather than a directly-quoted "don't do this" warning, hence flagged as an Open Question
  rather than asserted as fact.

**Research date:** 2026-07-19
**Valid until:** ~30 days (Textual ships frequent minor releases, but the core APIs researched here
— thread workers, reactive, ModalScreen, RichLog, run_test — are long-stable and unlikely to break;
re-verify the pinned version floor if planning is delayed significantly past this window).
</content>
