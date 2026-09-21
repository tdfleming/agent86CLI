"""OpenTelemetry tracing (Tier 5).

Wraps the turn, each model call, and each tool execution in spans when OTel is enabled
*and* the ``otel`` extra is installed. Degrades to a no-op context manager otherwise, so the
loop can always call ``span(...)`` without conditionals and ``agent86 run`` never pays for
an import it does not need.

Before v1.0 this only called ``trace.get_tracer``, which returns a handle on the **no-op**
global provider unless something else in the process has already installed one. With
``otel = true`` and the extra installed, spans were created and dropped on the floor. The
tracer now configures its own ``TracerProvider``:

* a ``Resource`` carrying ``service.name = "agent86"`` and ``service.version``,
* an exporter chosen by ``[observability] otel_exporter``: ``otlp`` (gRPC, falling back to
  HTTP when only the HTTP exporter is installed), ``console`` (to stderr), or ``none``,
* a ``BatchSpanProcessor``, flushed by :meth:`Tracer.close` from ``Harness.close()``.

The standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``OTEL_EXPORTER_OTLP_HEADERS`` env vars are
respected — the exporters read them themselves — and ``[observability] otel_endpoint`` is an
explicit override for when config, not environment, is the source of truth.

Every failure path here is swallowed and recorded on :attr:`Tracer.note`: a missing
collector, a missing extra, or a broken exporter must degrade to "no traces", never to
"no agent".

Nothing in this module imports opentelemetry at module scope. The imports live inside
``_build_provider``, which only runs when tracing is switched on.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any


class Tracer:
    """A tracer handle that is always safe to call.

    ``active`` says whether spans are really being recorded; ``note`` carries the one-line
    reason when they are not, so a surface can tell the user "otel = true but the extra is
    not installed" instead of silently doing nothing.
    """

    def __init__(
        self,
        enabled: bool,
        *,
        exporter: str = "otlp",
        endpoint: str | None = None,
        service_version: str | None = None,
    ):
        self._tracer: Any = None
        self._provider: Any = None
        self.note: str | None = None
        if not enabled:
            self.note = "tracing disabled"
            return
        try:
            self._provider, self.note = _build_provider(
                exporter=str(exporter),
                endpoint=endpoint,
                service_version=service_version,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._provider, self.note = None, f"otel disabled: {type(exc).__name__}: {exc}"
        try:
            from opentelemetry import trace

            # With a provider of our own, spans go to our exporter; without one (the extra
            # is missing) this raises and we fall through to the no-op path below.
            self._tracer = (
                self._provider.get_tracer("agent86")
                if self._provider is not None
                else trace.get_tracer("agent86")
            )
            if self._provider is None and self.note is None:
                self.note = "otel: no SDK provider configured; spans are no-ops"
        except Exception as exc:
            self._tracer = None
            if self.note is None:
                self.note = f"otel unavailable ({type(exc).__name__}); spans are no-ops"

    @property
    def active(self) -> bool:
        return self._tracer is not None

    @property
    def exporting(self) -> bool:
        """True only when a real SDK provider is installed and will export spans."""
        return self._provider is not None

    @contextmanager
    def span(self, name: str, **attributes: Any):
        if self._tracer is None:
            yield None
            return
        with self._tracer.start_as_current_span(name) as span:
            set_attributes(span, attributes)
            yield span

    def close(self) -> None:
        """Flush and shut the exporter down. No-op when there is no provider."""
        provider = self._provider
        self._provider = None
        self._tracer = None
        if provider is None:
            return
        try:
            provider.shutdown()
        except Exception:  # pragma: no cover - a flush failure must not break close()
            pass


def set_attributes(span: Any, attributes: dict[str, Any]) -> None:
    """Set attributes on a span, skipping ``None`` and never raising.

    ``None`` is dropped rather than stringified: OTel rejects it, and an attribute whose
    value is the literal ``"None"`` is worse than an absent one when querying a backend.
    """
    if span is None:
        return
    for key, value in attributes.items():
        if value is None:
            continue
        try:
            span.set_attribute(key, value)
        except Exception:
            continue


def _build_provider(
    *, exporter: str, endpoint: str | None, service_version: str | None
) -> tuple[Any, str | None]:
    """Configure a real ``TracerProvider``, or return ``(None, note)`` explaining why not."""
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return None, "otel enabled but the 'otel' extra is not installed; spans are no-ops"

    from agent86 import __version__

    resource = Resource.create(
        {
            "service.name": "agent86",
            "service.version": service_version or __version__,
        }
    )
    provider = TracerProvider(resource=resource)

    if exporter == "none":
        # Spans are recorded and sampled but go nowhere: useful when another process in the
        # same interpreter installs its own processors, and for tests.
        return provider, "otel: no exporter configured (otel_exporter = 'none')"

    span_exporter, note = _build_exporter(exporter, endpoint)
    if span_exporter is None:
        try:
            provider.shutdown()
        except Exception:  # pragma: no cover - defensive
            pass
        return None, note
    provider.add_span_processor(BatchSpanProcessor(span_exporter))
    return provider, note


def _build_exporter(exporter: str, endpoint: str | None) -> tuple[Any, str | None]:
    if exporter == "console":
        import sys

        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        # stderr, never stdout: stdout is the harness's streamed model output and the
        # `run --json` contract.
        return ConsoleSpanExporter(out=sys.stderr), None

    if exporter != "otlp":
        return None, f"otel: unknown exporter {exporter!r}; spans are no-ops"

    # `endpoint` overrides OTEL_EXPORTER_OTLP_ENDPOINT; when neither is set the exporters
    # fall back to their own default (localhost:4317 / :4318).
    target = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        return (OTLPSpanExporter(endpoint=target) if target else OTLPSpanExporter()), None
    except ImportError:
        pass
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HTTPExporter,
        )

        return (HTTPExporter(endpoint=target) if target else HTTPExporter()), None
    except ImportError:
        return None, (
            "otel: no OTLP exporter installed (pip install 'agent86[otel]'); spans are no-ops"
        )
    except Exception as exc:  # pragma: no cover - a malformed endpoint, say
        return None, f"otel: OTLP exporter unavailable ({type(exc).__name__}: {exc})"


def build_tracer(
    enabled: bool,
    *,
    exporter: str = "otlp",
    endpoint: str | None = None,
    service_version: str | None = None,
) -> Tracer:
    return Tracer(
        enabled, exporter=exporter, endpoint=endpoint, service_version=service_version
    )


__all__ = ["Tracer", "build_tracer", "set_attributes"]
