"""v1.0 — ``agent86 trace show`` filters and ``agent86 trace export``.

All of these run the real Typer app against a temp trace directory: ``load_config`` is
monkeypatched in the CLI module (the same seam the other CLI-facing tests use) so nothing
touches the developer's own ~/.agent86.
"""

from __future__ import annotations

import json
import time

import pytest
from typer.testing import CliRunner

from agent86 import cli as cli_mod
from agent86.config import Config
from agent86.observability.recorder import Recorder

runner = CliRunner()


@pytest.fixture
def trace_dir(tmp_path, monkeypatch):
    """A temp trace directory the CLI resolves to, plus a recorder writing into it."""
    cfg = Config()
    cfg.observability.path = str(tmp_path)
    # Deep enough that the rotation tests below can push every event out of the live file
    # and still have the CLI find them.
    cfg.observability.keep_traces = 10
    monkeypatch.setattr(cli_mod, "load_config", lambda *a, **k: cfg)
    return tmp_path


def _seed(trace_dir, **kwargs) -> None:
    """Write a two-session trace: one clean turn with a tool call, one failed turn."""
    rec = Recorder(trace_dir / "trace.jsonl", **kwargs)
    now = time.time()
    rec.event("sess-a", "turn_start", task="do the thing")
    rec.event(
        "sess-a", "model_call", step=1, model="anthropic:claude", input_tokens=100,
        output_tokens=20, cost_usd=0.0021, stop_reason="tool_use", tool_calls=["read_file"],
    )
    rec.event("sess-a", "tool_call", tool="read_file", ok=True, arguments={"path": "a.txt"})
    rec.event(
        "sess-a", "model_call", step=2, model="anthropic:claude", input_tokens=150,
        output_tokens=30, cost_usd=0.0035, stop_reason="end_turn", tool_calls=[],
    )
    rec.event("sess-a", "turn_end", status="done", steps=2)
    rec.event("sess-b", "turn_start", task="the other thing")
    rec.event("sess-b", "tool_call", tool="run_shell", ok=False, error="boom")
    rec.event("sess-b", "turn_end", status="error", reason="circuit tripped")
    rec.close()
    return now


# --------------------------------------------------------------------------- #
# show
# --------------------------------------------------------------------------- #


def test_show_reports_nothing_when_the_trace_is_empty(trace_dir):
    result = runner.invoke(cli_mod.app, ["trace", "show"])
    assert result.exit_code == 0
    assert "no trace events" in result.output


def test_show_prints_token_and_cost_columns_for_model_calls(trace_dir):
    _seed(trace_dir)
    result = runner.invoke(cli_mod.app, ["trace", "show", "--kind", "model_call"])
    assert result.exit_code == 0, result.output
    assert "$0.0021" in result.output
    assert "$0.0035" in result.output
    # The footer totals both calls: 250 in / 50 out, $0.0056.
    assert "250 in / 50 out" in result.output
    assert "$0.0056" in result.output


def test_show_kind_filter_excludes_everything_else(trace_dir):
    _seed(trace_dir)
    result = runner.invoke(cli_mod.app, ["trace", "show", "-k", "tool_call"])
    assert result.exit_code == 0
    assert "tool_call" in result.output
    assert "turn_start" not in result.output
    assert "model_call" not in result.output


def test_show_kind_is_repeatable(trace_dir):
    _seed(trace_dir)
    result = runner.invoke(
        cli_mod.app, ["trace", "show", "-k", "turn_start", "-k", "turn_end"]
    )
    assert "turn_start" in result.output and "turn_end" in result.output
    assert "model_call" not in result.output


def test_show_session_filter(trace_dir):
    _seed(trace_dir)
    result = runner.invoke(cli_mod.app, ["trace", "show", "-s", "sess-b"])
    assert "sess-b" in result.output
    assert "sess-a" not in result.output


def test_show_since_excludes_older_events(trace_dir):
    _seed(trace_dir)
    # Everything was written seconds ago, so a 2h window keeps it all...
    assert "model_call" in runner.invoke(cli_mod.app, ["trace", "show", "--since", "2h"]).output
    # ...and a window that ends before they were written keeps none.
    old = trace_dir / "trace.jsonl"
    lines = [json.loads(line) for line in old.read_text(encoding="utf-8").splitlines()]
    for record in lines:
        record["ts"] = time.time() - 86_400
    old.write_text(
        "".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8"
    )
    result = runner.invoke(cli_mod.app, ["trace", "show", "--since", "2h"])
    assert "no trace events" in result.output


def test_show_rejects_a_bad_duration(trace_dir):
    _seed(trace_dir)
    result = runner.invoke(cli_mod.app, ["trace", "show", "--since", "soon"])
    assert result.exit_code != 0
    assert "duration" in result.output


def test_show_reads_across_rotated_generations(trace_dir):
    # A cap of one line per file pushes almost everything into rotated generations.
    _seed(trace_dir, max_bytes=100, keep=10)
    result = runner.invoke(cli_mod.app, ["trace", "show", "-k", "model_call"])
    assert "$0.0021" in result.output and "$0.0035" in result.output


