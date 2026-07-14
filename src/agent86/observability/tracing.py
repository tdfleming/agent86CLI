"""OpenTelemetry tracing (Tier 5).

Wraps steps, model calls, and tool executions in spans when OTel is enabled and installed.
Degrades to a no-op context manager otherwise, so the loop code can always call ``span(...)``
without conditionals.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any


class Tracer:
    def __init__(self, enabled: bool):
        self._tracer: Any = None
        if enabled:
            try:
                from opentelemetry import trace

                self._tracer = trace.get_tracer("agent86")
            except Exception:
                self._tracer = None

    @property
    def active(self) -> bool:
        return self._tracer is not None

    @contextmanager
    def span(self, name: str, **attributes: Any):
        if self._tracer is None:
            yield None
            return
        with self._tracer.start_as_current_span(name) as span:
            for key, value in attributes.items():
                try:
                    span.set_attribute(key, value)
                except Exception:
                    pass
            yield span


def build_tracer(enabled: bool) -> Tracer:
    return Tracer(enabled)


__all__ = ["Tracer", "build_tracer"]
