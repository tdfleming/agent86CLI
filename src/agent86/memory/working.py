"""Working memory (Pillar 2) — context-window management.

Keeps the conversation inside a token budget derived from the model's *real* context window
rather than a flat number: the window, minus what the prompt already spends (system prompt +
tool schemas), minus the headroom the response needs. What happens when the budget is
exceeded is the caller's choice — :meth:`WorkingMemory.fit` drops the oldest span, and
:meth:`WorkingMemory.compaction_cut` picks the prefix the orchestrator replaces with a
summary instead (``[limits] compaction``).

Trimming never leaves an orphan tool-result at the head of the window (which would break
providers that require a preceding tool-use).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

from agent86.types import Message, Role, ToolSpec

#: Never hand the model less conversation than this, whatever the arithmetic says. A budget
#: that collapses to ~0 (a small window, a large tool catalogue) would trim every turn to a
#: single message and make the agent amnesiac; failing the call with an honest context error
#: from the provider is more useful than silently answering with no history.
MIN_CONVERSATION_TOKENS = 1_024

#: The reserve (headroom + output cap) is clamped to this fraction of the window. Without it a
#: default 4k reserve + 8k output cap would consume an entire 8k local window and leave
#: nothing for the conversation at all.
_MAX_RESERVE_FRACTION = 0.5

#: Messages at the tail that compaction must never touch: the current user turn plus enough
#: recent context that the model does not lose the thread it is mid-way through.
KEEP_RECENT = 6


def count_spec_tokens(specs: Sequence[ToolSpec]) -> int:
    """Rough token cost of the tool catalogue as it goes on the wire (~4 chars/token).

    Tool schemas are part of every request and can run to thousands of tokens once MCP
    servers are mounted; budgeting as if they were free is how a "fits comfortably"
    conversation still gets a context-length 400.
    """
    if not specs:
        return 0
    try:
        payload = json.dumps(
            [
                {"name": s.name, "description": s.description, "parameters": s.parameters}
                for s in specs
            ],
            ensure_ascii=False,
            default=str,
        )
    except (TypeError, ValueError):  # pragma: no cover - defensive
        payload = str(specs)
    return len(payload) // 4


def conversation_budget(
    window: int,
    *,
    overhead_tokens: int = 0,
    reserve_tokens: int = 0,
    output_tokens: int = 0,
    hard_cap: int = 0,
    minimum: int = MIN_CONVERSATION_TOKENS,
) -> int:
    """Tokens of *conversation* that fit, given everything else the request spends.

    ``window`` minus the fixed prompt overhead (system prompt + tool schemas), minus the
    response headroom (``reserve_tokens`` + ``output_tokens``, together clamped to half the
    window so a small local model is not starved), floored at ``minimum``, and only THEN
    clamped by ``hard_cap`` (``[limits] max_context_tokens``; ``0`` means no cap). The floor
    is applied before the cap on purpose: it guards the *derived* number against a pathological
    window, and must not quietly overrule a cap the user typed on purpose.
    """
    window = max(0, int(window))
    reserve = max(0, int(reserve_tokens)) + max(0, int(output_tokens))
    reserve = min(reserve, int(window * _MAX_RESERVE_FRACTION))
    budget = max(window - max(0, int(overhead_tokens)) - reserve, int(minimum))
    if hard_cap and hard_cap > 0:
        budget = min(budget, int(hard_cap))
    return budget


class WorkingMemory:
    """The conversation's slice of the context window.

    ``max_tokens`` is the current budget; the orchestrator recomputes it per request (the
    system prompt and the tool catalogue both change at runtime) and assigns it here, so
    everything sharing this instance — the main loop and any sub-agent — trims to the same
    number.
    """

    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens

    def _budget(self, max_tokens: int | None) -> int:
        return self.max_tokens if max_tokens is None else max_tokens

    def fits(
        self,
        messages: list[Message],
        counter: Callable[[list[Message]], int],
        max_tokens: int | None = None,
    ) -> bool:
        """True when ``messages`` already fit the budget and nothing needs to be dropped."""
        budget = self._budget(max_tokens)
        return not messages or counter(messages) <= budget

    def fit(
        self,
        messages: list[Message],
        counter: Callable[[list[Message]], int],
        max_tokens: int | None = None,
    ) -> list[Message]:
        """Return the largest recent suffix of ``messages`` that fits the token budget."""
        budget = self._budget(max_tokens)
        if not messages or counter(messages) <= budget:
            return messages

        kept: list[Message] = []
        for message in reversed(messages):
            trial = [message, *kept]
            if kept and counter(trial) > budget:
                break
            kept = trial

        # Drop any leading tool-result orphans left by the cut.
        while len(kept) > 1 and kept[0].role == Role.TOOL:
            kept = kept[1:]
        return kept

    def compaction_cut(
        self,
        messages: list[Message],
        counter: Callable[[list[Message]], int],
        max_tokens: int | None = None,
        keep_recent: int = KEEP_RECENT,
        protect_from: int | None = None,
    ) -> int:
        """Index at which to split ``messages`` into a compactable prefix and a kept suffix.

        Returns ``0`` when nothing may be compacted. The cut respects three invariants:

        * the last ``keep_recent`` messages are never compacted — the model must not lose the
          thread it is in the middle of;
        * neither is anything from ``protect_from`` onward (the current user turn);
        * an assistant message carrying ``tool_calls`` is never separated from its TOOL
          results, because every provider rejects a tool_result with no preceding tool_use.
          The cut therefore walks *back* off any TOOL message it lands on.
        """
        budget = self._budget(max_tokens)
        if not messages or counter(messages) <= budget:
            return 0

        cut = len(messages) - max(0, keep_recent)
        if protect_from is not None:
            cut = min(cut, protect_from)
        # Landing on a TOOL result means its assistant tool_use is in the prefix; walk back
        # until the first kept message opens a block of its own.
        while cut > 0 and messages[cut].role == Role.TOOL:
            cut -= 1
        return max(cut, 0)


__all__ = [
    "KEEP_RECENT",
    "MIN_CONVERSATION_TOKENS",
    "WorkingMemory",
    "conversation_budget",
    "count_spec_tokens",
]
