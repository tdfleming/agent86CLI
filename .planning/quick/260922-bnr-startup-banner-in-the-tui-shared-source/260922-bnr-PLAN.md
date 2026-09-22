# Quick Task 260922-bnr — Startup banner in the TUI, from one shared definition

**Created:** 2026-09-22
**Type:** Branding / UX, two surfaces
**Files:** `src/agent86/ui/repl.py`, `src/agent86/tui/app.py`, `src/agent86/tui/commands.py`,
`src/agent86/tui/widgets/status_footer.py` (docstring), plus tests
**Precedes:** § 999.0a in `docs/BACKLOG.md`. Not a backlog phase — a quick task taken ahead of the
post-1.0 backlog at the user's request (2026-09-22).

## Problem

Raised as "unlike other CLIs there is no splash screen that shows the name". The investigation
found the opposite of a missing feature: **the splash exists and is on the wrong surface.**

`ui/repl.py:46` `_banner(cfg)` returns a bordered Rich `Panel` titled "agentic harness" showing
`agent86 v<version>`, model, router, sandbox, approval and a `/help` hint. It is printed at
`repl.py:459` — **plain path only**, and the comment above it says why: it renders before Textual
takes the screen, so under the alternate screen it would be painted onto the normal screen and
only flash past on quit. The TUI therefore renders `startup_notes` into its transcript
(`app.py:235`) and carries no identity at all.

So the default interactive surface is the unbranded one and the fallback surface carries the
brand. The fix has the same shape as the per-turn cost line and the approval diff: **one
definition, rendered by both surfaces, so they cannot drift.**

## Decisions (user, 2026-09-22)

| Question | Ruling |
|---|---|
| Form | Keep the bordered Rich `Panel`. No ASCII wordmark, no `Header` widget. |
| Surfaces | TUI **and** plain, from one shared source. `run` / `run --json` stay silent. |
| Persistence | Transcript content, **reprinted on `/clear`**. |
| Payload | Name, version, **model**. Not the full four-line panel. |
| Plain-loop parity (Fork 1) | `banner(cfg, *, compact)` — shared identity core for both; the plain loop passes `compact=False` to append its extra rows. |
| `/clear` (Fork 2) | **Yes** — `/clear` wipes the TUI transcript as well as resetting the session, then reprints the banner. |

Fork 1 exists because the trim is only free on one surface: the TUI's `StatusFooter` reports
sandbox and approval live, so dropping them from its splash costs nothing, while the plain loop
has **no status surface at all** (see task 4) — that banner is the only place a `--plain` user ever
sees `sandbox subprocess` / `approval ask`. One function with a `compact` flag keeps a single
definition without regressing plain.

## Tasks

### 1. `ui/repl.py` — one public `banner()`

- Rename `_banner` → **`banner(cfg, *, compact: bool = True)`** and export it.
- **Identity core (both surfaces):** `agent86 v<version>` and `model <ref>`. Keep the `Panel`,
  the "agentic harness" title, the cyan border and `expand=False`.
- **`compact=False` appends** router, sandbox, approval and the `Type /help …` hint — the rows the
  plain loop must keep.
- Stays textual-free and Rich-only. `Panel` is a core dependency, so the import graph does not
  move; the cold-start and import-graph tests must still pass untouched.
- Update the call site at `repl.py:459` to `console.print(banner(cfg, compact=False))`.

### 2. `tui/app.py` — the banner is a transcript **entry**, not a `log.write()`

- In `on_mount`, prepend `RawEntry(banner(cfg))` to `self._entries` **before** the `startup_notes`
  loop at `app.py:235`. `RawEntry(renderable: Any)` renders as given
  (`tui/widgets/transcript.py:123`), so the `Panel` needs no new entry type.
- **This is the catch:** `_rerender()` (`app.py:279`) clears the log and replays `self._entries`,
  and it fires on a theme change and on every tool-block expand/collapse. A banner written
  directly with `log.write()` would silently vanish the first time the user pressed `Ctrl+O`. As an
  entry it survives by construction.
- **Third call site:** the resume path (`app.py:457` sets `self._entries = []`, then extends from
  `_entries_for(state)`) must re-prepend the banner, or resuming a session loses it.

### 3. `/clear` — wipe the transcript, reprint the banner

- Today `_clear_session` (`tui/commands.py:271`) only does
  `repl.state = repl.harness.new_session()`. The TUI keeps the old exchange on screen, so after
  `/clear` the transcript shows history the model no longer has. Fork 2 fixes that as part of
  making the reprint meaningful.
- Keep the **state** reset in `commands.py` — the registry is shared and the plain loop has no
  transcript to wipe, so its `/clear` keeps printing "conversation cleared" and nothing else.
- Put the **transcript** wipe in the TUI's command-result handling (the `"handled"` / `"noop"`
  branch around `app.py:558`): `self._entries = [RawEntry(banner(cfg))]`, then `_rerender()`.
- **Signal it structurally, not by name.** Add a flag to `CommandResult` (e.g. `clears_transcript`)
  rather than having the app special-case the string `/clear` — matching on a command name is
  exactly the coupling that drifts.

### 4. `tui/widgets/status_footer.py:18` — correct a stale docstring

It says "The plain loop keeps rendering the whole line (`format_status_line`) — it has no widget".
`_Repl.status_line` (`repl.py:244`) has **no call site in the plain path**; `format_status_line` is
consumed only by `StatusFooter`. Correct the comment here. Giving the plain loop the live status
line it was documented as having is a *separate* change and is out of scope — but it is the reason
Fork 1 went the way it did, so record the pointer.

### 5. Tests

- **The drift test — the point of the whole task.** Assert both surfaces render the same identity
  core from one call: the TUI's first transcript entry and the plain loop's banner agree on name,
  version and model.
- TUI: the banner survives `_rerender()` — expand a tool block, assert it is still entry 0.
- TUI: after `/clear`, `_entries` is exactly `[banner]`.
- TUI: resuming a session re-prepends the banner.
- Plain: `compact=False` contains sandbox and approval; `compact=True` does not.
- **Contract:** `run` and `run --json` emit no banner — stdout stays exactly one JSON object.
  `tests/integration/test_scripting_contract.py` pins the JSON purity already; add the explicit
  no-banner assertion for both.
- Import graph / cold start: unchanged, and still asserted.

### 6. Decide the non-TTY plain case

A non-TTY stdin forces plain mode, so `echo "hi" | agent86` prints the `Panel` to **stdout** ahead
of the answer. This sits outside the pinned scripting contract (which covers `run` / `run --json`),
but it is the same class of mistake. **Recommendation: suppress the banner when stdout is not a
TTY**, and pin it with a test.

## Out of scope

- ASCII wordmark or block art, and a Textual `Header` widget — both ruled out above.
- A `--no-banner` flag or `AGENT86_NO_BANNER` env var. Not requested; revisit if task 6's
  suppression proves insufficient.
- Giving the plain loop a live status line (task 4).
- `--version` output, which stays machine-plain (`agent86 1.0.0`).
- Everything in the 999.x backlog, including 999.0a.
