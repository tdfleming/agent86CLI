"""Multi-agent (MAS) — collaboration & negotiation.

An ``Agent`` is a harness instance bound to a role, system prompt, and toolset.
Agents communicate via structured message *envelopes* (never raw natural language as a
wire protocol — the book's "Babel problem") over an in-process async broker. The
orchestrator spawns sub-agents, wires topologies (supervisor / pipeline / blackboard),
and applies harness-level conflict resolution rather than trusting pure LLM debate.

v0.1 ships single-agent-first with this scaffolding present; supervisor topology is the
first wired path (Phase 8).

Modules:
    agent.py         — Agent runtime wrapper
    envelope.py      — structured agent message envelope
    broker.py        — in-process async message broker
    orchestrator.py  — sub-agent spawning, topologies, conflict resolution
"""
