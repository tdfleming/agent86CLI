"""Tier 1 — Gateway / Ingress.

Entry point for all external interactions: session lifecycle, identity-to-role
mapping, rate limiting, and initial input sanitization (stripping malicious
payloads, validating file MIME types). Nothing reaches the harness proper without
passing through here.

Modules (Phase 2+):
    session.py  — session init & identity->role mapping
    ingress.py  — input sanitization, file/MIME validation
"""
