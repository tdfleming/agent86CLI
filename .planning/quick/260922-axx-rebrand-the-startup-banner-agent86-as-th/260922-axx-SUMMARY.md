# Quick Task 260922-axx — Summary

**Rebrand the startup banner: `agent86` as the title, `version` as a label**

`banner()` (`src/agent86/ui/repl.py`) titled its panel "agentic harness" and opened the body
with `agent86 v<version>` — the brand was buried in the body while a generic descriptor carried
the title. Flipped: the panel title is now `agent86`, and the body's first row is an ordinary
`version` label row aligned with `model` / `sandbox`, with no redundant `v` prefix.

```
╭─ agent86 ────────╮
│ version  1.0.0   │
│ model    qwen2.5 │
╰──────────────────╯
```

Because the new title (`agent86`) is no longer a distinctive string, two contract tests that
asserted the banner's *absence* (`run` / `run --json` must stay banner-free) were re-sharpened
to use a brand-independent sentinel pair instead: the `/help` hint text
(`"Type /help for commands"`) plus the Rich panel's top-left border glyph (`╭`) — neither of
which the old title-swap would have preserved as a meaningful absence check.

## Tasks completed

| # | Task | Commit |
|---|---|---|
| 1 | `ui/repl.py` — retitle panel to `agent86`, relabel body to `version` row, update docstring | `75d8aa3` |
| 2 | `tests/tui/test_banner.py` — follow the new strings (4 presence assertions, 3 body-token assertions) | `79a0cb6` |
| 3 | `tests/integration/test_scripting_contract.py` — re-sharpen the no-banner sentinel for `run`/`run --json` | `dfd4768` |
| 4 | `tests/tui/test_fallback.py` — same sentinel swap for the non-TTY suppression test | `74f5602` |
| — | Style follow-up: collapse the new banner body f-string to one line per `ruff format` | `8e3890f` |

## Verification (actual results)

- **`pytest`** — full suite: **1241 passed, 14 deselected** in ~97s. No deselection-count
  change from before this task.
- **`ruff check .`** — `All checks passed!`
- **`mypy src/agent86`** — `Success: no issues found in 93 source files`
- **`ruff format --check`** — the two files I touched with substantive edits
  (`src/agent86/ui/repl.py`, `tests/integration/test_scripting_contract.py`) had pre-existing
  formatting deviations *unrelated* to this task's lines (a `Syntax(...)` call, a `run_turn(...)`
  call, `_project_config(...)`, a `WRITE = ToolCall(...)` literal — none touched by this plan).
  I reformatted only the one line I personally introduced (the `body = f"..."` assignment in
  `banner()`) to match `ruff format`'s single-line collapse, and left the pre-existing
  out-of-scope deviations alone per the scope-boundary rule. Logged below rather than fixed.
- **`lines.count("agent86") == 2`** in `test_transcript_escape.py:238` and
  `test_transcript_render.py:193` — **confirmed still holds.** Ran both files directly
  (`pytest tests/tui/test_transcript_escape.py tests/tui/test_transcript_render.py -q`):
  19 passed. The count is unchanged because the banner still contributes exactly one `"agent86"`
  occurrence per render — it moved from the body (`agent86 v<version>`) to the panel title
  (`agent86`) rather than disappearing or duplicating.

### Rendered banner (actual, via Rich at width=40)

Compact (`compact=True`):
```
+----------- agent86 ------------+
| version  1.0.0                 |
| model    ollama:qwen3.5:latest |
+--------------------------------+
```

Full (`compact=False`):
```
+-------------- agent86 ---------------+
| version  1.0.0                       |
| model    ollama:qwen3.5:latest       |
| router off                           |
| sandbox  subprocess   approval ask   |
| Type /help for commands, /exit to    |
| quit.                                |
+--------------------------------------+
```

Matches the plan's target render exactly.

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 3 - blocking/hygiene] `ruff format` would have reformatted the new banner body line**
- **Found during:** post-task-1 verification pass (`ruff format --check`)
- **Issue:** my initial 3-line parenthesized f-string assignment for `body` fit on one line
  under the project's 100-column limit; `ruff format --diff` flagged it for collapsing.
- **Fix:** collapsed to a single-line f-string assignment, matching what `ruff format` produces.
- **Files modified:** `src/agent86/ui/repl.py`
- **Commit:** `8e3890f`
- **Out of scope, left alone:** two *pre-existing* `ruff format` deviations in
  `src/agent86/ui/repl.py` (a `Syntax(...)` call split across two lines, a `run_turn(...)` call
  that now fits on one line) and one pre-existing deviation in
  `tests/integration/test_scripting_contract.py` (`_project_config(...)`'s call layout and the
  `WRITE = ToolCall(...)` line length) — none are on lines this task touched, so per the
  deviation-rules scope boundary I did not reformat them. `ruff check .` (lint) is clean; only
  `ruff format --check` (pure style) flags these, and it was not part of this task's mandated
  verification gates.

No architectural, scope-expanding, or Rule 4 deviations. The plan's out-of-scope list
(`cli.py --help`, `__init__.py` docstring, `cognitive/prompt.py`) was not touched.

## Self-Check

- `src/agent86/ui/repl.py` — FOUND, contains `title="agent86"` and the `version` label row
- `tests/tui/test_banner.py` — FOUND, updated assertions present
- `tests/integration/test_scripting_contract.py` — FOUND, sentinel swap present
- `tests/tui/test_fallback.py` — FOUND, sentinel swap present
- Commit `75d8aa3` — FOUND in `git log`
- Commit `79a0cb6` — FOUND in `git log`
- Commit `dfd4768` — FOUND in `git log`
- Commit `74f5602` — FOUND in `git log`
- Commit `8e3890f` — FOUND in `git log`

## Self-Check: PASSED
