# Phase 2: Command Palette + Menus - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-20
**Phase:** 02-command-palette-menus
**Areas discussed:** Palette style, Command registry, Menus, Argument flow, Model list source, Typed-command compatibility

---

## Palette style

| Option | Description | Selected |
|--------|-------------|----------|
| Custom `/`-triggered dropdown | Typing `/` opens an inline autocomplete OptionList that filters as you type; most Claude-Code-like, more custom code | ✓ |
| Textual built-in palette | Reuse native command palette (Provider system, Ctrl+P), fuzzy search, less code but Ctrl+P trigger | |
| Both / hybrid | `/` dropdown plus Textual palette registration for Ctrl+P | |

**User's choice:** Custom `/`-triggered dropdown
**Notes:** Prioritized the Claude-Code-like feel of typing `/` over reusing Textual's Ctrl+P palette.

---

## Command registry

| Option | Description | Selected |
|--------|-------------|----------|
| Declarative command registry | Each command → registry entry (name, description, handler, needs-choice); single source of truth for palette, menus, /help | ✓ |
| Minimal metadata layer | Keep handle_command as-is; add a small (name, description) list beside it | |

**User's choice:** Declarative command registry
**Notes:** Accepts touching all commands to avoid two-places-to-sync drift.

---

## Menus (which commands become arrow-key menus, and widget) — multi-select

| Option | Description | Selected |
|--------|-------------|----------|
| /model picker (OptionList) | Selecting /model opens arrow-key list of models instead of typing provider:model | ✓ |
| /mode picker (RadioSet) | Selecting /mode opens arrow-key ask/auto/deny chooser | ✓ |
| Palette itself is the menu | Palette is the primary arrow-key selector; per-command menus only where an arg is genuinely needed | ✓ |

**User's choice:** All three
**Notes:** Palette is the primary selector; /model and /mode get dedicated choice menus.

---

## Argument flow

| Option | Description | Selected |
|--------|-------------|----------|
| Chain into a choice menu | Selecting /model immediately opens the model picker; fully menu-driven | ✓ |
| Prefill the input | Selecting /model drops "/model " into the prompt to type the argument | |
| You decide | Claude chooses per-command during planning | |

**User's choice:** Chain into a choice menu

---

## Model list source (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Role models + known refs | List configured role models (default/cheap/frontier) + any refs in config | |
| Providers, then type model | Picker lists providers; then type model name | |
| You decide | Claude picks cleanest source, consistent with Phase 3 expansion | ✓ |

**User's choice:** You decide (Claude's discretion — see D-12)

---

## Typed-command compatibility (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — keep typed dispatch | Palette/menus additive; typing full commands still runs them; existing tests stay green | ✓ |
| Palette-only | Remove typed dispatch; single path but breaks typed-command tests/muscle memory | |

**User's choice:** Yes — keep typed dispatch

---

## Claude's Discretion

- Source/shape of the `/model` picker list (D-12).
- Dropdown widget styling, positioning, filter/fuzzy-match algorithm, Esc-to-dismiss, and visual
  coexistence with the streaming line (D-13).

## Deferred Ideas

- Per-provider model catalog + add/test/save → Phase 3.
- MCP server menus → Phase 4.
- Ctrl+P global fuzzy palette via Textual Provider system → optional future polish.
- Palette theming → v2.
