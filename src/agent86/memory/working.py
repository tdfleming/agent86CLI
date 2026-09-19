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


# --------------------------------------------------------------------------- #
# Compaction — turning the dropped prefix into a summary instead of a hole
# --------------------------------------------------------------------------- #

#: Prefixed to the replacement message so a human reading a resumed session (and the model
#: reading its own history) can see that the span was compacted, not forgotten.
SUMMARY_HEADER = "[Conversation summary — earlier turns compacted]"

#: Rough ceiling for the summary itself. Bigger than this and compaction stops paying for
#: itself; smaller and the goal stops surviving.
SUMMARY_MAX_TOKENS = 600

#: The summarizer's instructions. Written for a *cheap* model: concrete, sectioned, and
#: explicit that identifiers are to be copied rather than paraphrased — a summary that
#: renames a file path is worse than no summary at all, because the agent will act on it.
SUMMARY_SYSTEM_PROMPT = (
    "You are compacting the earlier part of an agent's conversation so it fits in a context "
    "window. Write a dense factual summary of the transcript below, under these headings:\n"
    "GOAL: what the user is ultimately trying to achieve.\n"
    "DECISIONS: choices already made and why, including anything ruled out.\n"
    "FACTS: what was discovered — file paths, identifiers, commands, versions, numbers, "
    "error messages.\n"
    "OPEN: what is still unfinished or unverified.\n\n"
    "Rules: reproduce every file path, identifier, command, URL and number EXACTLY as it "
    "appears — never paraphrase, abbreviate or 'correct' one. Record only what the "
    "transcript says; invent nothing. Omit pleasantries and narration. Be terse: aim for "
    f"under {SUMMARY_MAX_TOKENS} tokens. Output the summary only, with no preamble."
)

#: Per-message cap when rendering the transcript handed to the summarizer. A single 200k-char
#: tool observation would otherwise be the whole summarization request.
_TRANSCRIPT_MESSAGE_CHARS = 2_000


def _clip(text: str, limit: int = _TRANSCRIPT_MESSAGE_CHARS) -> str:
    text = text or ""
    return text if len(text) <= limit else f"{text[:limit]} ... [{len(text) - limit} more chars]"


def render_transcript(messages: Sequence[Message]) -> str:
    """Render a span of conversation as plain text for the summarizer.

    Tool calls and their results are rendered explicitly — they are usually where the facts
    worth keeping (the paths that exist, the command that worked) actually are.
    """
    lines: list[str] = []
    for m in messages:
        label = m.role.value.upper()
        if m.role == Role.TOOL:
            lines.append(f"{label} result of {m.name or '?'}: {_clip(m.content)}")
            continue
        if m.content:
            lines.append(f"{label}: {_clip(m.content)}")
        for call in m.tool_calls:
            try:
                args = json.dumps(call.arguments, ensure_ascii=False, default=str)
            except (TypeError, ValueError):  # pragma: no cover - defensive
                args = str(call.arguments)
            lines.append(f"{label} called {call.name}({_clip(args, 600)})")
    return "\n".join(lines)


def apply_summary(summary_text: str, rest: list[Message]) -> list[Message]:
    """Return the compacted history: the summary, then everything that was kept.

    The summary rides on a USER message rather than a new role, so no provider adapter has to
    learn anything. It is *merged into* the first kept message when that is also a USER turn,
    because two USER messages in a row is a shape some providers reject outright — Anthropic's
    adapter additionally renders a TOOL result as a ``user`` message, so "consecutive user"
    is easier to produce here than it looks.
    """
    content = f"{SUMMARY_HEADER}\n{summary_text.strip()}"
    if rest and rest[0].role == Role.USER and not rest[0].tool_calls:
        head = rest[0].model_copy(update={"content": f"{content}\n\n{rest[0].content}"})
        return [head, *rest[1:]]
    return [Message(role=Role.USER, content=content), *rest]


__all__ = [
    "KEEP_RECENT",
    "MIN_CONVERSATION_TOKENS",
    "SUMMARY_HEADER",
    "SUMMARY_MAX_TOKENS",
    "SUMMARY_SYSTEM_PROMPT",
    "WorkingMemory",
    "apply_summary",
    "conversation_budget",
    "count_spec_tokens",
    "render_transcript",
]
