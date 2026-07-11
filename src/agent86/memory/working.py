"""Working memory (Pillar 2) — context-window management.

Keeps the conversation under a token budget with a sliding window: newest turns are kept,
oldest are dropped once the budget is exceeded. Trimming never leaves an orphan tool-result
at the head of the window (which would break providers that require a preceding tool-use).
Recursive summarization of the dropped prefix is a Phase-5 enhancement (hook below).
"""

from __future__ import annotations

from collections.abc import Callable

from agent86.types import Message, Role


class WorkingMemory:
    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens

    def fit(
        self, messages: list[Message], counter: Callable[[list[Message]], int]
    ) -> list[Message]:
        """Return the largest recent suffix of ``messages`` that fits the token budget."""
        if not messages or counter(messages) <= self.max_tokens:
            return messages

        kept: list[Message] = []
        for message in reversed(messages):
            trial = [message, *kept]
            if kept and counter(trial) > self.max_tokens:
                break
            kept = trial

        # Drop any leading tool-result orphans left by the cut.
        while len(kept) > 1 and kept[0].role == Role.TOOL:
            kept = kept[1:]
        return kept


__all__ = ["WorkingMemory"]
