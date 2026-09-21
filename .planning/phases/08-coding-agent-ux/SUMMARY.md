---
phase: 08-coding-agent-ux
subsystem: tui/ui/tools/skills/guardrails/memory
tags: [markdown-transcript, tool-blocks, prompt-input, prompt-history, file-mentions, session-picker, edit-file, unified-diff, tool-preview, agent-skills, allowed-tools]
requirements: [UX-01, UX-02, UX-03, UX-04, UX-05, UX-06, TOOL-01, SKILL-01]
status: complete
completed: 2026-09-21
---

# Phase 8 — Coding-Agent UX

**Goal:** make the transcript and the prompt do for a *coding* session what the TUI already did for
a chat session. v0.8 made the harness frugal with the context window; every remaining complaint was
about the surface. A reply arrived as its own Markdown source. Ten tool calls buried the answer,
and the two things worth keeping — the full arguments and the full output — were exactly what had
been truncated away. The prompt was one line with no memory of the last session. Putting a file in
front of the model cost a tool round trip. A past conversation was a 12-character id. `edit_file`
rewrote a CRLF file's line endings, dropped its BOM, and answered "Edited a.py." An approval showed
300 characters of JSON. A skill's `allowed-tools` was a comment.

**Requirements:** UX-01 (Markdown transcript), UX-02 (collapsible tool-call blocks), UX-03
(multi-line input + persistent history), UX-04 (`@file` mentions), UX-05 (session picker), UX-06
(diff approval), TOOL-01 (exact-match `edit_file`), SKILL-01 (Agent Skills convention +
`allowed-tools`).

Like Phases 5, 6 and 7, this phase was executed as a review-driven pass rather than a numbered plan
set: every item was a finding from the v0.8 release review, recorded in `PROJECT.md` § "Next
milestone candidates" and `docs/BACKLOG.md` §§ "TUI" and "Skills & tools", not new surface area.
Nothing here changes the scripting contract — `run`, `run --json` and `--plain` are untouched, and
the new modules on the shared path (`ui/history.py`, `tui/mentions.py`) import no Textual, so
`--plain` gets persistent history and `@file` mentions for free while paying nothing for the TUI.
Work is grouped below by workstream; commits are listed oldest-first within each group.

---

## Workstream 1 — Transcript (UX-01, UX-02)

**The transcript was append-only, and that was the constraint.** Both of this workstream's
requirements need an entry to change how it renders *after* it was first written — a reply that
becomes Markdown when it completes, a tool call that expands. A `RichLog` cannot do that, and
migrating to a `VerticalScroll` of widgets would have broken every surface that queries
`#transcript` as a `RichLog`. The resolution is that the widget stays a `RichLog` — append-only,
cheap to stream into, and unchanged for every caller — while the app keeps a **model** of the
scrollback beside it: an ordered list of entries, replayed into the log on a re-render. Everything
below falls out of that one decision.

**Markdown, once, on completion** (`0cc8605`). A reply streams in as plain escaped text and is
re-rendered as a single `rich.markdown.Markdown` document when it completes — at turn end, at a
harness notice, or at the next tool call. Streaming it *as* Markdown was never an option: a
half-written fence or table renders as garbage, and re-parsing the document on every delta is the
cost the streaming path exists to avoid. Two properties came free with `Markdown`: it never parses
console markup, so model text like `[/weird]` can neither raise `MarkupError` on the main thread
nor vanish into a style tag, and fenced code can go through `Syntax(word_wrap=True)`, so a wide
code block wraps instead of blowing the layout. The re-render is skipped entirely when the reply
has no Markdown structure — plain prose already looks the same — so the common short answer pays
nothing. `UserEntry` (the prompt echo) is always plain and escaped: it is the user's own text, and
rendering it as Markdown would be both wrong and a markup-injection surface.

