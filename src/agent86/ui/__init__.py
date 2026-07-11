"""User interface — the interactive REPL and rendering.

Rich + prompt_toolkit render streaming model output, tool-call panels, approval
prompts, and a live cost/step meter. Phase 1 ships a minimal REPL inline in
``agent86.cli``; the richer components (``repl.py``, ``render.py``) are extracted here
as the loop matures (Phase 2+).
"""
