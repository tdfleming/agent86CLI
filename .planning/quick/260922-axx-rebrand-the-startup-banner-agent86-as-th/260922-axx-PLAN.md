# Quick Task 260922-axx — Rebrand the startup banner: `agent86` as the title, `version` as a label

**Created:** 2026-09-22
**Type:** Branding / UX, cosmetic
**Files:** `src/agent86/ui/repl.py`, `tests/tui/test_banner.py`,
`tests/integration/test_scripting_contract.py`, `tests/tui/test_fallback.py`
**Follows:** quick task `260922-bnr`, which gave both surfaces one shared `banner()`.

## Problem

`banner()` (`ui/repl.py:46`) titles its panel **"agentic harness"** and opens the body with
**`agent86 v<version>`**. The brand sits in the body while the panel title carries a generic
descriptor — backwards for a splash whose job is to say *what this is*. Requested 2026-09-22:
put `agent86` in the title, and turn the body row into a `version` label.

Current render (compact):

```
╭─ agentic harness ─╮
│ agent86 v1.0.0    │
│ model    qwen2.5  │
╰───────────────────╯
```

## Decisions (user, 2026-09-22)

| Question | Ruling |
|---|---|
| Panel title | `agent86` — replaces "agentic harness". |
| Body identity row | A **`version` label row**, aligned with the other label rows. |
| The redundant `v` | **Dropped.** `version  1.0.0`, not `version v1.0.0`. |
| Label alignment | 9-column label gutter, matching the existing `model    ` / `sandbox  ` rows. |
| Styling | The `version` row becomes an ordinary label row — no bold — matching `model`. |
| Scope | Cosmetic only. `compact` split, TTY suppression and transcript-entry behaviour all unchanged. |

Target render (compact):

```
╭─ agent86 ────────╮
│ version  1.0.0   │
│ model    qwen2.5 │
╰──────────────────╯
```

## The catch: `"agentic harness"` is load-bearing in two contract tests

`test_scripting_contract.py:184-185` and `test_fallback.py:139` assert the banner is **absent**
(`run` / `run --json` must stay JSON-pure; a non-TTY stdout must not get the panel). They use
`"agentic harness"` as the sentinel, and it works *because it is distinctive*.

After the rename the title is `agent86` — a string that appears in ordinary output, module names
and JSON payloads. Reusing it as an absence sentinel would make both tests **vacuously weak**:
they could pass while a banner printed, or fail on unrelated output.

**Replace the sentinel with a brand-independent one:** `Type /help for commands, /exit to quit.`
— verified unique to `banner()` across `src/` — plus the Rich panel's top-left border character
`╭`, which pins "no panel was drawn at all" independently of any wording.

This keeps the no-banner contract sharp through any future rebrand.

## Tasks

### 1. `ui/repl.py` — retitle and relabel

- `Panel(..., title="agentic harness", ...)` → `title="agent86"` (line 69). Border style, the
  cyan colour and `expand=False` all unchanged.
- Body's first row: `f"[bold]agent86[/bold] [dim]v{__version__}[/dim]"` becomes a label row
  `f"version  [cyan]{__version__}[/cyan]"` — 9-column gutter, no `v` prefix, value in cyan like
  every other row's value.
- Update the docstring (line 49), which names the old `agent86 v<version>` form.
- Stays Rich-only and textual-free; the import graph does not move.

### 2. `tests/tui/test_banner.py` — follow the new strings

- Four `"agentic harness"` assertions (lines 129, 145, 164, 185) → `"agent86"`. These are
  *presence* assertions on a rendered banner, so the brand word is still a fine marker here.
- Three assertions on `f"agent86 v{__version__}"` (lines 78, 88, 115) → the new
  `f"version  {__version__}"` form.
- **The drift test (line 115) keeps its job:** both surfaces must still agree on name, version
  and model from one `banner()` call. Update the token it looks for, not what it proves.

### 3. `test_scripting_contract.py` — re-sharpen the no-banner sentinel

Swap the two `"agentic harness"` absence assertions for the brand-independent pair:
`"Type /help for commands"` and `"╭"`, on both stdout and stderr, for `run` and `run --json`.

### 4. `test_fallback.py:139` — same swap

Non-TTY suppression test: assert the hint string and `╭` are absent, not the old title.

## Verification

- `pytest` — full suite green, no deselection changes.
- `ruff check .` and `mypy src/agent86` clean.
- `lines.count("agent86") == 2` in `test_transcript_escape.py:238` /
  `test_transcript_render.py:193` should still hold: the body loses one `agent86`, the title
  gains one. **Confirm rather than assume** — if the count shifts, the banner render changed in
  a way this plan did not intend.

## Out of scope

- The `compact` split, the TTY suppression rule, transcript-entry rendering, `/clear` behaviour.
- `cli.py:75`'s `--help` text and `__init__.py:1`'s docstring, which also say "agentic harness".
  Those describe the *package*, not the splash, and were not part of the request.
- The system prompt's "agentic harness" wording (`cognitive/prompt.py:20`).
