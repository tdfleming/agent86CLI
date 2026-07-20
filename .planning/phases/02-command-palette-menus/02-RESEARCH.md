# Phase 2: Command Palette + Menus - Research

**Researched:** 2026-07-19
**Domain:** Textual TUI — inline command palette, arrow-key choice menus, declarative command registry
**Confidence:** HIGH (Textual widget APIs, priority bindings, existing test patterns) / MEDIUM (exact key-routing interaction between App-level bindings and `Input`'s own Enter/Escape handling — flagged for a wave-0 spike)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Palette trigger & presentation**
- **D-01:** Build a **custom `/`-triggered inline dropdown** — typing `/` in the prompt opens an
  autocomplete list (a Textual `OptionList`) rendered below/over the input that filters as the
  user types. This is the primary palette, chosen for the most Claude-Code-like feel.
- **D-02:** Do **not** rely on Textual's built-in command palette (Provider system / Ctrl+P) as
  the primary surface. (A Ctrl+P registration is not required this phase; the `/` dropdown is the
  contract.)
- **D-03:** Each palette entry shows the command **name and its description** (success criterion
  1). Selecting an entry runs it.

**Command registry (single source of truth)**
- **D-04:** Refactor to a **declarative command registry** — each command becomes a registry
  entry carrying at minimum: name, description, handler, and a flag/spec for whether it needs a
  choice (and what choices). This registry is the single source of truth feeding the palette, the
  choice menus, and `/help`.
- **D-05:** The registry must reproduce the existing dispatch behavior branch-for-branch
  (`/help /config /models /model /tools /skills /memory /mode /cost /clear /exit`). Behavior is
  unchanged; only the surfacing changes. Reuse the existing `CommandResult` contract in
  `tui/commands.py` rather than inventing a new return type.

**Arrow-key menus (TUI-04)**
- **D-06:** The autocompleting palette **is itself the primary arrow-key selector** — users
  navigate/select commands with arrow keys + Enter.
- **D-07:** Add a dedicated **`/model` picker** as an arrow-key `OptionList` of models to switch
  to (no typing `provider:model` required).
- **D-08:** Add a dedicated **`/mode` picker** as an arrow-key `RadioSet` for `ask` / `auto` /
  `deny`.
- **D-09:** Only commands that genuinely need an argument get a dedicated choice menu this phase
  (i.e. `/model` and `/mode`). Commands that already act with no argument keep running directly.

**Argument flow**
- **D-10:** When a palette command needs an argument, **selecting it chains straight into its
  choice menu** (e.g. selecting `/model` opens the model picker; selecting `/mode` opens the mode
  picker). Fully menu-driven — no intermediate typing required. This directly satisfies success
  criterion 2.

**Backward compatibility**
- **D-11:** **Typed slash-commands keep working** unchanged. Typing a full command such as
  `/model openrouter:anthropic/claude-3.7-sonnet` and pressing Enter still runs it directly. The
  palette and menus are **additive** — existing typed-command tests and muscle memory must stay
  green (success criterion 3).

### Claude's Discretion
- **D-12:** **Source of the `/model` picker list** — Claude decides the cleanest source given
  today's config (which exposes providers + the `default`/`cheap`/`frontier` role slots, with no
  per-provider model catalog yet). Reasonable approach: list the configured role models plus any
  model refs present in config as ready-to-switch choices, kept consistent with the richer
  catalog that Phase 3 will introduce. If no meaningful list can be built, fall back to
  prefilling `/model ` for typing.
- **D-13:** Exact dropdown widget styling, positioning, filter/fuzzy-match algorithm, keybindings
  for dismiss (Esc), and how the dropdown coexists visually with the streaming `Static` line are
  Claude's to choose, consistent with the Phase 1 layout.

### Deferred Ideas (OUT OF SCOPE)
- Per-provider model catalog + add/test/save model config → Phase 3 (MODEL-01/02, SEC-01). The
  `/model` picker this phase lists what today's config already knows.
- MCP server list/add/remove menus → Phase 4 (MCP-01).
- Ctrl+P / fuzzy global command palette via Textual's Provider system → not required; could be a
  future polish item if the `/` dropdown proves insufficient.
- Theming / color schemes for the palette → v2 (POL-01).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TUI-03 | A command palette offers autocomplete over slash-commands (`/model`, `/mcp`, `/config`, `/cost`, `/clear`, …) and runs the selected one | Registry pattern (§Architecture Pattern 1), `/`-triggered `OptionList` dropdown pattern (§Architecture Pattern 2), key-routing via priority `Binding`s (§Architecture Pattern 3) |
| TUI-04 | Interactive choices are made via arrow-key selectable menus/modals | `RadioSet` for `/mode`, `OptionList`-in-`ModalScreen` for `/model` (§Architecture Pattern 4), chaining from palette selection (§Pattern 5) |
</phase_requirements>

## Summary