**One call, one block** (`f524880`). A tool call cost two flat lines — `[tool] name({...})` at the
start and `[tool] name -> summary` at the end — with arguments truncated at 160 characters and the
result reduced to its first line. One block replaces both: a dim `> name(args) -> summary`, cropped
to the terminal width, that expands (`ctrl+o` for the last, `ctrl+shift+o` for all) to the full
arguments as pretty JSON and the full result text, capped at 200 lines with a truncated tail. The
full data comes from the **bridge**, not the delta lines: the loop appends the assistant message
(with `tool_calls`) before it announces a call and the `TOOL` message before it summarises one, so
`turn_bridge` looks both up in the session state and posts them with the message. That also fixed a
quieter bug — result lines used to fall through to `TurnDelta` and read as model speech. A block is
rendered when its *result* lands, so its header is never rewritten; its place in the entry list is
reserved at announce time; and a call the turn never observed is flushed at turn end. Everything
inside a block renders through `rich.text.Text`, which is never markup-parsed. Toggling is
keyboard-driven rather than click-driven, for the `RichLog` reason above — the follow-up is in
`docs/BACKLOG.md`.

**A failed turn says what raised it** (`daca8ec`). The line rendered as `error: <str(exc)>`, which
for a wrapped provider failure says what went wrong but never what raised it, and left no way to
get at the rest. It now leads with the exception **type**, keeps the (escaped) message, and is
followed by a dim hint naming the command that has the whole story:
`see agent86 trace show -s <session>`. Harness notices (`[compacted ...]`, `[continuing ...]`)
became `NoticeEntry` — still dim, still set apart from model speech, but entries like everything
else; before this they would have been dropped by the first re-render, which is exactly the class
of bug the entry-list design creates if you let it.

| Commit | What |
|---|---|
| `0cc8605` | feat(tui): render finished assistant replies as Markdown |
| `f524880` | feat(tui): collapsible tool-call blocks in the transcript |
| `daca8ec` | feat(tui): name the exception and point at the trace on a failed turn |

---

## Workstream 2 — Input and sessions (UX-03, UX-04, UX-05)

**The knobs first** (`efdd306`). `[ui] history_file` / `history_size`, `[ui] markdown`, and
`[tools] mention_max_bytes` landed ahead of the widgets that read them, so nothing downstream had
to hard-code a default and later be rewired.

**A prompt you can actually type into** (`81f3753`). `ui/history.PromptHistory` is a Textual-free,
stdlib-only record of submitted prompts following bash's rules: no blanks, no leading-space lines,
no consecutive duplicates, capped at `[ui] history_size`, appended atomically with a temp-file
rewrite when the cap trims it. A missing, unwritable or corrupt file degrades to "this session
only" rather than stopping a REPL from starting — a history file is a convenience and must never
be a startup dependency. `tui/widgets/prompt_input.PromptInput` is a `TextArea` that keeps the
`Input` interface (`.value`, `.clear()`, a `Submitted` message whose `.input` aliases the widget),
which is what let it be swapped into `app.py` without reopening turn handling: Enter submits,
Shift+Enter and Ctrl+J insert newlines, Up/Down walk history *from the first and last line only*
(so they still move the cursor inside a multi-line draft), Escape clears the draft, and the widget
grows to 8 rows before scrolling. The plain loop appends every submitted prompt to the same file,
so the two surfaces share one history; `_Repl.history` is built lazily, so constructing a REPL
never reads the user's real history file — which is what makes the tests honest.

**`@path` mentions** (`b9b6b68`). `tui/mentions.expand_mentions` turns `@src/app.py` (or
`@"path with spaces"`) into an inline fenced block appended to the prompt, so a file can be put in
front of the model without spending a tool round trip on it. The load-bearing order is that every
path goes through `SandboxPolicy.resolve_within` **first**: a path outside the workspace jail is
refused and never opened — not stat'ed, not sniffed, not read — because a refusal that still
touches the file leaks whether it exists. What is inlined stays bounded: `[tools]
mention_max_bytes` per file, at most 200 names for a directory listing, binaries refused, and a
fence long enough to survive backticks in the content. Refusals are surfaced to the user *and*
carried in the prompt, so neither side assumes a file arrived when it didn't — a visible refusal
the model can't see is worse than no mention at all. `complete_mentions` offers up to 20
workspace-relative completions to the palette, directories first, skipping
`.git`/`.venv`/`node_modules`/`__pycache__`, and refuses to complete outside the workspace. The
module imports no Textual, so `--plain` expands mentions through the shared
`_Repl.expand_mentions` seam and pays nothing.

