"""User interface — the interactive entry point and shared status rendering.

``repl.py`` owns ``run_repl``: it builds the harness once and routes to either the
full-screen Textual app (``agent86.tui``) or the plain stdlib ``input()`` loop.
``status.py`` holds the pure status-line logic both surfaces render.
"""