The existing `tui/commands.py::handle_command` is a flat if/else dispatch keyed on exact-match or
prefix-match strings, returning a `CommandResult(action, render)`. It already isolates all
command logic from I/O (nothing touches stdout), which makes it a clean seam to refactor into a
declarative registry without touching behavior. `tui/app.py::on_input_submitted` is the single
integration point where typed input becomes a command today — this is also where the `/`-dropdown
must be triggered (on `Input.Changed`, not `Input.Submitted`) and where a chained picker must be
opened instead of calling `handle_command` directly when a command needs a choice.

Textual (installed: 8.2.8, pinned `>=1.0` in `pyproject.toml`) ships everything needed as core
widgets — no new dependency is required: `OptionList` (palette + model picker, supports
`add_options`/`clear_options`/`highlighted`/`OptionSelected`/`OptionHighlighted` messages),
`RadioSet` (mode picker, `Changed` message, `pressed_index`), and `ModalScreen[T]` (already used
by `ApprovalModal`, D-08's/D-07's picker should mirror this exact pattern). The one genuinely
tricky part is **key routing**: while the user is typing in the focused `#prompt` Input, Up/Down/
Enter/Escape need to drive the dropdown instead of (or in addition to) `Input`'s own behavior
(cursor movement, `Input.Submitted`, no-op). Textual's documented, first-class mechanism for this
is **priority `Binding`s** (`Binding(..., priority=True)`) on the `App`, which are checked before
the focused widget's own key handling and cannot be shadowed by widget-level bindings. This is a
HIGH-confidence, officially documented pattern (see Architecture Pattern 3) — but the exact
interaction with `Input`'s native Enter-submits/Escape-does-nothing behavior when the dropdown is
**closed** should be verified empirically in a wave-0 spike, since `Input.Submitted` firing must
still work unchanged whenever the dropdown isn't showing (D-11).

**Primary recommendation:** Refactor `handle_command` into a `COMMANDS: list[CommandEntry]`
registry (dataclass: `name`, `usage`, `description`, `needs_choice: Literal[None,"model","mode"]`,
`handler`) that both the existing string-dispatch and the new palette/menu layer consume; render
the `/`-dropdown as a plain sibling `OptionList` (`display: none` by default) inserted between
`#stream` and `#prompt` in the compose tree — not an absolute-position overlay — toggled via
`Input.Changed`; drive its navigation via three `priority=True` App bindings (`up`, `down`,
`enter`) that only act when the dropdown is visible and otherwise no-op (Input has no native
Up/Down handling, so this is safe); and implement `/model` and `/mode` pickers as
`ModalScreen[str | None]` subclasses that mirror `ApprovalModal` exactly, chained from the
dropdown's `OptionSelected` handler.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| textual | 8.2.8 (installed; pinned `>=1.0`) | `OptionList`, `RadioSet`, `ModalScreen`, `Binding(priority=True)` | Already the project's TUI framework (Phase 1 lock); every widget this phase needs ships in core — no new dependency |

### Supporting
None required. No new library needed for this phase.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-built `/`-triggered `OptionList` dropdown | `textual-autocomplete` (darrenburns, PyPI, Textual ≥2.0 compatible) third-party widget | Purpose-built for exactly this (`AutoComplete` attaches to an `Input`, `get_candidates`/`DropdownItem`/`apply_completion`, dropdown positions below input, Escape hides it). Rejected because D-01 explicitly locks a **custom** dropdown, and pulling in a new runtime dependency (even a small one) adds an import to audit for the lazy-import/cold-start contract (CLAUDE.md) for a widget the team wants full control over (fuzzy-match algorithm, dismiss keys — D-13 discretion). Worth a name-drop in the plan as prior art/fallback if the custom build proves harder than expected. |
| App-level priority `Binding`s for key routing | Subclassing `Input` and overriding its internal key handler | Subclassing `Input`'s private `_on_key` is not a public/documented API surface (higher regression risk on Textual upgrades) — priority `Binding`s are the documented, supported mechanism for "app-level hotkey that pre-empts the focused widget." |
| `ModalScreen[str | None]` pickers for `/model`/`/mode` | Inline `OptionList`/`RadioSet` swapped in place of `#prompt` | Inline avoids a screen-push/pop but requires more custom layout bookkeeping (save/restore prompt state, focus management) and has no established pattern in this codebase; `ModalScreen` is the proven Phase 1 pattern (`ApprovalModal`) already covered by Pilot tests — lower risk, consistent with D-13's "Claude's discretion, consistent with Phase 1." |

**Installation:**
```bash
# No new dependency — Textual 8.2.8 is already installed and covers OptionList, RadioSet, ModalScreen.
```

