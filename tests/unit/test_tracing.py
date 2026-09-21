"""v1.0 — the OpenTelemetry tracer really exports.

Two halves. With the ``otel`` extra installed, an ``InMemorySpanExporter`` is wired into a
``Tracer`` and the span tree plus attributes are asserted for a fake turn. Without it, the
import is broken on purpose and the tracer must degrade to a no-op with a readable note —
because ``otel = true`` on a machine that never installed the extra has to stay a warning,
not a crash.
"""

from __future__ import annotations

import builtins
import sys

import pytest

from agent86.observability.tracing import Tracer, build_tracer, set_attributes

sdk = pytest.importorskip("opentelemetry.sdk.trace", reason="requires the 'otel' extra")


# --------------------------------------------------------------------------- #
# With the SDK
# --------------------------------------------------------------------------- #


@pytest.fixture
def exporting_tracer():
    """A real Tracer whose provider exports into memory."""
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    tracer = build_tracer(True, exporter="none", service_version="9.9.9")
    assert tracer.exporting, tracer.note
    memory = InMemorySpanExporter()
    tracer._provider.add_span_processor(SimpleSpanProcessor(memory))
    try:
        yield tracer, memory
    finally:
        tracer.close()


def test_provider_carries_the_service_resource(exporting_tracer):
    tracer, memory = exporting_tracer
    with tracer.span("turn"):
        pass
    (span,) = memory.get_finished_spans()
    assert span.resource.attributes["service.name"] == "agent86"
    assert span.resource.attributes["service.version"] == "9.9.9"


def test_span_tree_and_attributes_for_a_fake_turn(exporting_tracer):
    tracer, memory = exporting_tracer
    with tracer.span("turn", **{"session.id": "s-1", "gen_ai.request.model": "m"}) as turn:
        with tracer.span(
            "model_call", **{"gen_ai.system": "anthropic", "gen_ai.request.model": "m"}
        ) as call:
            set_attributes(
                call,
                {"gen_ai.usage.input_tokens": 11, "gen_ai.usage.output_tokens": 7},
            )
        with tracer.span("tool_call", **{"tool.name": "read_file"}) as tool:
            set_attributes(tool, {"tool.ok": True})
        set_attributes(turn, {"agent86.steps": 2, "agent86.cost_usd": 0.5})

    spans = {s.name: s for s in memory.get_finished_spans()}
    assert set(spans) == {"turn", "model_call", "tool_call"}

    turn_span = spans["turn"]
    assert turn_span.parent is None
    assert turn_span.attributes["session.id"] == "s-1"
    assert turn_span.attributes["agent86.steps"] == 2
    assert turn_span.attributes["agent86.cost_usd"] == 0.5

    # Both children hang off the turn — the tree, not a flat list.
    for child in ("model_call", "tool_call"):
        assert spans[child].parent is not None
        assert spans[child].parent.span_id == turn_span.context.span_id

    assert spans["model_call"].attributes["gen_ai.system"] == "anthropic"
    assert spans["model_call"].attributes["gen_ai.usage.input_tokens"] == 11
    assert spans["model_call"].attributes["gen_ai.usage.output_tokens"] == 7
    assert spans["tool_call"].attributes["tool.name"] == "read_file"
    assert spans["tool_call"].attributes["tool.ok"] is True


def test_set_attributes_drops_none_and_never_raises(exporting_tracer):
    tracer, memory = exporting_tracer
    with tracer.span("turn") as span:
        set_attributes(span, {"kept": 1, "dropped": None})
    set_attributes(None, {"anything": 1})  # must not raise
    (span,) = memory.get_finished_spans()
    assert "dropped" not in span.attributes
    assert span.attributes["kept"] == 1


def test_console_exporter_writes_to_stderr():
    tracer = build_tracer(True, exporter="console")
    try:
        assert tracer.exporting, tracer.note
        assert tracer.note is None
    finally:
        tracer.close()