**Sessions you can find again** (`c4c1bd9`, `d7a1d95`). A session log you can't read is a log you
never go back to, and every past conversation was an opaque 12-character id. A session is now named
after the first thing the user said to it (collapsed, truncated to 60 characters), and that name is
what the listing, the picker and the resume note all show. `MemoryStore` gained `SessionInfo`,
`recent_sessions()` and `session_title()` so no UI ever touches a sqlite `Row`, and
`save_session`'s title semantics are pinned: `None` keeps the existing name, a title given wins.
`Harness._persist` names a session **once** — on the first persist that has a user message to name
it after — and asks the store first, so a compaction that drops the opening message cannot silently
rename the conversation. `EpisodicMemory` exposes the same listing: recall answers "what happened
in a turn like this", this answers "what were we working on". `/sessions` prints the recent
sessions with the active one highlighted; `/resume [id]` accepts the 8-character prefix the listing
actually shows and refuses an ambiguous one rather than guessing; `/resume` with no argument raises
`SessionPickerModal`, a filter `Input` over an `OptionList` shaped like `CatalogPickerModal`,
guarded by `maybe_one` and dismissing with a session id or `None`, whose options are built as Rich
`Text` because titles are user input. The follow-up commit gave the modal an empty default list, so
the app's placeholder call is an honest "no saved sessions yet" picker rather than a `TypeError` at
the prompt and a mypy failure in a file that workstream must not touch.

| Commit | What |
|---|---|
| `efdd306` | feat(config): add prompt-history, markdown and mention-cap settings |
| `81f3753` | feat(ui): multi-line prompt with shared, persistent history |
| `b9b6b68` | feat(tui): expand @file mentions into the prompt |
| `c4c1bd9` | feat(memory): name sessions and add /sessions, /resume and a picker |
| `d7a1d95` | fix(tui): default SessionPickerModal to an empty session list |

---

## Workstream 3 — Tools and skills (TOOL-01, UX-06, SKILL-01)

**`edit_file` is the tool a coding agent lives in** (`5341ae5`), and the old one answered "Edited
a.py." — no diff, no match count, and a whole-file rewrite through `read_text`/`write_text` that
silently converted a CRLF file's line endings and dropped its BOM. It is now exact-match on
`old_string`/`new_string` with `replace_all` (the pre-v0.9 `old`/`new` names kept as aliases, so an
older transcript degrades to working rather than hard-failing), and its refusals name the count
*and* the way out: "0 matches ... copy the text verbatim", "3 matches ... add context, or pass
`replace_all=true`" — a refusal the model can act on is worth more than one that is merely
correct. The file is decoded and re-encoded by the tool itself: BOM detected and restored, CRLF
normalised for matching and written back as CRLF, a mixed file left verbatim, and a non-UTF-8 file
refused rather than mangled by an `errors="replace"` round trip. Both mutations answer with a
unified diff (also in `metadata["diff"]`), and `write_file` says "new file, N lines" when there was
nothing to diff. `unified_diff_for()` / `head_of()` / `read_file_text()` came out as shared
helpers — which is what made the next commit cheap.

**Approving a change, not a tool name** (`c77ede8`). The ASK gate handed the prompt a
300-character JSON dump of the arguments, so a `write_file` whose content ran past that cap — or
any `edit_file` at all — was approved sight-unseen. The user was answering "do you trust this tool
name?", not "do you want this change?". `Tool.preview(arguments, ctx)` is new on the ABC (default
`None`): `write_file`/`edit_file` return a unified diff against the file on disk (and say so when
`old_string` is missing or ambiguous, naming the count), `run_command` and `python_exec` return the
whole command or snippet capped at 60 lines instead of truncated mid-token. It is called with the
**raw, unvalidated** arguments — the gate runs before validation — and must never raise;
`build_preview` swallows and logs it if it does. The compatibility trick is `ApprovalPreview`, a
`str` subclass carrying `detail`/`lexer`: the `(tool_name, preview) -> bool` contract that the TUI
bridge, the plain loop and every test double implement keeps working untouched, while a caller that
knows about the detail renders it. `ApprovalGate(..., context=)` is optional and preview-only;
without it the file previews resolve against the CWD, which is the default workspace. The modal
renders the detail in a scrollable `rich.syntax.Syntax` panel — never as console markup, since a
diff is full of `[` — and gained `y`/`n` alongside `escape`, with every path still an explicit
`dismiss`.

