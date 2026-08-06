"""Pin the debugging-discipline section of the system prompt identity.

The model was misattributing its own bugs to a flaky environment because it never printed
tracebacks or inspected data shape before indexing. `_BASE_IDENTITY` gains a terse
debugging-discipline section instructing it to do both, and to treat attempt-to-attempt
differences as a clue about its own code rather than proof of a flaky sandbox.
"""

from __future__ import annotations

from agent86.cognitive.prompt import build_system_prompt
from agent86.config import load_config


def _prompt_text() -> str:
    return build_system_prompt(load_config()).content.lower()


def test_prompt_mentions_traceback_printing():
    text = _prompt_text()
    assert "traceback.format_exc" in text
    assert "try/except" in text or "except" in text


def test_prompt_mentions_shape_inspection():
    text = _prompt_text()
    assert ".keys()" in text
    assert "type(" in text


def test_prompt_mentions_flaky_environment_discipline():
    text = _prompt_text()
    assert "flaky" in text
