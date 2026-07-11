"""Tier 4 — Tool & Execution  (Pillar 3: the actuators).

Where side effects happen in the real world. A model can only express the *intent*
to use a tool; this tier translates that intent into safe, deterministic execution
through strict JSON-Schema enforcement and sandbox isolation. Tools come from three
sources into one registry: built-ins, MCP servers, and skills.

Modules (Phase 3+):
    base.py        — Tool ABC, ToolResult
    registry.py    — registration, schema export, dispatch, per-tool policy
    builtin/       — shell, files, web, python_exec
    mcp_client.py  — MCP client mounting external tools
    sandbox/       — subprocess (default) + docker (opt-in) executors, policy
"""
