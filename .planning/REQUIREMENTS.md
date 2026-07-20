# Requirements: agent86 Interactive Milestone (v0.6)

**Defined:** 2026-07-19
**Core Value:** The user can run, configure, and steer the agent entirely from within an
interactive terminal app — switching models, wiring up MCP servers, and watching live progress —
without hand-editing TOML or restarting.

## v1 Requirements

Requirements for the v0.6 interactive milestone. Each maps to exactly one roadmap phase.

### TUI (full-screen app)

- [ ] **TUI-01**: A full-screen Textual app launches as the default interactive UI (no
      subcommand), with a scrollable transcript, a prompt input, and a footer status bar
- [ ] **TUI-02**: The status bar stays live and updates model, context %, tokens, cost, and the
      current phase (thinking / running tool) *while a turn is processing*
- [ ] **TUI-05**: Tool-approval requests appear as a modal dialog (replacing the inline `y/N`),
      resolving the worker thread's approval event
- [ ] **TUI-06**: The plain loop and `run --json` continue to work unchanged; keyring/Textual
      absence degrades gracefully to the plain loop
- [ ] **TUI-03**: A command palette offers autocomplete over slash-commands (`/model`, `/mcp`,
      `/config`, `/cost`, `/clear`, …) and runs the selected one
- [ ] **TUI-04**: Interactive choices are made via arrow-key selectable menus/modals

### Model & Provider Configuration

- [ ] **MODEL-01**: The user can list, switch, add, and test model providers/models from within
      the app (a live connection test confirms the model responds before saving)
- [ ] **MODEL-02**: Config changes are written back to `~/.agent86/config.toml` non-destructively
      (comments preserved), defaulting to user scope with a project-scope option

### Secrets

- [ ] **SEC-01**: API keys can be stored in and read from the OS keyring; environment variables
      still take precedence, and config never contains a plaintext secret

### MCP Configuration

- [ ] **MCP-01**: The user can list, add, remove, and enable/disable MCP servers from within the
      app, with a connection test that validates the server and enumerates its tools before saving

## v2 Requirements

Deferred — acknowledged but not in this milestone's roadmap.

### Polish

- **POL-01**: Theming / color schemes for the TUI
- **POL-02**: Session picker UI (browse & resume prior sessions from a menu)
- **POL-03**: In-app skills browser/manager

## Out of Scope

| Feature | Reason |
|---------|--------|
| Keep legacy `rich_loop` long-term | Replaced by TUI + plain loop; three loops → two |
| Plaintext / hand-rolled encrypted secret storage | keyring only; no custom crypto |
| Harness / cognitive-loop rewrite | This milestone is presentation + config-write only |
| Web or GUI front-end | Terminal only |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| TUI-01 | Phase 1 | Pending |
| TUI-02 | Phase 1 | Pending |
| TUI-05 | Phase 1 | Pending |
| TUI-03 | Phase 2 | Pending |
| TUI-04 | Phase 2 | Pending |
| SEC-01 | Phase 3 | Pending |
| MODEL-01 | Phase 3 | Pending |
| MODEL-02 | Phase 3 | Pending |
| MCP-01 | Phase 4 | Pending |
| TUI-06 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 10 total
- Mapped to phases: 10
- Unmapped: 0 ✓

---
*Requirements defined: 2026-07-19*
*Last updated: 2026-07-19 after initial definition*
