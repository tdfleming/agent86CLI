# Phase 2: Command Palette + Menus - Context

**Gathered:** 2026-07-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the hand-parsed slash-command strings in the TUI with an **autocompleting command
palette** (TUI-03) and **arrow-key selectable menus** for commands that need a choice (TUI-04).

**In scope:** A `/`-triggered inline autocomplete dropdown in the Textual app; a declarative
command registry that powers the palette, menus, and `/help`; arrow-key choice menus for
`/model` and `/mode`; keeping every existing slash-command reachable with behavior unchanged.

**Out of scope:** Keyring + model/provider add/test config write-back (Phase 3), MCP config UI
(Phase 4), lazy-import packaging/hardening & release (Phase 5), theming (v2). This phase does not
modify the harness, cognitive loop, providers, or config schema — it is a presentation layer over
the existing `handle_command` dispatch.
</domain>

<decisions>
## Implementation Decisions

### Palette trigger & presentation
- **D-01:** Build a **custom `/`-triggered inline dropdown** — typing `/` in the prompt opens an
  autocomplete list (a Textual `OptionList`) rendered below/over the input that filters as the
  user types. This is the primary palette, chosen for the most Claude-Code-like feel.
- **D-02:** Do **not** rely on Textual's built-in command palette (Provider system / Ctrl+P) as
  the primary surface. (A Ctrl+P registration is not required this phase; the `/` dropdown is the
  contract.)
- **D-03:** Each palette entry shows the command **name and its description** (success criterion
  1). Selecting an entry runs it.

### Command registry (single source of truth)
- **D-04:** Refactor to a **declarative command registry** — each command becomes a registry
  entry carrying at minimum: name, description, handler, and a flag/spec for whether it needs a
  choice (and what choices). This registry is the single source of truth feeding the palette, the
  choice menus, and `/help`.
- **D-05:** The registry must reproduce the existing dispatch behavior branch-for-branch
  (`/help /config /models /model /tools /skills /memory /mode /cost /clear /exit`). Behavior is
  unchanged; only the surfacing changes. Reuse the existing `CommandResult` contract in
  `tui/commands.py` rather than inventing a new return type.

### Arrow-key menus (TUI-04)
- **D-06:** The autocompleting palette **is itself the primary arrow-key selector** — users
  navigate/select commands with arrow keys + Enter.
- **D-07:** Add a dedicated **`/model` picker** as an arrow-key `OptionList` of models to switch
  to (no typing `provider:model` required).
- **D-08:** Add a dedicated **`/mode` picker** as an arrow-key `RadioSet` for `ask` / `auto` /
  `deny`.
- **D-09:** Only commands that genuinely need an argument get a dedicated choice menu this phase
  (i.e. `/model` and `/mode`). Commands that already act with no argument keep running directly.

### Argument flow
- **D-10:** When a palette command needs an argument, **selecting it chains straight into its
  choice menu** (e.g. selecting `/model` opens the model picker; selecting `/mode` opens the mode
  picker). Fully menu-driven — no intermediate typing required. This directly satisfies success
  criterion 2.

### Backward compatibility
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
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The seam to evolve (command dispatch)
- `src/agent86/tui/commands.py` — `handle_command` (the if/else dispatch to refactor into a
  registry), `CommandResult` (reuse this contract), `_help_table`, `_models_tables`, `_set_mode`,
  `_set_model`, `_show_cost`, `_show_memory`, `startup_notes`. This is the primary reference.
- `src/agent86/tui/app.py` — `Agent86App.on_input_submitted` (where input is dispatched today and
  where the `/` dropdown + menu chaining must integrate), `compose`/`on_mount` (widget layout),
  the `#prompt` Input and `#stream` Static, existing `BINDINGS` and CSS.

### Menu/choice data sources
- `src/agent86/config.py` — `Config`, `providers`, model roles (`model.default`,
  `model.route.cheap`, `model.route.frontier`) used to build the `/model` picker list; `UIConfig`.
- `src/agent86/guardrails/policy.py` — `cycle_mode`, `parse_mode` (drive the `/mode` picker
  values: ask/auto/deny).
- `src/agent86/orchestration/loop.py` — `Harness.set_model`, `provider`, `gate` (`.mode`), used by
  `/model` and `/mode` handlers.
- `src/agent86/types.py` — `ModelRef` (parse/validate model refs for the picker), `ApprovalMode`.

### Prior phase decisions (patterns to honor)
- `.planning/phases/01-tui-skeleton-live-status-line/01-CONTEXT.md` — Textual-only-in-`tui/`
  constraint, layout, reuse-of-`_Repl` pattern, `run --json`/plain-loop must stay green.
- `src/agent86/tui/screens/approval.py` — existing `ModalScreen[bool]` pattern to mirror if any
  menu is implemented as a modal screen.

### Packaging constraint
- `pyproject.toml` — Textual is a core-but-lazy dep; nothing new should break the lazy-import
  cold-start guarantee (no Textual import in `cli.py` at module load).

No external specs/ADRs — requirements are fully captured in the decisions above and the roadmap.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tui/commands.py::CommandResult` + `handle_command` — the dispatch to refactor; keep the
  `action`/`render` contract so `app.py` integration is minimal.
- `tui/screens/approval.py::ApprovalModal` — `ModalScreen[bool]` pattern to mirror for any menu
  rendered as a modal.
- `ui/status.py` reactive status + `StatusFooter` widget — unchanged; menus/palette must keep the
  footer status refresh calls that `on_input_submitted` already performs.

### Established Patterns
- All Textual code is isolated in `src/agent86/tui/`; `ui/repl.py` and the plain loop are never
  touched (Phase 1 lock).
- Commands return renderables via `CommandResult` rather than printing — the palette/menu layer
  must preserve this so transcript output is unchanged.
- Widgets are queried by id (`#prompt`, `#transcript`, `#stream`, `#status`) and CSS lives on the
  `Agent86App` class.

### Integration Points
- `Agent86App.on_input_submitted` — detect a leading `/` to open the dropdown; route menu
  selections back through `handle_command`/handlers; keep the typed-command path intact.
- `Agent86App.compose`/CSS — add the dropdown `OptionList` and any menu widgets to the layout.
- The registry becomes the new backing store for `_help_table` so `/help` and the palette never
  drift.
</code_context>

<specifics>
## Specific Ideas

- Feel target: Claude-Code-like — type `/`, see a filtering list of commands with descriptions,
  arrow to one, Enter to run; if it needs a choice (model/mode), Enter chains straight into an
  arrow-key picker. No `provider:model` typing required, but typing still works for power users.
- Keep the palette/menu additions inside the Phase 1 layout without disturbing the live footer or
  the streaming line.
</specifics>

<deferred>
## Deferred Ideas

- Per-provider model catalog + add/test/save model config → Phase 3 (MODEL-01/02, SEC-01). The
  `/model` picker this phase lists what today's config already knows.
- MCP server list/add/remove menus → Phase 4 (MCP-01).
- Ctrl+P / fuzzy global command palette via Textual's Provider system → not required; could be a
  future polish item if the `/` dropdown proves insufficient.
- Theming / color schemes for the palette → v2 (POL-01).
</deferred>

---

*Phase: 02-command-palette-menus*
*Context gathered: 2026-07-20*
