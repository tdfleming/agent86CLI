# Roadmap: agent86

## Milestones

- **v0.6 Interactive** — Phases 1-5 — shipped 2026-09-19
- **v0.7 Trustworthy Harness** — Phase 6 — shipped 2026-09-19
- **v0.8 Context & Cost** — Phase 7 — shipped 2026-09-19
- **v0.9 Coding-Agent UX** — Phase 8 — shipped 2026-09-21
- **v1.0 Release** — Phase 9 — shipped 2026-09-21, published to PyPI

Full detail for all five: [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md) ·
requirements: [milestones/v1.0-REQUIREMENTS.md](milestones/v1.0-REQUIREMENTS.md) ·
narrative: [MILESTONES.md](MILESTONES.md)

## Phases

<details>
<summary>v0.6 -> v1.0 (Phases 1-9) — SHIPPED 2026-09-21</summary>

| Phase | Milestone | Plans | Status | Completed |
|---|---|---|---|---|
| 1. TUI Skeleton + Live Status Line | v0.6 | 5/5 | Complete | 2026-07-20 |
| 2. Command Palette + Menus | v0.6 | 4/4 | Complete | 2026-07-20 |
| 3. Secrets + Model/Provider Config | v0.6 | 13/13 | Complete | 2026-08-06 |
| 4. MCP Config UI | v0.6 | 8/8 | Complete | 2026-08-06 |
| 5. Packaging & Hardening | v0.6 | direct | Complete | 2026-09-19 |
| 6. Trustworthy Harness | v0.7 | direct | Complete | 2026-09-19 |
| 7. Context & Cost | v0.8 | direct | Complete | 2026-09-19 |
| 8. Coding-Agent UX | v0.9 | direct | Complete | 2026-09-21 |
| 9. Release | v1.0 | direct | Complete | 2026-09-21 |

"direct" marks a phase executed as a coordinated subagent pass rather than as numbered
GSD plans; each still carries a `SUMMARY.md` in `phases/`.

</details>

## Next

No milestone is planned. Post-1.0 candidates are recorded in
[../docs/BACKLOG.md](../docs/BACKLOG.md) — click-to-toggle tool blocks, plain-loop history
navigation, a read/write split in the workspace jail, a compaction-quality eval, Ollama
`num_ctx` auto-sizing, and a per-turn `/cost` breakdown.

Start the next one with `/gsd:new-milestone`, which gathers fresh requirements — this
milestone's `REQUIREMENTS.md` is archived and removed, by design.
