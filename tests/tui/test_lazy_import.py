"""Regression guard: importing agent86.cli must not import textual (Pitfall 1)."""

from __future__ import annotations

import subprocess
import sys


def test_cli_import_does_not_import_textual():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, agent86.cli; assert 'textual' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
