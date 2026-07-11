"""Tier 5 — Observability.

Makes autonomous runs debuggable. OpenTelemetry spans wrap each step, model call, and
tool execution; a parallel append-only JSONL flight recorder gives a local, greppable
audit trail even with no OTel collector configured.

Modules (Phase 5+):
    tracing.py   — OpenTelemetry span setup
    recorder.py  — JSONL flight-data recorder
"""
