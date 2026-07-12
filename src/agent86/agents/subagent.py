"""Sub-agent runtime (multi-agent systems).

A ``SubAgent`` is a role-scoped Reason->Act->Observe loop that *reuses* the parent harness's
provider, tool registry, sandbox, and approval gate — so a delegated task gets the same
guardrails and observability as the main agent, without rebuilding memory/MCP/tracing. Its
depth is tracked so delegation can't recurse without bound.
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
    ToolResult,
)

if TYPE_CHECKING:
    from agent86.orchestration.loop import Harness

_SUB_MAX_STEPS = 8


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

    def _system(self) -> str:
        return (
            f"You are a '{self.role}' sub-agent operating inside a larger agent system. "
            "You were delegated a focused task by a supervising agent. Use tools as needed, "
            "complete the task precisely, and return ONLY the final result — no preamble."
        )

    def _specs(self):
        specs = self.h.registry.specs()
        # At max depth, hide `delegate` so this sub-agent cannot spawn further.
        if self.depth >= self.h.config.agents.max_depth:
            specs = [s for s in specs if s.name != "delegate"]
        return specs

    def run(self, task: str) -> str:
        provider = self.h.provider
        sid = f"sub:{self.role}"
        messages = [
            Message(role=Role.SYSTEM, content=self._system()),
            Message(role=Role.USER, content=task),
        ]
        breaker = CircuitBreaker(self.h.config.limits, max_steps=_SUB_MAX_STEPS)

        while True:
            try:
                breaker.before_step()
            except CircuitTripped as exc:
                return f"[sub-agent '{self.role}' halted: {exc}]"

            completion = provider.complete(
                CompletionRequest(
                    model=provider.model,
                    messages=messages,
                    tools=self._specs(),
                    temperature=0.0,
                )
            )
            breaker.record_step(completion.usage)
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=completion.text,
                    tool_calls=completion.tool_calls,
                )
            )

            if not completion.tool_calls:
                self.h.recorder.event(sid, "subagent_done", role=self.role, depth=self.depth)
                return completion.text

            for call in completion.tool_calls:
                result = self._run_tool(call)
                content = self.h._observe(result, call.name, sid)
                messages.append(
                    Message(role=Role.TOOL, content=content, tool_call_id=call.id, name=call.name)
                )
                try:
                    breaker.record_tool_result(result.ok)
                except CircuitTripped as exc:
                    return f"[sub-agent '{self.role}' halted: {exc}]"

    def _run_tool(self, call) -> ToolResult:
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


__all__ = ["SubAgent"]
