"""Tier 2 — Orchestration & State  (Pillar 1: the nervous system).

The model-agnostic brain of the harness. Drives the ReAct execution loop, enforces
the finite-state-machine lifecycle (INIT -> PLAN -> EXECUTE -> VERIFY -> DONE),
persists state atomically, routes model calls by complexity/cost, and trips circuit
breakers to prevent runaway loops. Every model proposal and tool result crosses here.

Modules (Phase 2+):
    loop.py     — ReAct execution loop
    state.py    — AgentState FSM + persistence
    router.py   — dynamic model routing (triage)
    circuit.py  — cost/step/wall-clock circuit breakers
"""
