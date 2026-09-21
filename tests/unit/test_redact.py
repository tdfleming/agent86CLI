"""v1.0 — trace redaction (``observability/redact.py``).

The flight recorder outlives the session, so the contract under test is: nothing
secret-shaped reaches the file, nothing unbounded reaches the file, and nothing the loop
can hand the recorder makes redaction raise.
"""

from __future__ import annotations

from pathlib import Path

from agent86.observability.recorder import Recorder, read_events
from agent86.observability.redact import REDACTED, redact_event

FAKE_KEY = "sk-ant-api03-" + "A" * 40


def test_secret_in_nested_arguments_is_redacted():
    event = {
        "ts": 1.0,
        "session": "s1",
        "kind": "tool_call",
        "arguments": {"env": {"headers": ["Authorization", FAKE_KEY]}},
    }
    out = redact_event(event)
    flat = repr(out)
    assert FAKE_KEY not in flat
    assert REDACTED in flat
    # Structure is preserved — only the leaf changed.
    assert out["arguments"]["env"]["headers"][0] == "Authorization"


def test_openai_and_key_shaped_tokens_are_redacted():
    event = {"kind": "turn_start", "task": "use sk-" + "b" * 30 + " and gsk_" + "c" * 25}
    out = redact_event(event)
    assert "sk-bbb" not in out["task"]
    assert "gsk_ccc" not in out["task"]


def test_long_content_is_truncated_with_a_marker():
    event = {"kind": "observation", "content": "x" * 5000}
    out = redact_event(event, max_field_chars=100)
    assert out["content"].startswith("x" * 100)
    assert "[truncated 4900 chars]" in out["content"]
    assert len(out["content"]) < 200


def test_truncation_is_inherited_into_nested_argument_values():
    event = {"kind": "tool_call", "arguments": {"body": "y" * 900}}
    out = redact_event(event, max_field_chars=50)
    assert "[truncated 850 chars]" in out["arguments"]["body"]


def test_short_fields_and_non_text_fields_pass_through():
    event = {"ts": 1.5, "session": "s1", "kind": "model_call", "step": 3, "ok": True}
    assert redact_event(event) == event


def test_none_mode_passes_through_untouched():
    event = {"kind": "turn_start", "task": FAKE_KEY + " " + "z" * 5000}
    assert redact_event(event, mode="none") is event


def test_non_serialisable_values_fall_back_to_str():
    class Exploding:
        def __repr__(self) -> str:
            return f"<Exploding {FAKE_KEY}>"

        __str__ = __repr__

    event = {"kind": "tool_call", "arguments": {"obj": Exploding(), "p": Path("/tmp/x")}}
    out = redact_event(event)  # must not raise
    assert FAKE_KEY not in repr(out)
    assert isinstance(out["arguments"]["obj"], str)


def test_cyclic_structures_do_not_recurse_forever():
    inner: dict = {"kind": "deep"}
    inner["self"] = inner
    out = redact_event({"kind": "tool_call", "arguments": inner})  # must not hang or raise
    assert out["kind"] == "tool_call"


def test_recorder_redacts_on_write(tmp_path):
    path = tmp_path / "trace.jsonl"
    rec = Recorder(path, max_field_chars=80)
    rec.event("s1", "tool_call", arguments={"key": FAKE_KEY}, content="q" * 400)
    rec.close()

    (event,) = read_events(path)
    assert FAKE_KEY not in path.read_text(encoding="utf-8")
    assert event["arguments"]["key"] == REDACTED
    assert "[truncated 320 chars]" in event["content"]


def test_recorder_redact_none_writes_verbatim(tmp_path):
    path = tmp_path / "trace.jsonl"
    rec = Recorder(path, redact="none")
    rec.event("s1", "turn_start", task=FAKE_KEY)
    rec.close()
    assert read_events(path)[0]["task"] == FAKE_KEY


def test_build_recorder_honours_config(tmp_path):
    from agent86.config import Config

    cfg = Config()
    cfg.observability.path = str(tmp_path)
    cfg.observability.max_field_chars = 12
    from agent86.observability.recorder import build_recorder

    rec = build_recorder(cfg)
    try:
        assert rec.redact == "secrets"
        assert rec.max_field_chars == 12
    finally:
        rec.close()
