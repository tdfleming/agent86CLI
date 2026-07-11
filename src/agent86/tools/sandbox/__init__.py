"""Sandbox executors + policy for Tier 4.

A ``SandboxPolicy`` governs every side-effecting tool: path allow/deny + cwd jail,
network egress allow/deny, env scrubbing, and CPU/memory/time limits. Default is a
restricted subprocess; ``--sandbox docker`` escalates to a container when available.
Populated in Phase 3 (subprocess) and Phase 9 (docker).
"""
