"""Sub-agent runtime (multi-agent systems).

A ``SubAgent`` is a role-scoped Reason->Act->Observe loop that *reuses* the parent harness's
provider, tool registry, sandbox, and approval gate — so a delegated task gets the same
guardrails and observability as the main agent, without rebuilding memory/MCP/tracing. Its
depth is tracked so delegation can't recurse without bound.

Accountability is the other half of that reuse: a sub-agent runs under the parent's step and
context budgets, reports every model call to the same recorder tagged with its role and depth,
and hands its token usage back so the parent turn's cost includes what it spent. A delegated
task is not a way to escape the harness's limits.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from agent86.orchestration.circuit import CircuitBreaker, CircuitTripped
from agent86.tools.base import ToolContext
from agent86.types import (
    CompletionRequest,
    Message,
    Role,
    ToolCall,
    ToolResult,
    Usage,
    invalid_arguments_result,
)

if TYPE_CHECKING:
    from agent86.orchestration.loop import Harness

#: Used when the config predates ``agents.max_steps``.
DEFAULT_SUB_MAX_STEPS = 8

_ROLE_PREAMBLE = (
    "You are a '{role}' sub-agent operating inside a larger agent system. You were delegated "
    "a focused task by a supervising agent. Use tools as needed, complete the task precisely, "
    "and return ONLY the final result — no preamble."
)


class SubAgent:
    def __init__(self, harness: Harness, role: str, depth: int):
        self.h = harness
        self.role = role or "assistant"
        self.depth = depth
        # A context whose spawn() delegates one level deeper, so nested delegation is depth-aware.
        self.ctx: ToolContext = replace(
            harness.context,
            spawn=lambda r, t: harness.spawn_subagent(r, t, depth + 1),
        )

    @property
    def max_steps(self) -> int:
        """Step budget for this sub-agent, from ``agents.max_steps``."""
        return getattr(self.h.config.agents, "max_steps", DEFAULT_SUB_MAX_STEPS)

    def _system(self) -> Message:
        """Role preamble + the parent's compiled system prompt.

        Sub-agents used to get the persona and nothing else: no environment facts and — the
        real problem — no skills list, so ``use_skill`` was advertised to them as a tool with
        no way of knowing what to ask it for. ``build_system_prompt``'s output, which the
        harness compiled once at startup, is reused verbatim beneath the preamble.
        """
        return Message(
            role=Role.SYSTEM,
            content=f"{_ROLE_PREAMBLE.format(role=self.role)}\n\n{self.h.system_prompt.content}",
        )

    def _specs(self):
        specs = self.h.registry.specs()
        # At max depth, hide `delegate` so this sub-agent cannot spawn further.
        if self.depth >= self.h.config.agents.max_depth:
            specs = [s for s in specs if s.name != "delegate"]
        return specs

    def run(self, task: str) -> tuple[str, Usage]:
        """Run the delegated task to completion; return its answer and what it cost."""
        provider = self.h.provider
        sid = f"sub:{self.role}"
        system = self._system()
        messages: list[Message] = [Message(role=Role.USER, content=task)]
        breaker = CircuitBreaker(self.h.config.limits, max_steps=self.max_steps)
        spent = Usage()

        while True:
            try:
                breaker.before_step()
            except CircuitTripped as exc:
                return f"[sub-agent '{self.role}' halted: {exc}]", spent

            # Same context-window discipline as the main loop: a sub-agent that ran many
            # tool calls could otherwise overflow the window and fail its last model call.
            # The system message is held out of the trim so it can never be the part dropped.
            convo = self.h.working.fit(messages, provider.count_tokens)
            completion = provider.complete(
                CompletionRequest(
                    model=provider.model,
                    messages=[system, *convo],
                    tools=self._specs(),
                    temperature=0.0,
                )
            )
            breaker.record_step(completion.usage)
            spent = spent + completion.usage
            self.h.recorder.event(
                sid,
                "model_call",
                agent=self.role,
                depth=self.depth,
                step=breaker.steps,
                model=provider.model,
                input_tokens=completion.usage.input_tokens,
                output_tokens=completion.usage.output_tokens,
                cost_usd=completion.usage.cost_usd,
                stop_reason=completion.stop_reason,
                tool_calls=[tc.name for tc in completion.tool_calls],
            )
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=completion.text,
                    tool_calls=completion.tool_calls,
                )
            )

            if not completion.tool_calls:
                self.h.recorder.event(
                    sid, "subagent_done", role=self.role, depth=self.depth,
                    steps=breaker.steps, cost_usd=spent.cost_usd,
                )
                return completion.text, spent

            for call in completion.tool_calls:
                result = self._run_tool(call)
                content = self.h._observe(result, call.name, sid)
                messages.append(
                    Message(role=Role.TOOL, content=content, tool_call_id=call.id, name=call.name)
                )
                try:
                    breaker.record_tool_result(result.ok)
                except CircuitTripped as exc:
                    return f"[sub-agent '{self.role}' halted: {exc}]", spent

    def _run_tool(self, call: ToolCall) -> ToolResult:
        # Same interception as the main loop: unparseable arguments never reach a tool.
        invalid = call.invalid_arguments
        if invalid is not None:
            return invalid_arguments_result(call, invalid)
        tool = self.h.registry.get(call.name)
        if tool is None:
            return self.h.registry.dispatch(call, self.ctx)
        decision = self.h.gate.decide(tool, call)
        if not decision.approved:
            return ToolResult(
                call_id=call.id, name=call.name, ok=False,
                error=f"Not executed: {decision.reason}.",
            )
        result = self.h.registry.dispatch(call, self.ctx)
        self.h.recorder.event(
            f"sub:{self.role}", "tool_call", tool=call.name, ok=result.ok, depth=self.depth
        )
        return result


__all__ = ["SubAgent", "DEFAULT_SUB_MAX_STEPS"]