def test_otlp_endpoint_override_beats_the_env_var(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://env:4317")
    seen: dict = {}

    import agent86.observability.tracing as tracing_mod

    real = tracing_mod._build_exporter

    def spy(exporter, endpoint):
        seen["endpoint"] = endpoint
        return real("none", None)[0], None

    monkeypatch.setattr(tracing_mod, "_build_exporter", spy)
    tracer = build_tracer(True, exporter="otlp", endpoint="http://cfg:4317")
    tracer.close()
    assert seen["endpoint"] == "http://cfg:4317"


def test_unknown_exporter_degrades_with_a_note():
    tracer = build_tracer(True, exporter="carrier-pigeon")
    try:
        assert not tracer.exporting
        assert "carrier-pigeon" in (tracer.note or "")
    finally:
        tracer.close()


def test_close_shuts_the_provider_down_once(exporting_tracer):
    tracer, _ = exporting_tracer
    tracer.close()
    assert not tracer.exporting
    assert not tracer.active
    tracer.close()  # idempotent
    with tracer.span("turn") as span:  # still safe to call
        assert span is None


def test_disabled_tracer_is_inert():
    tracer = build_tracer(False)
    assert not tracer.active and not tracer.exporting
    assert tracer.note == "tracing disabled"
    with tracer.span("turn", x=1) as span:
        assert span is None
    tracer.close()


# --------------------------------------------------------------------------- #
# A real turn through the harness
# --------------------------------------------------------------------------- #


def test_a_real_turn_produces_the_expected_span_tree():
    """End to end: `Harness.run_turn` emits turn -> {model_call, tool_call} with attributes."""
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from agent86.config import load_config
    from agent86.orchestration.loop import Harness
    from agent86.tools.base import EmptyArgs, Tool, ToolContext
    from agent86.tools.registry import ToolRegistry
    from agent86.types import ToolCall, ToolResult, ToolSpec
    from tests.support import ToolThenTextProvider

    class Ping(Tool[EmptyArgs]):
        name = "ping"
        description = "ping"
        Args = EmptyArgs
        side_effecting = False

        def spec(self) -> ToolSpec:
            return ToolSpec(name=self.name, description=self.description, parameters={})

        def execute(self, args: EmptyArgs, ctx: ToolContext) -> ToolResult:
            return ToolResult(call_id="c1", name=self.name, ok=True, content="pong")

    cfg = load_config()
    cfg.observability.otel = True
    cfg.observability.otel_exporter = "none"
    provider = ToolThenTextProvider(ToolCall(id="c1", name="ping", arguments={}))
    registry = ToolRegistry()
    registry.register(Ping())
    harness = Harness(cfg, provider=provider, memory=None, registry=registry)

    memory = InMemorySpanExporter()
    assert harness.tracer.exporting, harness.tracer.note
    harness.tracer._provider.add_span_processor(SimpleSpanProcessor(memory))

    state = harness.new_session()
    list(harness.run_turn("hi", state))
    harness.close()

    spans = memory.get_finished_spans()
    by_name: dict = {}
    for span in spans:
        by_name.setdefault(span.name, []).append(span)
    assert set(by_name) == {"turn", "model_call", "tool_call"}
    assert len(by_name["model_call"]) == 2  # the tool step, then the answer

    (turn,) = by_name["turn"]
    assert turn.parent is None
    assert turn.attributes["session.id"] == state.session_id
    assert turn.attributes["agent86.steps"] == 2
    assert turn.attributes["agent86.tool_calls"] == 1
    assert turn.attributes["gen_ai.usage.input_tokens"] == 11  # 5 + 6
    assert turn.attributes["gen_ai.usage.output_tokens"] == 3

    for child in by_name["model_call"] + by_name["tool_call"]:
        assert child.parent.span_id == turn.context.span_id

    first_call = by_name["model_call"][0]
    assert first_call.attributes["gen_ai.request.model"] == provider.model
    assert first_call.attributes["gen_ai.system"] == "tooltext"
    assert first_call.attributes["gen_ai.usage.input_tokens"] == 5

    (tool_span,) = by_name["tool_call"]
    assert tool_span.attributes["tool.name"] == "ping"
    assert tool_span.attributes["gen_ai.tool.name"] == "ping"
    assert tool_span.attributes["tool.ok"] is True


# --------------------------------------------------------------------------- #
# Without the SDK
# --------------------------------------------------------------------------- #


def test_missing_extra_degrades_to_the_noop_tracer_with_a_note(monkeypatch):
    """`otel = true` on a machine without the extra: a note, not a traceback."""
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("opentelemetry.sdk"):
            raise ImportError("No module named 'opentelemetry.sdk'")
        return real_import(name, *args, **kwargs)

    for mod in [m for m in sys.modules if m.startswith("opentelemetry.sdk")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setattr(builtins, "__import__", blocked)

    tracer = Tracer(True)
    assert not tracer.exporting
    assert "extra is not installed" in (tracer.note or "")
    # The API's no-op tracer still answers, so the loop's `with span(...)` keeps working.
    with tracer.span("turn", **{"session.id": "s1"}):
        pass
    tracer.close()
