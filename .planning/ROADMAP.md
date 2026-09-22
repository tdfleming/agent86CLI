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

Added 2026-09-22, and the strongest candidates for the next milestone: the seven **competitive
gaps** in § Backlog below (phases 999.1–999.7) — `grep`/`glob` built-ins, tool hooks, declarative
sub-agents, a plan-mode gate, git awareness, shell network control, and an injection classifier.
Analysis for each: [../docs/BACKLOG.md](../docs/BACKLOG.md) § "Competitive gaps 2026-09-22".
**None of them outranks MCP integration work.**

Start the next one with `/gsd:new-milestone`, which gathers fresh requirements — this
milestone's `REQUIREMENTS.md` is archived and removed, by design.

## Backlog

Unsequenced parking lot (999.x). Added 2026-09-22 from a competitive read of Claude Code and
Antigravity. Full analysis for every item: [../docs/BACKLOG.md](../docs/BACKLOG.md) §
"Competitive gaps 2026-09-22".

**Standing constraint:** none of these outranks MCP integration work, which is now recorded as
999.0 below. They are ordered *among themselves*; MCP sits above the whole block.

Prioritised order — 999.0 → 999.1 → 999.2 → 999.3 → 999.4, then the rest unordered.

### Phase 999.0: MCP integration work (BACKLOG — scope TBD)

**Goal:** Unwritten. Ranked above every other backlog item by standing instruction (2026-09-22),
but no scope was given with it, and MCP is already complete against `docs/ARCHITECTURE.md` — so
the intent is not inferable from the code. **Do not promote this until the scope is written.**
**Requirements:** TBD — see [../docs/BACKLOG.md](../docs/BACKLOG.md) § 999.0 for what already
exists, so it is not rebuilt by accident.
**Plans:** 0 plans

Plans:
- [ ] TBD (define the scope first, then promote with /gsd:review-backlog)

### Phase 999.1: Codebase intelligence — `grep` / `glob` built-in tools (BACKLOG)

**Goal:** Give the agent first-class search so "where is this defined?" stops routing through
approval-gated, platform-variable `run_command`.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.2: PreToolUse / PostToolUse hook events (BACKLOG)

**Goal:** An extension point between the loop and the outside world — and the deterministic
policy gate Tier 5 wants, instead of regex scanners carrying the whole story.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.3: Declarative sub-agents — `.agent86/agents/*.md` (BACKLOG)

**Goal:** Check-in-able agent definitions (Markdown + YAML front matter: model, tool allowlist,
permission mode, isolation) so `delegate` stops being dynamic-only and unreproducible.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.4: Plan-mode gate — approve one plan, not forty diffs (BACKLOG)

**Goal:** A read-only planning phase whose output is reviewed and approved once, before any
file changes — a strategic gate above the existing per-call tactical one.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.5: Git awareness — checkpoint/rewind, worktree isolation, diff surface (BACKLOG)

**Goal:** Treat the worktree as the unit of agent isolation: checkpoints, rewind, per-sub-agent
worktrees, and a diff/stage/commit surface.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.6: Network control around `run_command` (BACKLOG)

**Goal:** Close the gap where the SSRF guard protects `web_fetch` only and the shell has
unrestricted network. OS-native primitives; gVisor/WASM stay non-goals.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.7: Model-based prompt-injection classifier (BACKLOG)

**Goal:** A second model over proposed actions in auto mode, above the regex ingress/egress
scanners — with the ceiling stated honestly.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)
