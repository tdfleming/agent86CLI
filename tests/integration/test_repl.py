"""REPL core — command dispatch, mode cycling, status — headless via a fake provider.

Since v0.6 ``_Repl.dispatch`` is a thin console renderer over the shared registry in
``agent86.tui.commands``, so these also pin the plain-mode (`agent86 --plain`) behavior of
every command the two surfaces have in common, plus the graceful degradation of the
TUI-only ones.
"""

from __future__ import annotations

from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.types import ApprovalMode
from agent86.ui.repl import _Repl
from tests.support import make_text_provider


def _repl(tmp_path):
    cfg = load_config()
    harness = Harness(cfg, provider=make_text_provider("hi there"), memory=None, workspace=tmp_path)
    return _Repl(cfg, resume=None, harness=harness), harness


def test_dispatch_routes_commands_and_turns(tmp_path):
    repl, _ = _repl(tmp_path)
    assert repl.dispatch("") == "handled"
    assert repl.dispatch("/help") == "handled"
    assert repl.dispatch("/tools") == "handled"
    assert repl.dispatch("/unknowncmd") == "handled"  # unknown slash cmd is swallowed
    assert repl.dispatch("hello world") == "turn"
    assert repl.dispatch("/exit") == "exit"


def test_dispatch_uses_the_shared_command_registry(tmp_path, monkeypatch):
    """One implementation, two surfaces: the plain loop must not re-parse commands itself."""
    from agent86.tui import commands as commands_mod

    repl, _ = _repl(tmp_path)
    seen: list[str] = []
    real = commands_mod.handle_command

    def _spy(r, line):  # noqa: ANN001
        seen.append(line)
        return real(r, line)

    monkeypatch.setattr(commands_mod, "handle_command", _spy)
    repl.dispatch("/cost")
    assert seen == ["/cost"]


def test_help_prints_the_registry_table(tmp_path, capsys):
    from agent86.tui.commands import COMMANDS

    repl, _ = _repl(tmp_path)
    assert repl.dispatch("/help") == "handled"
    out = capsys.readouterr().out
    for entry in COMMANDS:
        assert entry.name in out


def test_quit_is_an_alias_for_exit(tmp_path, capsys):
    repl, _ = _repl(tmp_path)
    assert repl.dispatch("/quit") == "exit"
    assert "bye" in capsys.readouterr().out


def test_cost_command_prints_usage(tmp_path, capsys):
    repl, _ = _repl(tmp_path)
    assert repl.dispatch("/cost") == "handled"
    out = capsys.readouterr().out
    assert "steps" in out and "cost" in out


def test_config_model_degrades_gracefully_in_plain_mode(tmp_path, capsys):
    """The model manager is a TUI surface; in plain mode it says so rather than failing."""
    repl, _ = _repl(tmp_path)
    assert repl.dispatch("/config model") == "handled"
    assert "TUI surface" in capsys.readouterr().out


def test_mode_command_sets_and_cycles(tmp_path, capsys):
    repl, harness = _repl(tmp_path)
    assert repl.dispatch("/mode auto") == "handled"
    assert harness.gate.mode is ApprovalMode.AUTO
    assert "approval mode: auto" in capsys.readouterr().out
    assert repl.dispatch("/mode deny") == "handled"
    assert harness.gate.mode is ApprovalMode.DENY
    # bare /mode cycles: deny -> ask
    repl.dispatch("/mode")
    assert harness.gate.mode is ApprovalMode.ASK
    # invalid mode leaves it unchanged
    capsys.readouterr()
    repl.dispatch("/mode nonsense")
    assert harness.gate.mode is ApprovalMode.ASK
    assert "unknown mode" in capsys.readouterr().out


def test_hotkey_cycle_updates_gate_and_status(tmp_path):
    repl, harness = _repl(tmp_path)
    start = harness.gate.mode
    repl._cycle_approval()
    assert harness.gate.mode is not start
    assert repl.status.approval == harness.gate.mode.value


def test_model_command_switches_active_model(tmp_path, monkeypatch, capsys):
    repl, harness = _repl(tmp_path)
    # Switch to a keyless local provider (Ollama needs no API key).
    assert repl.dispatch("/model ollama:llama3.1") == "handled"
    assert harness.provider.name == "ollama"
    assert harness.provider.model == "llama3.1"
    assert repl.status.model == "llama3.1"  # status line updated
    assert "ollama:llama3.1" in capsys.readouterr().out

    # A slash-containing model id on a keyed provider works once its key is set.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    repl.dispatch("/model openrouter:anthropic/claude-3.7-sonnet")
    assert harness.provider.model == "anthropic/claude-3.7-sonnet"


