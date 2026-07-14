"""agent86 — an agentic harness on the command line.

A Python CLI that connects to remote or local models and lets them use tools and
skills, built as a faithful implementation of the five-tier architecture and four
pillars from *The Agentic Harness* (Tony Fleming, 2026).

Core principle — Separation of Concerns: the Cognitive Core (the model) only ever
*proposes* the next step. The deterministic harness validates, executes, and persists.
The model never touches the sandbox, the database, or the terminal directly.
"""

__version__ = "0.5.1"

__all__ = ["__version__"]
