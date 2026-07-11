"""Tier 5 — Guardrails  (Pillar 4: the immune system).

Deterministic policies, monitors, and filters that inspect inputs and outputs
bidirectionally:

    Ingress     — prompt-injection / jailbreak / PII scanning on input
    Egress      — secret/PII leak scanning + output schema validation
    Operational — rate limits, cost caps, step caps
    HITL        — approval gate for side-effectful / destructive tool calls

Modules (Phase 5+):
    ingress.py  — input scanning
    egress.py   — output scanning + schema validation
    policy.py   — operational policy + human-in-the-loop approval gate
"""