def test_path_lists_rotated_generations(trace_dir):
    _seed(trace_dir, max_bytes=100, keep=10)
    result = runner.invoke(cli_mod.app, ["trace", "path"])
    assert "trace.jsonl" in result.output
    assert "trace.1.jsonl" in result.output


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #


def test_export_jsonl_to_stdout_filters_by_session(trace_dir):
    _seed(trace_dir)
    result = runner.invoke(cli_mod.app, ["trace", "export", "-s", "sess-b"])
    assert result.exit_code == 0, result.output
    records = [json.loads(line) for line in result.stdout.strip().splitlines()]
    assert len(records) == 3
    assert {r["session"] for r in records} == {"sess-b"}


def test_export_json_writes_a_single_array_to_a_file(trace_dir, tmp_path):
    _seed(trace_dir)
    out = tmp_path / "nested" / "trace.json"
    result = runner.invoke(
        cli_mod.app, ["trace", "export", "--format", "json", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(payload, list) and len(payload) == 8
    assert "Wrote 8 event(s)" in result.output


def test_export_rejects_an_unknown_format(trace_dir):
    result = runner.invoke(cli_mod.app, ["trace", "export", "--format", "parquet"])
    assert result.exit_code != 0
    assert "parquet" in result.output


def test_export_otlp_json_reconstructs_the_span_tree(trace_dir, tmp_path):
    _seed(trace_dir)
    out = tmp_path / "spans.json"
    result = runner.invoke(
        cli_mod.app,
        ["trace", "export", "--session", "sess-a", "--format", "otlp-json", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output

    doc = json.loads(out.read_text(encoding="utf-8"))
    (resource_spans,) = doc["resourceSpans"]
    attrs = {a["key"]: a["value"] for a in resource_spans["resource"]["attributes"]}
    assert attrs["service.name"]["stringValue"] == "agent86"
    (scope_spans,) = resource_spans["scopeSpans"]
    spans = scope_spans["spans"]

    by_name: dict[str, list] = {}
    for span in spans:
        by_name.setdefault(span["name"], []).append(span)
    assert sorted(by_name) == ["model_call", "tool_call", "turn"]
    assert len(by_name["model_call"]) == 2

    (turn,) = by_name["turn"]
    assert "parentSpanId" not in turn
    assert turn["status"]["code"] == 1  # done
    for child in by_name["model_call"] + by_name["tool_call"]:
        assert child["parentSpanId"] == turn["spanId"]
        assert child["traceId"] == turn["traceId"]
        assert int(child["endTimeUnixNano"]) >= int(child["startTimeUnixNano"])

    call_attrs = {
        a["key"]: a["value"] for a in by_name["model_call"][0]["attributes"]
    }
    assert call_attrs["gen_ai.request.model"]["stringValue"] == "anthropic:claude"
    assert call_attrs["gen_ai.usage.input_tokens"]["intValue"] == "100"
    assert call_attrs["agent86.cost_usd"]["doubleValue"] == pytest.approx(0.0021)

    tool_attrs = {a["key"]: a["value"] for a in by_name["tool_call"][0]["attributes"]}
    assert tool_attrs["tool.name"]["stringValue"] == "read_file"
    assert tool_attrs["tool.ok"]["boolValue"] is True


def test_export_otlp_json_marks_a_failed_turn_and_a_failed_tool(trace_dir):
    _seed(trace_dir)
    result = runner.invoke(
        cli_mod.app, ["trace", "export", "-s", "sess-b", "-f", "otlp-json"]
    )
    spans = json.loads(result.stdout)["resourceSpans"][0]["scopeSpans"][0]["spans"]
    statuses = {s["name"]: s["status"]["code"] for s in spans}
    assert statuses["turn"] == 2  # ERROR
    assert statuses["tool_call"] == 2


def test_export_otlp_json_separates_sessions_into_distinct_traces(trace_dir):
    _seed(trace_dir)
    result = runner.invoke(cli_mod.app, ["trace", "export", "-f", "otlp-json"])
    spans = json.loads(result.stdout)["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len({s["traceId"] for s in spans}) == 2
    assert len({s["spanId"] for s in spans}) == len(spans)  # ids are unique


def test_export_otlp_json_ids_are_stable_across_runs(trace_dir):
    _seed(trace_dir)
    first = runner.invoke(cli_mod.app, ["trace", "export", "-f", "otlp-json"]).stdout
    second = runner.invoke(cli_mod.app, ["trace", "export", "-f", "otlp-json"]).stdout
    assert first == second


def test_export_closes_a_turn_that_never_ended(trace_dir):
    """A crashed session has a turn_start and no turn_end; it still gets a span."""
    rec = Recorder(trace_dir / "trace.jsonl")
    rec.event("sess-c", "turn_start", task="interrupted")
    rec.event("sess-c", "model_call", step=1, model="m", input_tokens=1, output_tokens=1)
    rec.close()

    result = runner.invoke(cli_mod.app, ["trace", "export", "-f", "otlp-json"])
    spans = json.loads(result.stdout)["resourceSpans"][0]["scopeSpans"][0]["spans"]
    turn = next(s for s in spans if s["name"] == "turn")
    attrs = {a["key"]: a["value"] for a in turn["attributes"]}
    assert attrs["agent86.status"]["stringValue"] == "unfinished"
