"""Circuit breakers (Tier 2) — bound the cost of an agentic loop.

The book's antidote to the "naive ReAct infinite loop": before every model call the breaker
checks the step count, cumulative token cost, wall-clock time, and consecutive-error streak,
and trips (raising :class:`CircuitTripped`) when any bound is exceeded. One breaker instance
lives per user turn.
"""

from __future__ import annotations

import time

from agent86.config import LimitsConfig
from agent86.types import Usage


class CircuitTripped(RuntimeError):
    """A resource bound was exceeded; the loop must halt."""


class CircuitBreaker:
    def __init__(self, limits: LimitsConfig, max_steps: int | None = None):
        self.max_steps = min(max_steps, limits.max_steps) if max_steps else limits.max_steps
        self.max_cost_usd = limits.max_cost_usd
        self.max_wall_clock_s = limits.max_wall_clock_s
        self.max_consecutive_errors = limits.max_consecutive_errors

        self.steps = 0
        self.cost_usd = 0.0
        self.consecutive_errors = 0
        self._start = time.monotonic()

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self._start

    def before_step(self) -> None:
        """Raise if starting another model call would breach a bound."""
        if self.steps >= self.max_steps:
            raise CircuitTripped(f"step budget reached ({self.max_steps} steps)")
        if self.max_cost_usd and self.cost_usd >= self.max_cost_usd:
            raise CircuitTripped(f"cost cap reached (${self.cost_usd:.4f} >= ${self.max_cost_usd})")
        if self.max_wall_clock_s and self.elapsed_s >= self.max_wall_clock_s:
            raise CircuitTripped(f"wall-clock limit reached ({self.max_wall_clock_s}s)")

    def record_step(self, usage: Usage) -> None:
        self.steps += 1
        self.cost_usd += usage.cost_usd

    def record_tool_result(self, ok: bool) -> None:
        if ok:
            self.consecutive_errors = 0
        else:
            self.consecutive_errors += 1
            if self.consecutive_errors > self.max_consecutive_errors:
                raise CircuitTripped(
                    f"aborted after {self.consecutive_errors} consecutive tool errors"
                )


__all__ = ["CircuitBreaker", "CircuitTripped"]
