"""Shared test fixtures."""

from __future__ import annotations

import pytest

import agent86.orchestration.loop as loop_mod
from agent86.observability.recorder import Recorder


@pytest.fixture(autouse=True)
def _no_home_writes(monkeypatch):
    """Keep the Harness from writing the flight recorder into the real ~/.agent86 in tests."""
    monkeypatch.setattr(loop_mod, "build_recorder", lambda config: Recorder(None))
