"""Wave 0 test scaffolding: a stub harness fixture for turn_bridge unit tests."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from agent86.guardrails.policy import ApprovalGate
from agent86.types import ApprovalMode, CompletionDelta


class _FakeHarness:
    """A lightweight stand-in for ``Harness`` exposing only what turn_bridge needs.

    ``gate`` reuses the real ``ApprovalGate`` so ``gate.prompt`` is a genuine seam
    (turn_bridge assigns to it, exactly like the real Harness). ``run_turn`` streams a
    text delta, a tool-announce delta, blocks on ``gate.prompt`` mid-iteration (mirroring
    a real approval-gated tool call), then yields a final delta reporting the outcome.
    """

    def __init__(self) -> None:
        self.gate = ApprovalGate(ApprovalMode.ASK)
        self.last_ok: bool | None = None

    def run_turn(self, line: str, state) -> Iterator[CompletionDelta]:
        yield CompletionDelta(text="hello ")
        yield CompletionDelta(text='\n[tool] write_file({"path": "x"})\n')
        ok = self.gate.prompt("write_file", '{"path": "x"}')
        self.last_ok = ok
        yield CompletionDelta(text=f"[tool] write_file -> {'ok' if ok else 'no'}\n")


class _RaisingHarness:
    """A stub harness whose ``run_turn`` raises before yielding a final delta."""

    def __init__(self, exc: BaseException) -> None:
        self.gate = ApprovalGate(ApprovalMode.ASK)
        self._exc = exc

    def run_turn(self, line: str, state) -> Iterator[CompletionDelta]:
        yield CompletionDelta(text="hello ")
        raise self._exc


@pytest.fixture
def fake_harness() -> _FakeHarness:
    return _FakeHarness()


@pytest.fixture
def raising_harness():
    def _make(exc: BaseException) -> _RaisingHarness:
        return _RaisingHarness(exc)

    return _make


@pytest.fixture
def fake_state():
    return SimpleNamespace()