**Version verification:**
```bash
python -c "import textual; print(textual.__version__)"   # -> 8.2.8
pip show textual                                          # confirms installed release
```
`pyproject.toml` pins `textual>=1.0` as a core-but-lazy dependency (comment: "imported only inside
the TUI entry path"); 8.2.8 is what's actually installed in this environment and is what was
used to verify every API referenced below via Context7 (`/textualize/textual`, docs pulled live).

## Architecture Patterns

### Recommended Project Structure
```
src/agent86/tui/
├── app.py                  # Agent86App — wire dropdown + key bindings + menu chaining here
├── commands.py             # COMMANDS registry + handle_command (refactored, same CommandResult)
├── palette.py               # NEW: CommandEntry dataclass, COMMANDS list, filter helper (or keep
│                            #      in commands.py — see Pattern 1 tradeoff)
├── screens/
│   ├── approval.py          # existing ModalScreen[bool] pattern — mirror below
│   ├── model_picker.py      # NEW: ModelPickerModal(ModalScreen[str | None])
│   └── mode_picker.py       # NEW: ModePickerModal(ModalScreen[str | None])
└── widgets/
    └── status_footer.py      # unchanged
```

### Pattern 1: Declarative command registry backing dispatch, palette, and `/help`
**What:** Replace the if/else chain in `handle_command` with a list of `CommandEntry` records;
`handle_command` becomes a lookup instead of branch-for-branch logic; `_help_table` and the
palette both iterate the same list.
**When to use:** Now — this is D-04/D-05, required before the palette can exist without drifting
from `/help`.
**Example:**
```python
# tui/commands.py — reproduces existing dispatch behavior via a registry lookup
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Literal

ChoiceKind = Literal[None, "model", "mode"]

@dataclass(frozen=True)
class CommandEntry:
    name: str                       # e.g. "/model" (no trailing space)
    usage: str                      # e.g. "/model <provider:model>"
    description: str                # shown in palette + /help
    needs_choice: ChoiceKind = None # drives menu chaining (D-10)
    # handler(repl, arg) -> CommandResult ; arg is "" for bare invocation
    handler: Callable[[object, str], "CommandResult"] | None = None
    terminal: bool = False          # True for /exit-style actions

def _help_entries() -> list[CommandEntry]:
    return COMMANDS  # single source of truth — /help renders straight from this

COMMANDS: list[CommandEntry] = [
    CommandEntry("/help", "/help", "Show this help", handler=lambda repl, arg: CommandResult("handled", _help_table())),
    CommandEntry("/config", "/config", "Show the resolved configuration", handler=lambda repl, arg: CommandResult("handled", repl.cfg.model_dump_json(indent=2))),
    CommandEntry("/models", "/models", "List configured models", handler=lambda repl, arg: CommandResult("handled", _models_tables(repl.cfg))),
    CommandEntry("/model", "/model <provider:model>", "Switch the active model for this session", needs_choice="model", handler=lambda repl, arg: CommandResult("handled", _set_model(repl, arg))),
    CommandEntry("/tools", "/tools", "List available tools", handler=lambda repl, arg: CommandResult("handled", "tools: " + ", ".join(repl.harness.registry.names()))),
    CommandEntry("/skills", "/skills", "List available skills", handler=lambda repl, arg: CommandResult("handled", _skills_render(repl))),
    CommandEntry("/memory", "/memory", "Show memory stats and session id", handler=lambda repl, arg: CommandResult("handled", _show_memory(repl))),
    CommandEntry("/mode", "/mode [ask|auto|deny]", "Show/set approval mode (Shift+Tab cycles)", needs_choice="mode", handler=lambda repl, arg: CommandResult("handled", _set_mode(repl, arg))),
    CommandEntry("/cost", "/cost", "Show token usage and cost this session", handler=lambda repl, arg: CommandResult("handled", _show_cost(repl))),
    CommandEntry("/clear", "/clear", "Start a fresh conversation", handler=lambda repl, arg: (repl.__setattr__("state", repl.harness.new_session()), CommandResult("handled", "conversation cleared"))[1]),
    CommandEntry("/exit", "/exit", "Quit", terminal=True, handler=lambda repl, arg: CommandResult("exit")),
]

def find_command(name: str) -> CommandEntry | None:
    return next((c for c in COMMANDS if c.name == name), None)

def handle_command(repl, line: str) -> "CommandResult":
    if not line:
        return CommandResult("noop")
    if line in ("/exit", "/quit"):
        return CommandResult("exit")
    if not line.startswith("/"):
        return CommandResult("turn")
    name, _, arg = line.partition(" ")
    entry = find_command(name)
    if entry is None:
        return CommandResult("handled", f"unknown command {line}")
    return entry.handler(repl, arg.strip())
```
**Note:** the original branches match on the *whole line* (e.g. `line == "/mode" or line.startswith("/mode ")`); the registry lookup above achieves the same by splitting on the first space, which is behavior-preserving for every existing command (none of the current commands have a name that is a prefix of another, e.g. `/model` vs `/models` differ by the space-split so `"/models"` splits to `name="/models"`, not `"/model"` — verify this specific edge case with a unit test since it's the one place prefix-vs-exact-match subtlety could regress).

### Pattern 2: `/`-triggered inline dropdown as a sibling widget (not an absolute overlay)
**What:** Add an `OptionList(id="palette", classes="hidden")` widget to `compose()`, positioned in
the natural document flow directly above `#prompt` (between `#stream` and `#prompt`), not via
`layer`/`offset` absolute positioning. Toggle visibility with `display: none` / `display: block`
(via `widget.display = True/False`) rather than Textual's `layers` system.
**When to use:** For this phase's dropdown. `layer`/`offset` absolute positioning (Source:
`docs/css_types/position.md`, `docs/styles/layer.md`) is the mechanism Textual itself recommends
for floating overlays that must not disturb layout — but it is more CSS surface area to get right
(z-order, coordinate math relative to the input's screen position, resize handling) for a payoff
(floating over the transcript) this app doesn't need, since the dropdown naturally has room to
live in the flow directly above the input without stealing space from `#transcript`/`#stream`
except while it's open.
**Example:**
```python
# app.py compose()
def compose(self) -> ComposeResult:
    yield RichLog(id="transcript", markup=True, wrap=True, highlight=False)
    yield Static(id="stream")
    yield OptionList(id="palette")   # hidden by default; CSS below
    yield Input(id="prompt", placeholder="agent86> ")
    yield StatusFooter(id="status")

CSS = """
#palette {
    display: none;
    max-height: 10;   # cap so a long command list doesn't push the footer off-screen
    border: round $accent;
}
"""

def on_mount(self) -> None:
    ...
    self.query_one("#palette", OptionList).display = False

def on_input_changed(self, event: Input.Changed) -> None:
    if event.input.id != "prompt":
        return
    self._sync_palette(event.value)

def _sync_palette(self, text: str) -> None:
    palette = self.query_one("#palette", OptionList)
    if not text.startswith("/"):
        palette.display = False
        return
    matches = [c for c in COMMANDS if c.name.startswith(text)]
    if not matches:
        palette.display = False
        return
    palette.clear_options()
    for c in matches:
        palette.add_option(Option(f"{c.name}  [dim]{c.description}[/dim]", id=c.name))
    palette.display = True
    palette.highlighted = 0
```
Source pattern verified via Context7 `/textualize/textual`: `OptionList.add_options`/`clear_options`,
`display: none`/`display: block` semantics (`docs/styles/display.md` — "removes it from layout,
no space reserved," which is exactly what's wanted here so the palette doesn't reserve blank
space while hidden).

### Pattern 3: Priority `Binding`s to route Up/Down/Enter/Escape to the open palette
**What:** Register `Binding("up", "palette_up", priority=True)`,
`Binding("down", "palette_down", priority=True)`, `Binding("enter", "palette_select",
priority=True)`, `Binding("escape", "palette_dismiss", priority=True)` on `Agent86App.BINDINGS`.
Each `action_palette_*` checks `self.query_one("#palette", OptionList).display` first; if the
palette is hidden, the action is a no-op (falls through — Input's own Enter-submits and
Up/Down-does-nothing behavior is untouched since `Input` has no bound `up`/`down` actions and
priority bindings only pre-empt *bindings*, not raw character insertion for keys `Input` doesn't
bind).
**When to use:** This is the mechanism for D-06 (arrow-key navigation of the palette while the
`#prompt` Input keeps focus and keeps receiving character keys for filtering).
**Example:**
```python
# Source: Textual docs/guide/input.md — "Priority bindings... checked prior to the bindings of
# the focused widget... cannot be disabled by binding the same key on a widget." Textual's own
# App.BINDINGS uses this exact mechanism for ctrl+q.
BINDINGS = [
    Binding("shift+tab", "cycle_mode", "cycle approval mode"),
    Binding("up", "palette_up", show=False, priority=True),
    Binding("down", "palette_down", show=False, priority=True),
    Binding("enter", "palette_select", show=False, priority=True),
    Binding("escape", "palette_dismiss", show=False, priority=True),
]

def action_palette_up(self) -> None:
    palette = self.query_one("#palette", OptionList)
    if palette.display:
        palette.action_cursor_up()

def action_palette_select(self) -> None:
    palette = self.query_one("#palette", OptionList)
    if not palette.display:
        return  # let Input's own Enter -> Input.Submitted proceed (D-11)
    # ... resolve highlighted option, run or chain to a picker, then hide palette
```
**Confidence caveat (MEDIUM):** `enter` is the one key `Input` *does* natively bind (to submit).
Whether an `action_palette_select` that is a no-op when the palette is hidden truly lets
`Input.Submitted` still fire afterward — or whether declaring the App-level `enter` binding at all
changes `Input`'s internal dispatch — needs a **wave-0 spike test** (a `Pilot` test: type a full
command with the palette *not* showing, press enter, assert `on_input_submitted` still ran)
before the rest of the palette is built on top of it. If it does not fall through cleanly, the
fallback is to *not* bind `enter` at the App level at all, and instead detect Enter-with-palette-
open a different way (e.g. have the palette itself hold focus only while navigating — see
Alternatives Considered).

### Pattern 4: `/mode` as `RadioSet`, `/model` as `OptionList`-in-`ModalScreen`
**What:** Mirror `ApprovalModal(ModalScreen[bool])` exactly, but typed `ModalScreen[str | None]`
(`None` = cancelled/Escape).
**Example:**
```python
# tui/screens/mode_picker.py
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import RadioButton, RadioSet, Label

class ModePickerModal(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Container(id="mode-picker-dialog"):
            yield Label("Approval mode")
            with RadioSet(id="mode-options"):
                for value in ("ask", "auto", "deny"):
                    yield RadioButton(value, value=(value == self._current))

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        self.dismiss(str(event.pressed.label))

    def action_cancel(self) -> None:
        self.dismiss(None)
```
```python
# tui/screens/model_picker.py — OptionList variant (list can be long; RadioSet is meant for
# small, always-visible choice sets per Textual docs, OptionList scrolls and supports many items)
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

class ModelPickerModal(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, choices: list[tuple[str, str]]) -> None:  # (label, value) pairs
        super().__init__()
        self._choices = choices

    def compose(self) -> ComposeResult:
        with Container(id="model-picker-dialog"):
            yield Label("Switch model")
            yield OptionList(*[Option(label, id=value) for label, value in self._choices])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)
```
Source verified via Context7 `/textualize/textual`: `RadioSet.Changed` message + `pressed_button`
(`docs/widgets/radioset.md`, `src/textual/widgets/_radio_set.py`), `OptionList.OptionSelected`
(`docs/widgets/option_list.md`), `ModalScreen` push/dismiss pattern already proven in this repo
by `ApprovalModal` + `tests/tui/test_app.py::_run_approval_case`.

### Pattern 5: Menu chaining from a palette selection (D-10)
**What:** When the palette's highlighted/selected entry has `needs_choice` set, do **not** call
`entry.handler` directly — instead `push_screen` the corresponding picker with a callback that,
on a non-`None` result, synthesizes the full command string and runs it through the *existing*
`handle_command` path (so behavior/state-mutation is identical to typing it).
**Example:**
```python
def _run_or_chain(self, entry: CommandEntry) -> None:
    self._hide_palette()
    if entry.needs_choice == "mode":
        self.push_screen(ModePickerModal(self.repl.harness.gate.mode.value), self._on_mode_picked)
    elif entry.needs_choice == "model":
        choices = _model_choices(self.repl.cfg)  # see Don't Hand-Roll / model list section below
        self.push_screen(ModelPickerModal(choices), self._on_model_picked)
    else:
        self._dispatch_line(entry.name)  # runs entry.handler via handle_command, same as typed

def _on_mode_picked(self, value: str | None) -> None:
    if value is not None:
        self._dispatch_line(f"/mode {value}")

def _on_model_picked(self, value: str | None) -> None:
    if value is not None:
        self._dispatch_line(f"/model {value}")

def _dispatch_line(self, line: str) -> None:
    # identical body to the top of on_input_submitted, minus reading from the Input widget
    ...
```
This keeps `CommandResult`/`handle_command` as the single execution path regardless of whether
the command came from typing or the palette — satisfying D-05 ("reuse the existing
`CommandResult` contract") without a second code path to keep in sync.

### Anti-Patterns to Avoid
- **Duplicating command metadata between `_help_table()` and the palette:** the whole point of
  D-04 is one list. If `_help_table` is left as hand-written Rich `Table.add_row` calls separate
  from `COMMANDS`, the two will drift the first time a command is added — generate the help table
  from `COMMANDS` (Pattern 1).
- **Absolute-position/`layer` overlay for the dropdown when a sibling-widget-in-flow works:**
  adds CSS complexity (z-order, coordinate math) for no benefit given this app's layout (there is
  natural room above `#prompt`, below `#transcript`/`#stream`).
- **Building a second "menu dispatch" path that bypasses `handle_command`:** every picker
  selection must resolve to a synthesized command string run through the same `handle_command`
  (Pattern 5) — never call `repl.harness.set_model`/`gate.mode = ...` directly from a picker
  callback, or the palette path and the typed path can silently diverge.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Arrow-key list navigation, wraparound, highlight tracking | A custom keyboard-navigable list widget | `OptionList` (`action_cursor_up`/`action_cursor_down`, `highlighted`, `OptionSelected`) | Core Textual widget, already handles focus, scrolling for long lists, and highlight state |
| Single-choice radio-style picker | Custom toggle-button group | `RadioSet` + `RadioButton` | Purpose-built, emits `Changed` with `pressed_button`/`pressed_index`, used correctly is less code than a hand-rolled group |
| Modal dialog show/resolve/dismiss lifecycle | A custom "overlay screen" abstraction | `ModalScreen[T]` (already proven by `ApprovalModal` in this repo) | `push_screen(screen, callback)` + `dismiss(value)` is the established, tested pattern in this codebase for exactly this shape of interaction |
| App-level hotkey that must pre-empt a focused widget's own key handling | Manual event interception / monkeypatching `Input._on_key` | `Binding(..., priority=True)` | Documented, public API (`docs/guide/input.md`); private `_on_key` overriding is unsupported surface |

**Key insight:** Every widget this phase needs already exists in Textual core (installed 8.2.8,
pinned `>=1.0`). The actual novelty in this phase is entirely in *wiring* — the registry
refactor, the show/hide + filter logic for the dropdown, and getting priority-binding key routing
right — not in building new UI primitives.

## Common Pitfalls

### Pitfall 1: Registry refactor silently changes a match (exact vs. prefix)
**What goes wrong:** The original dispatch uses per-command match rules (`line == "/mode" or
line.startswith("/mode ")` vs. `line == "/help"` exact-only). A naive `line.split(" ", 1)`-based
registry lookup is behavior-equivalent for every current command, but a *future* command whose
name is a prefix of another's (there are none today) would silently misroute. Also: multiple
spaces (`"/model  foo"`) or a trailing space with no argument (`"/model "` — handled today via
`line.startswith("/model ")` giving `arg=""`) must still produce the same `CommandResult`.
**Why it happens:** Refactoring string-branch logic into structured lookup is exactly the kind of
change that "looks equivalent" but has edge-case gaps.
**How to avoid:** Port `tests/tui/test_commands.py` unchanged as the regression harness (it
already exercises `/mode`, `/model`, `/clear`, unknown commands, bare `/mode`/`/model`); add a
parametrized case for "/model" vs "/models" and for trailing-whitespace argument forms.
**Warning signs:** Any existing `test_commands.py` test failing after the registry refactor —
treat as a hard blocker, not a "close enough."

### Pitfall 2: Enter key ambiguity between palette-select and Input-submit
**What goes wrong:** With a priority `enter` binding, pressing Enter while the palette is *closed*
must still let `Input.Submitted` fire normally (typed commands + turns, D-11). If the
`action_palette_select` no-op doesn't cleanly "fall through" to Input's normal Enter handling, the
whole app's submit path breaks — including plain conversational turns, not just commands.
**Why it happens:** Priority bindings intercept **before** the focused widget's own handling;
whether a no-op action still permits Input's default behavior to run afterward, or whether the
binding fully consumes the event once matched, depends on Textual's exact event-consumption
semantics.
**How to avoid:** A wave-0 spike/smoke test (Pilot: type plain text with no leading `/`, press
Enter, assert a turn started) run *before* building anything on top of the `enter` priority
binding. If it doesn't fall through, restrict the App-level `enter` binding registration to only
happen (e.g. dynamically add/remove the binding) while the palette is actually visible, rather
than a permanent binding with an internal no-op guard.
**Warning signs:** Any `tests/tui/test_app.py` or `tests/tui/test_commands.py`-style Pilot test
that submits plain text and expects `action == "turn"` starts failing once the palette bindings
land.

### Pitfall 3: Dropdown consumes vertical space and pushes the footer
**What goes wrong:** If `#palette` is given `height: auto` with no `max-height`, a long filtered
list (all 11 commands, unfiltered on bare `/`) could grow tall enough to shove `StatusFooter` or
even `#prompt` out of the visible viewport in a small terminal window.
**Why it happens:** `RichLog#transcript` is `1fr` (flexible) but the palette, prompt, and footer
are effectively fixed/auto height competing for the remaining space.
**How to avoid:** Cap `#palette` with `max-height` in CSS (Pattern 2 example) so it scrolls
internally past a handful of visible rows instead of growing unbounded.
**Warning signs:** Visual regression in a small terminal (manual UAT); `OptionList` overflowing
without a `max-height` is straightforward to catch during Windows Terminal manual verification
(consistent with the Phase 1 pattern of a manual-verification checklist).

### Pitfall 4: `/mode` picker option comparison via `RadioButton.label` string vs. `ApprovalMode` enum
**What goes wrong:** `RadioSet.Changed.pressed.label` is a Rich `Text`/renderable, not a plain
`str` — `str(event.pressed.label)` round-trips correctly for plain ASCII labels ("ask"/"auto"/
"deny") but is a place a careless `==` comparison against the enum member (not its `.value`)
could silently never match.
**Why it happens:** `RadioButton` labels are display-oriented; mixing display and value semantics
is an easy trap.
**How to avoid:** Keep mode picker option labels as the exact lowercase strings `parse_mode`
already accepts ("ask", "auto", "deny") and route the picker's result string straight back
through `_set_mode`/`parse_mode`, never comparing against `ApprovalMode` members directly in the
picker.
**Warning signs:** `/mode` selection via the picker silently not changing `gate.mode`.

## Code Examples

### Filtering the palette as the user types (verified against installed OptionList API)
```python
# Source: Context7 /textualize/textual — OptionList.clear_options()/add_option()/add_options(),
# OptionList.OptionHighlighted/OptionSelected (docs/widgets/option_list.md)
def _sync_palette(self, text: str) -> None:
    palette = self.query_one("#palette", OptionList)
    if not text.startswith("/") or " " in text:
        # once the user has typed past the command name (a space), the palette should not
        # keep suggesting — they're now typing an argument for a typed command (D-11 path)
        palette.display = False
        return
    matches = [c for c in COMMANDS if c.name.startswith(text)]
    palette.display = bool(matches)
    if matches:
        palette.clear_options()
        palette.add_options(
            Option(f"{c.name}  [dim]{c.description}[/dim]", id=c.name) for c in matches
        )
        palette.highlighted = 0
```

### Modal picker push/dismiss (mirrors existing `ApprovalModal` usage in `app.py`)
```python
# Source: existing src/agent86/tui/app.py::on_approval_request — proven pattern, same shape
def _open_mode_picker(self) -> None:
    self.push_screen(
        ModePickerModal(self.repl.harness.gate.mode.value),
        self._on_mode_picked,
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Flat if/else `handle_command` dispatch, hand-written `_help_table` | Declarative `CommandEntry` registry backing dispatch + palette + help | This phase | `/help` and the palette can never drift; adding a command becomes one list entry instead of three separate edits |
| Typed-only slash-commands (Phase 1) | Typed commands **and** an arrow-key palette/menus, additive | This phase (TUI-03/04) | No behavior change for existing muscle memory; new discoverability + choice-driven UX |

**Deprecated/outdated:** Nothing in this codebase is being deprecated — the palette is additive
per D-11.

## Open Questions

1. **Does a priority `enter` `Binding` at the App level still let `Input.Submitted` fire when the
   binding's action is a no-op (palette hidden)?**
   - What we know: Priority bindings are checked before the focused widget's own bindings
     (documented, HIGH confidence). `Input` handles Enter as `Input.Submitted` internally.
   - What's unclear: Whether Textual's key-dispatch, once a priority binding *matches* the key
     (regardless of what its action body does), still lets `Input`'s own Enter handling run
     afterward, or whether matching the binding fully consumes the event.
   - Recommendation: Wave-0 spike test (Pilot: submit plain text with palette closed, assert
     `Input.Submitted` still reaches `on_input_submitted`) before building the rest of the palette
     on this mechanism. If it doesn't fall through, dynamically bind/unbind `enter` only while the
     palette is visible (Textual supports adding/removing bindings at runtime via
     `App.bind`/`refresh_bindings`, or simpler: track palette-open state and have
     `on_input_submitted` itself check "was the palette open at Enter-press time" using an
     `Input.Changed`-tracked flag rather than a competing `enter` binding at all).

2. **Fuzzy vs. prefix filtering for the palette (D-13, Claude's discretion).**
   - What we know: The existing 11 commands are short and distinct; simple `str.startswith`
     filtering (Pattern 2/Code Examples) is sufficient and trivially correct.
   - What's unclear: Whether Phase 3/4 will add enough commands that prefix-only filtering feels
     limiting.
   - Recommendation: Ship `startswith` filtering this phase (simplest, zero new dependency,
     easiest to test); revisit fuzzy matching only if a future phase's command count makes it
     necessary.

3. **`/model` picker list composition when only defaults are configured (D-12).**
   - What we know: `ModelConfig` always has non-empty `default`/`route.cheap`/`route.frontier`
     strings (pydantic defaults), so the picker list is never empty in practice with today's
     schema — the D-12 "fall back to prefilling `/model `" path is a defensive branch, not a
     commonly hit one.
   - What's unclear: Whether to also surface providers from `cfg.providers` that have no role
     slot (e.g. `groq`, `llamacpp` configured but not used in any role) — these have no known
     *model name* (only a provider), so they can't produce a valid `provider:model` picker entry
     without guessing a model string.
   - Recommendation: Build the picker list from the three role slots only (dedup by
     `provider:model` string, label with the role name(s), e.g. "default, route.cheap" if two
     roles share a ref), which is exactly the "reasonable approach" D-12 names. Do not attempt to
     synthesize entries for providers with no role reference — that's Phase 3's per-provider
     catalog's job.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.2+ with `pytest-asyncio` (`asyncio_mode = "auto"`), Textual's `App.run_test()` / `Pilot` harness |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `pytest tests/tui/ -x -q` |
| Full suite command | `pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TUI-03 (criterion 1) | Typing `/` shows a filtering `OptionList` with name+description; selecting one runs it | integration (Pilot) | `pytest tests/tui/test_palette.py::test_palette_filters_and_selects -x` | ❌ Wave 0 |
| TUI-03 (criterion 1) | `/help` output is generated from the same `COMMANDS` registry the palette uses (no drift) | unit | `pytest tests/tui/test_commands.py::test_help_matches_registry -x` | ❌ Wave 0 (extend existing file) |
| TUI-04 (criterion 2) | Selecting `/model` in the palette opens an `OptionList` picker; selecting an entry calls `/model <ref>` | integration (Pilot) | `pytest tests/tui/test_palette.py::test_model_command_chains_to_picker -x` | ❌ Wave 0 |
| TUI-04 (criterion 2) | Selecting `/mode` in the palette opens a `RadioSet` picker; selecting an entry calls `/mode <value>` | integration (Pilot) | `pytest tests/tui/test_palette.py::test_mode_command_chains_to_picker -x` | ❌ Wave 0 |
| TUI-03/04 (criterion 3) | Typed full commands (`/model ollama:llama3.1`, `/mode auto`, etc.) still work unchanged with the palette present | regression | `pytest tests/tui/test_commands.py -x` (existing file, must stay green unmodified in behavior) | ✅ (extend, don't break) |
| TUI-03/04 (criterion 3) | Plain-text turn submission (no leading `/`) still reaches `on_input_submitted`/starts a turn with priority bindings registered | integration (Pilot) | `pytest tests/tui/test_app.py::test_turn_streams_and_footer_goes_live_then_idle -x` (existing — must stay green) | ✅ |
| Packaging (CLAUDE.md constraint) | `agent86.cli` import still never imports `textual` | regression | `pytest tests/tui/test_lazy_import.py -x` (existing — untouched by this phase) | ✅ |

### Sampling Rate
- **Per task commit:** `pytest tests/tui/ -x -q`
- **Per wave merge:** `pytest -q` (full suite, currently 178 tests before this phase)
- **Phase gate:** Full suite green before `/gsd:verify-work`, plus the Open Question 1 spike
  resolved (either priority-binding fallthrough confirmed, or the dynamic bind/unbind fallback
  implemented and tested) before building the rest of the palette on top of it.

### Wave 0 Gaps
- [ ] `tests/tui/test_palette.py` — new file covering dropdown open/filter/select, and both
  picker chains (`/model`, `/mode`)
- [ ] `tests/tui/test_commands.py::test_help_matches_registry` — new test asserting `_help_table`
  content is generated from `COMMANDS`, not hand-maintained separately
- [ ] Spike/smoke test for Open Question 1 (priority `enter` binding + Input.Submitted
  fallthrough) — write this **first**, before the palette's Enter-handling is implemented, so the
  key-routing approach is chosen with evidence rather than assumption
- [ ] `tests/tui/screens/` (new dir) or keep picker-modal tests alongside `test_app.py` — mirror
  how `ApprovalModal` is tested in-place today (no separate `test_approval.py` exists; palette
  picker tests can similarly live in `test_palette.py` rather than needing a new screens test dir)

## Sources

### Primary (HIGH confidence)
- Context7 `/textualize/textual` — `docs/widgets/option_list.md` (`OptionList` messages,
  `add_options`/`clear_options`), `docs/widgets/radioset.md` + `src/textual/widgets/_radio_set.py`
  (`RadioSet.Changed`, `pressed_button`/`pressed_index`), `docs/widgets/input.md` (`Input.Changed`/
  `Input.Submitted`/reactive `value`/`cursor_position`), `docs/guide/input.md` (priority
  `Binding`s), `docs/styles/display.md` (`display: none` layout semantics), `docs/styles/layer.md`
  + `docs/css_types/position.md` (absolute overlay alternative, not chosen)
- Local codebase (read directly): `src/agent86/tui/commands.py`, `src/agent86/tui/app.py`,
  `src/agent86/tui/screens/approval.py`, `src/agent86/config.py`, `src/agent86/guardrails/policy.py`,
  `src/agent86/orchestration/loop.py`, `src/agent86/types.py`, `pyproject.toml`,
  `tests/tui/test_app.py`, `tests/tui/test_commands.py`, `tests/tui/test_lazy_import.py`,
  `tests/tui/conftest.py`
- `python -c "import textual; print(textual.__version__)"` run in this environment — confirms
  8.2.8 installed against the `>=1.0` pin

### Secondary (MEDIUM confidence)
- WebFetch of `github.com/darrenburns/textual-autocomplete/blob/main/README.md` — confirms a
  purpose-built alternative exists and its API shape (`AutoComplete`, `get_candidates`,
  `DropdownItem`, `apply_completion`), used here only to inform the "Alternatives Considered"
  entry, not adopted (D-01 locks a custom build)

### Tertiary (LOW confidence)
- None relied upon as authoritative — the one genuinely uncertain claim (priority-binding +
  `Input.Submitted` interaction) is flagged explicitly as Open Question 1 with a concrete spike
  test recommendation rather than asserted as fact.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependency; every widget referenced verified via Context7 against
  the actually-installed Textual version (8.2.8)
- Architecture: HIGH for widget composition/registry refactor; MEDIUM for the specific
  priority-binding + `Input.Submitted` interaction (Open Question 1) — this is the one item the
  plan should schedule as a wave-0 spike before committing to the full palette build
- Pitfalls: HIGH — pitfalls 1, 3, 4 are directly inferable from reading the existing code and
  Textual's documented widget semantics; pitfall 2 is the same uncertainty as Open Question 1

**Research date:** 2026-07-19
**Valid until:** 30 days (stable domain — Textual core widget APIs; re-verify if the installed
Textual version changes materially, e.g. a major version bump)