**The Agent Skills convention, with the allowlist as a gate** (`8b7e2fc`). Discovery now matches
the convention skills are actually written to. Frontmatter: the closing delimiter is a `---` on its
own **line** (splitting on the next three hyphens anywhere truncated any skill whose body had a
horizontal rule); block scalars (`>` folded, `|` literal), quoted values, inline and block lists;
PyYAML used when it happens to be installed and a built-in mini parser when it is not, because **a
skill must never need a dependency** — both paths are tested against the same cases;
`allowed-tools` space-delimited per the convention, with commas, brackets and YAML lists tolerated;
`license` and `metadata` carried. Discovery searches project `.agent86/skills` -> project
`.claude/skills` -> user `~/.agent86/skills` -> `~/.claude/skills` -> `[skills] paths`, **first
root wins**, so a project skill shadows a user skill and nothing shadows the project; project roots
resolve against an explicit `workspace` argument rather than the CWD (callers that pass none keep
the CWD fallback). `skill_roots()` feeds `default_policy`, so a skill's bundled resources — which
for a user skill live *outside* the workspace — are readable instead of a jail error on the first
"see `reference.md`". Enforcement: `use_skill` records the skill on `ToolContext` and
`ToolRegistry.dispatch` refuses anything outside a non-empty `allowed-tools`, naming the skill and
the list so the model can re-plan rather than retry; `use_skill` itself is always callable (a skill
that forgot to list it would be a one-way door); activating another skill *replaces* the
restriction rather than intersecting it, so a skill's boundary never depends on history; and
`clear_skill()` lifts it at the end of the turn. The compiled system prompt lists each skill's
`allowed-tools`, so the restriction is known before a refusal costs a step.

| Commit | What |
|---|---|
| `5341ae5` | feat(tools): exact-match edit_file with unified diffs |
| `c77ede8` | feat(guardrails): show what a side effect does before approving it |
| `8b7e2fc` | feat(skills): Agent Skills convention, with allowed-tools enforced |

---

## Workstream 4 — Wiring

Three workstreams built against `app.py` at once, so the seams were cut before the widgets were
swapped in (`166906f`) and bound in a final pass:

- **`submit_prompt(text)`** is everything `Input.Submitted` did after clearing the box, so a
  replacement input widget dispatches through exactly one path. The wiring pass swapped
  `PromptInput` in behind it and expanded `@path` mentions on submit.
- **`open_session_picker()`** pushes `SessionPickerModal`, imported lazily and guarded with a
  transcript note, handing it the recent-session list only if `commands.recent_sessions` exists —
  `commands.py` belonged to another workstream, and a picker with no list beats an `AttributeError`
  at the prompt. `/resume` with no argument now routes here.
- **`load_session(state)`** makes a state live and rebuilds the transcript from its messages:
  prompts echoed plain, assistant turns through the Markdown path, and every tool call a collapsed
  block with its arguments and result attached — so a resumed session looks like the one that was
  left, not like a flat replay.

The same pass bound the rest: `discover_skills(config, workspace)` so project skills resolve
against the workspace rather than the process CWD, the approval gate given the tool context so file
previews resolve against the real workspace, `clear_skill()` called at the end of every turn, and a
`y/N` approval prompt carrying the diff in the plain loop when stdin is a TTY — `run` without
`--yes` is non-interactive and still declines, unchanged.

| Commit | What |
|---|---|
| `166906f` | feat(tui): hook points for the v0.9 input/session wiring pass |
| *(wiring pass)* | PromptInput swapped in, mentions on submit, `/resume` -> picker, `discover_skills(config, workspace)`, the gate given the tool context, `clear_skill()` per turn, the plain-loop y/N approval |

---

## What this opened

Recorded in `docs/BACKLOG.md`, none of it blocking:

- **Click-to-toggle tool blocks.** The block is a renderable that changes shape, and the log is
  re-rendered when it does — because a `RichLog` renders to strips and cannot host interactive
  children. A clickable block needs the transcript migrated to a widget-based container, which
  would also have to keep `#transcript` answering as a `RichLog` for every surface that queries it.
- **History navigation in the plain loop.** Both surfaces write the same history file, but stdlib
  `input()` has no line editor, so the plain loop can only append. Up-arrow recall there needs
  `readline` (absent on Windows without a third-party module) — a dependency decision, not an
  implementation one.
- **The jail has no read/write split.** `skill_roots()` is granted to `allow_paths` so a skill's
  bundled resources are readable, but `allow_paths` grants *write* as well: a user skill's own
  directory — `~/.claude/skills` included — is now writable by a tool call. The fix is a policy
  with separate read and write sets, not a narrower grant.
