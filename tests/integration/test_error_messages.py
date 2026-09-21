"""Every error a first-run user can hit must say what to do next.

The failures below are the common ones — a typo'd ``--model``, a provider prefix that
isn't configured, no API key, memory turned off, a memory database that won't open, no MCP
servers — and each assertion is the same shape: the message names the *fix* (an env var, a
config key, a command to run), and it never prints a secret to do it.

They are deliberately asserted on the surface a user actually sees (the CLI, via
``CliRunner``) rather than on the exception text, because the gap this guards against is
not a missing string — it is a message that never reaches the user at all, because the
call site let the exception through as a traceback.
"""

from __future__ import annotations

import textwrap

import pytest
from typer.testing import CliRunner

from agent86 import cli as cli_mod

runner = CliRunner()

_BASE_CONFIG = """
[memory]
embeddings = "hash:64"
"""


@pytest.fixture
def fresh_home(tmp_path, monkeypatch):
    """A machine with no agent86 config and no API keys (see test_scripting_contract)."""
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr("agent86.config.USER_CONFIG_DIR", home / ".agent86")
    monkeypatch.setattr("agent86.config.USER_CONFIG_PATH", home / ".agent86" / "config.toml")
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(work)
    _write_config(work, "")
    return work


def _write_config(work, body: str) -> None:
    (work / ".agent86").mkdir(exist_ok=True)
    (work / ".agent86" / "config.toml").write_text(
        _BASE_CONFIG + textwrap.dedent(body), encoding="utf-8"
    )


def _said(result) -> str:  # noqa: ANN001 - click Result
    """Everything the user saw, on one line.

    Whitespace is collapsed because Rich wraps to the console width: a message is not less
    actionable for having a newline in the middle of `agent86 config path`, and asserting on
    the wrapped form would make these tests a function of the terminal size.
    """
    combined = result.stdout + result.stderr
    assert "Traceback (most recent call last)" not in combined, combined
    return " ".join(combined.split())


# --------------------------------------------------------------------------- #
# 1. a model ref that isn't `provider:model`
# --------------------------------------------------------------------------- #


def test_a_malformed_model_ref_explains_the_format_and_how_to_list_models(fresh_home):
    result = runner.invoke(cli_mod.app, ["--model", "nonsense", "run", "hi"])

    said = _said(result)
    assert result.exit_code == 1
    assert "provider:model" in said
    assert "agent86 models" in said


# --------------------------------------------------------------------------- #
# 2. a provider prefix nothing is configured for
# --------------------------------------------------------------------------- #


def test_an_unknown_provider_prefix_names_both_ways_out(fresh_home):
    result = runner.invoke(cli_mod.app, ["--model", "bogus:some-model", "run", "hi"])

    said = _said(result)
    assert result.exit_code == 1
    assert "bogus" in said
    # Either add a provider block for it...
    assert "base_url" in said
    # ...or go and look at the ones that already work.
    assert "agent86 models" in said


# --------------------------------------------------------------------------- #
# 3. a missing API key — names the VARIABLE, never a value
# --------------------------------------------------------------------------- #


def test_a_missing_key_names_the_env_var_to_set(fresh_home):
    _write_config(fresh_home, """
        [providers.needy]
        base_url = "https://example.invalid/v1"
        api_key_env = "NEEDY_API_KEY"
    """)

    result = runner.invoke(cli_mod.app, ["--model", "needy:some-model", "run", "hi"])

    said = _said(result)
    assert result.exit_code == 1
    assert "NEEDY_API_KEY" in said


def test_the_key_report_never_prints_the_key_itself(fresh_home, monkeypatch):
    """`agent86 models` says where each key comes from; the value is never renderable."""
    secret = "sk-ant-api03-NEVERPRINTTHIS0000000000"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)

    result = runner.invoke(cli_mod.app, ["models"])

    said = _said(result)
    assert result.exit_code == 0
    assert secret not in said
    assert "ANTHROPIC_API_KEY" in said  # the NAME is what the user needs to see


# --------------------------------------------------------------------------- #
# 4/5. memory: turned off, and unable to open
# --------------------------------------------------------------------------- #


def test_memory_disabled_says_which_key_turns_it_on(fresh_home):
    # Written whole rather than appended: the base config already opens a [memory] table.
    (fresh_home / ".agent86" / "config.toml").write_text(
        "[memory]\nenabled = false\n", encoding="utf-8"
    )

    result = runner.invoke(cli_mod.app, ["memory", "stats"])

    said = _said(result)
    assert result.exit_code == 1
    assert "enabled = true" in said
    assert "agent86 config path" in said


def test_an_unopenable_memory_db_says_what_to_change(tmp_path):
    """The store raises its own error rather than leaking a bare sqlite3 exception."""
    from agent86.memory.embeddings import HashingEmbedder
    from agent86.memory.store import MemoryStore, MemoryStoreError

    # A directory where the database file should be: sqlite cannot open it, on any OS.
    blocked = tmp_path / "memory.db"
    blocked.mkdir()

    with pytest.raises(MemoryStoreError) as excinfo:
        MemoryStore(blocked, HashingEmbedder(16))

    message = str(excinfo.value)
    assert str(blocked) in message
    assert "memory] path" in message  # where to point it instead
    assert "enabled = false" in message  # or how to turn it off


def test_the_harness_runs_without_memory_rather_than_crashing(tmp_path, monkeypatch):
    """A db that won't open costs recall, not the session."""
    from agent86.config import load_config
    from agent86.memory.store import MemoryStoreError
    from agent86.orchestration.loop import Harness
    from tests.support import TextProvider

    def _explode(config):  # noqa: ANN001, ANN202
        raise MemoryStoreError("Could not open the memory database at X - locked.")

    monkeypatch.setattr("agent86.orchestration.loop.build_memory", _explode)
    harness = Harness(load_config(), provider=TextProvider("fine"), workspace=tmp_path)

    assert harness.memory is None
    assert harness.memory_note is not None
    assert "without recall" in harness.memory_note
    # And a turn still runs.
    streamed = "".join(d.text for d in harness.run_turn("go", harness.new_session()) if d.text)
    assert "fine" in streamed


# --------------------------------------------------------------------------- #
# 6. MCP with nothing configured
# --------------------------------------------------------------------------- #


def test_no_mcp_servers_says_how_to_add_one(fresh_home):
    result = runner.invoke(cli_mod.app, ["mcp", "list"])

    said = _said(result)
    assert result.exit_code == 0
    assert "mcp_servers" in said
    assert "/config mcp" in said


# --------------------------------------------------------------------------- #
# 7. a config file that doesn't parse
# --------------------------------------------------------------------------- #


def test_a_malformed_config_names_the_file_instead_of_crashing(fresh_home):
    """Every command reads config, so a broken file used to break all of them at once."""
    (fresh_home / ".agent86" / "config.toml").write_text("[memory\n", encoding="utf-8")

    result = runner.invoke(cli_mod.app, ["models"])

    said = _said(result)
    assert result.exit_code == 1
    assert "config.toml" in said
    assert "agent86 config path" in said