def test_bare_model_command_shows_current_model(tmp_path, capsys):
    repl, harness = _repl(tmp_path)
    assert repl.dispatch("/model") == "handled"
    out = capsys.readouterr().out
    assert "current model" in out and harness.provider.model in out


def test_model_command_rejects_bad_ref_and_missing_key(tmp_path, monkeypatch, capsys):
    repl, harness = _repl(tmp_path)
    repl.dispatch("/model ollama:llama3.1")
    before = harness.provider.model
    # Malformed ref (no colon) -> ValueError -> model unchanged, error surfaced.
    capsys.readouterr()
    repl.dispatch("/model not-a-ref")
    assert harness.provider.model == before
    assert "provider:model" in capsys.readouterr().out
    # Missing API key -> ProviderError -> model unchanged.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    repl.dispatch("/model openai:gpt-4o")
    assert harness.provider.model == before


def test_startup_notes_are_collected_not_printed(tmp_path, capsys):
    """Constructing the REPL must stay silent — the TUI hides stdout behind its screen."""
    repl, _ = _repl(tmp_path)
    assert capsys.readouterr().out == ""
    assert any(n.startswith("session ") for n in repl.startup_notes)

    repl.print_notes()
    out = capsys.readouterr().out
    assert repl.state.session_id in out


def test_resume_miss_is_recorded_as_a_startup_note(tmp_path, capsys):
    cfg = load_config()
    harness = Harness(cfg, provider=make_text_provider("hi"), memory=None, workspace=tmp_path)
    repl = _Repl(cfg, resume="no-such-session", harness=harness)

    assert capsys.readouterr().out == ""
    assert repl.resume_notes == ["no session 'no-such-session' found; starting fresh"]
    # and it leads the notes the TUI transcript / plain banner area shows
    assert repl.startup_notes[0] == repl.resume_notes[0]


def test_status_line_reflects_state(tmp_path):
    repl, harness = _repl(tmp_path)
    repl._refresh_status()
    line = repl.status_line()
    assert harness.provider.model in line
    assert "mode:" in line and "sbx" in line


def test_status_carries_the_full_model_ref_for_price_lookup(tmp_path):
    """`model` is the short display label; price lookup needs `provider:model`.

    Without the ref a local model is indistinguishable from an unpriced one, so an Ollama
    user would read "cost n/a" where $0.0000 is the truth.
    """
    from agent86.ui.status import UNPRICED_LABEL

    repl, harness = _repl(tmp_path)
    repl.dispatch("/model ollama:llama3.1")  # keyless local provider

    assert repl.status.model == "llama3.1"  # display label stays bare
    assert repl.status.model_ref == "ollama:llama3.1"  # lookup ref is fully qualified
    assert UNPRICED_LABEL not in repl.status_line()
    assert "$0.0000" in repl.status_line()

    # and it is set at construction too, not only after a /model switch
    fresh = _Repl(repl.cfg, resume=None, harness=harness)
    p = harness.provider
    assert fresh.status.model_ref == f"{p.name}:{p.model}"


def test_unknown_command_echo_is_markup_escaped(tmp_path, capsys):
    """The plain loop must not blow up on an unknown command that looks like Rich markup.

    `handle_command` echoes the raw line back, and `_Repl.dispatch` hands that straight to
    `Console.print`, which parses markup. `[/bar]` is a closing tag with nothing open, so an
    unescaped echo raises `MarkupError` — out of the REPL's own input loop, where there is
    nothing to catch it. Same class of bug as the transcript escaping in
    `tests/tui/test_transcript_escape.py`, on the other surface.
    """
    repl, _ = _repl(tmp_path)

    assert repl.dispatch("/foo [/bar]") == "handled"

    out = capsys.readouterr().out
    assert "/foo [/bar]" in out  # echoed verbatim, tags shown as text


def test_unknown_command_markup_is_not_interpreted(tmp_path, capsys):
    """A well-formed tag must render as text, not as styling — no injection into the console."""
    repl, _ = _repl(tmp_path)

    assert repl.dispatch("/foo [bold red]loud[/bold red]") == "handled"

    out = capsys.readouterr().out
    assert "[bold red]loud[/bold red]" in out


def test_handle_command_escapes_the_unknown_line_itself(tmp_path):
    """Pin the escaping at the source, so the TUI surface is covered by the same guarantee."""
    import io

    from rich.console import Console

    from agent86.tui.commands import handle_command

    repl, _ = _repl(tmp_path)
    result = handle_command(repl, "/foo [/bar]")

    assert result.action == "handled"
    assert result.render == r"unknown command /foo \[/bar]"
    # And the escaped form survives a real markup parse.
    buf = io.StringIO()
    Console(file=buf, width=200).print(result.render)
    assert "/foo [/bar]" in buf.getvalue()
