"""Regression guard: importing agent86.cli must not import textual, keyring, or tomlkit."""

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


def test_cli_import_does_not_import_keyring_or_tomlkit():
    """D-22: `run` (one-shot) and `--plain` cold start must not pay for keyring/tomlkit."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, agent86.cli; "
            "assert 'keyring' not in sys.modules, 'keyring imported eagerly'; "
            "assert 'tomlkit' not in sys.modules, 'tomlkit imported eagerly'",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
