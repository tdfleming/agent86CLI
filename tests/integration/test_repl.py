"""REPL core — command dispatch, mode cycling, status — headless via a fake provider.

Since v0.6 ``_Repl.dispatch`` is a thin console renderer over the shared registry in
``agent86.tui.commands``, so these also pin the plain-mode (`agent86 --plain`) behavior of
every command the two surfaces have in common, plus the graceful degradation of the
TUI-only ones.
"""

from __future__ import annotations

from agent86.config import load_config
from agent86.orchestration.loop import Harness
from agent86.types import ApprovalMode, Message, Role
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


def test_cost_command_reports_cache_tokens_when_there_are_any(tmp_path, capsys):
    repl, _ = _repl(tmp_path)
    repl.state.usage.cache_read_tokens = 1900
    repl.state.usage.cache_creation_tokens = 200

    assert repl.dispatch("/cost") == "handled"

    out = capsys.readouterr().out
    assert "cache read 1900" in out and "written 200" in out


def test_cost_command_stays_quiet_about_a_cache_nobody_used(tmp_path, capsys):
    repl, _ = _repl(tmp_path)
    assert repl.dispatch("/cost") == "handled"
    assert "cache" not in capsys.readouterr().out


def test_cost_command_reports_cache_savings_when_pricing_offers_them(
    tmp_path, capsys, monkeypatch
):
    """`pricing.cache_savings` is optional (v0.8); when it exists /cost spends it."""
    from agent86.cognitive import pricing

    repl, _ = _repl(tmp_path)
    repl.state.usage.cache_read_tokens = 1900
    monkeypatch.setattr(pricing, "cache_savings", lambda ref, usage: 0.0421, raising=False)

    assert repl.dispatch("/cost") == "handled"
    assert "saved $0.0421" in capsys.readouterr().out


def test_cost_command_survives_an_incompatible_cache_savings(tmp_path, capsys, monkeypatch):
    """A signature we don't know how to call must degrade to the counts, never raise."""
    from agent86.cognitive import pricing

    repl, _ = _repl(tmp_path)
    repl.state.usage.cache_read_tokens = 1900

    def _savings(*, only_keywords):  # noqa: ANN001 - deliberately uncallable positionally
        raise AssertionError("should not be reached")

    monkeypatch.setattr(pricing, "cache_savings", _savings, raising=False)

    assert repl.dispatch("/cost") == "handled"
    out = capsys.readouterr().out
    assert "cache read 1900" in out and "saved" not in out


def test_status_window_prefers_the_harness_context_window(tmp_path):
    """When the harness publishes the window it budgets against, the gauge agrees with it."""
    repl, harness = _repl(tmp_path)
    object.__setattr__(harness, "context_window", 12_345)

    repl._refresh_status()

    assert repl.status.window == 12_345


def test_status_window_falls_back_when_the_harness_says_nothing(tmp_path):
    repl, harness = _repl(tmp_path)
    object.__setattr__(harness, "context_window", None)

    repl._refresh_status()

    assert repl.status.window == 8_192  # the per-model table's default for a fake provider


def test_status_carries_cumulative_cache_tokens(tmp_path):
    repl, _ = _repl(tmp_path)
    repl.state.usage.cache_read_tokens = 1800
    repl.state.usage.cache_creation_tokens = 100

    repl._refresh_status()

    assert repl.status.cached_tokens == 1900
    assert "(1.9k cached)" in repl.status_line()


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


# ---- startup diagnostics ------------------------------------------------- #


def test_registry_collisions_surface_as_a_startup_note(tmp_path):
    """A tool that lost its name is not callable — saying nothing looks like a dead server."""
    repl, harness = _repl(tmp_path)
    harness.registry.collisions = ["mcp__a__search", "read_file"]

    from agent86.tui.commands import startup_notes

    notes = startup_notes(repl)
    line = next(n for n in notes if n.startswith("tools: "))
    assert "mcp__a__search" in line and "read_file" in line
    assert "not callable" in line


def test_no_collision_note_when_every_tool_kept_its_name(tmp_path):
    repl, harness = _repl(tmp_path)
    assert harness.registry.collisions == []

    from agent86.tui.commands import startup_notes

    assert not any(n.startswith("tools: ") for n in startup_notes(repl))


def test_every_mcp_note_gets_its_own_startup_line(tmp_path):
    """Several bad servers used to collapse into one newline-joined blob."""
    from agent86.tools.mcp_client import MCPManager
    from agent86.tui.commands import startup_notes

    repl, harness = _repl(tmp_path)
    manager = MCPManager({})
    manager._add_note("MCP server 'alpha' failed to start: boom")
    manager._add_note("MCP server 'beta' failed to start: nope")
    harness.mcp = manager

    lines = [n for n in startup_notes(repl) if n.startswith("mcp: ")]
    assert lines == [
        "mcp: MCP server 'alpha' failed to start: boom",
        "mcp: MCP server 'beta' failed to start: nope",
    ]


def test_mcp_and_collision_notes_are_markup_escaped(tmp_path):
    from agent86.tools.mcp_client import MCPManager
    from agent86.tui.commands import startup_notes

    repl, harness = _repl(tmp_path)
    manager = MCPManager({})
    manager._add_note("MCP server 'a' failed to start: [boom]")
    harness.mcp = manager
    harness.registry.collisions = ["mcp__a__[x]"]

    notes = startup_notes(repl)
    assert any(r"\[boom]" in n for n in notes)
    assert any(r"mcp__a__\[x]" in n for n in notes)


# ---- prompt history (plain loop) ----------------------------------------- #


def _history_repl(tmp_path):
    """A _Repl whose history file lives in tmp_path rather than the real home."""
    repl, harness = _repl(tmp_path)
    repl.cfg.ui.history_file = str(tmp_path / "history")
    return repl, harness


def _drive(repl, monkeypatch, lines):
    """Run plain_loop over ``lines``, then EOF out of it."""
    pending = list(lines)

    def _fake_input(_prompt=""):
        if not pending:
            raise EOFError
        return pending.pop(0)

    monkeypatch.setattr("builtins.input", _fake_input)
    repl.plain_loop()


def test_plain_loop_records_submitted_prompts(tmp_path, monkeypatch, capsys):
    from agent86.ui.history import PromptHistory

    repl, _ = _history_repl(tmp_path)
    _drive(repl, monkeypatch, ["hello there", "/cost"])
    capsys.readouterr()

    assert repl.history.entries == ["hello there", "/cost"]
    # The shared file, not just this session's memory.
    assert PromptHistory(tmp_path / "history").entries == ["hello there", "/cost"]


def test_plain_loop_honours_the_leading_space_escape_hatch(tmp_path, monkeypatch, capsys):
    repl, _ = _history_repl(tmp_path)
    _drive(repl, monkeypatch, [" /cost", "/cost"])
    capsys.readouterr()

    assert repl.history.entries == ["/cost"]


def test_history_is_not_built_until_it_is_used(tmp_path):
    """Constructing a _Repl must not touch the user's real history file."""
    repl, _ = _repl(tmp_path)
    assert repl._history is None


# ---- @file mentions (plain loop) ----------------------------------------- #


def test_plain_loop_expands_mentions_before_sending(tmp_path, monkeypatch, capsys):
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")
    repl, _ = _history_repl(tmp_path)
    _drive(repl, monkeypatch, ["explain @app.py"])
    capsys.readouterr()

    sent = repl.state.messages[0].content
    assert sent.startswith("explain @app.py")
    assert "--- @app.py (1 lines) ---" in sent
    assert "print('hi')" in sent
    # The history keeps what the user typed, not the expansion.
    assert repl.history.entries == ["explain @app.py"]


def test_plain_loop_reports_a_refused_mention(tmp_path, monkeypatch, capsys):
    repl, _ = _history_repl(tmp_path)
    _drive(repl, monkeypatch, ["read @nope.py"])
    out = capsys.readouterr().out

    assert "no such file or directory" in out
    assert "no such file or directory" in repl.state.messages[0].content


def test_expand_mentions_is_jailed_by_the_harness_policy(tmp_path):
    repl, harness = _repl(tmp_path)
    outside = tmp_path.parent / "repl-outside.txt"
    outside.write_text("SECRET", encoding="utf-8")
    try:
        result = repl.expand_mentions(f'@"{outside}"')
    finally:
        outside.unlink()
    assert result.attachments == []
    assert "outside the workspace" in result.errors[0]
    assert harness.policy.workspace == tmp_path.resolve()


def test_expand_mentions_honours_the_configured_cap(tmp_path):
    (tmp_path / "big.txt").write_text("z" * 4000, encoding="utf-8")
    repl, _ = _repl(tmp_path)
    repl.cfg.tools.mention_max_bytes = 100
    result = repl.expand_mentions("@big.txt")
    assert "over the 100-byte mention cap" in result.errors[0]


# ---- /sessions and /resume (plain loop) ---------------------------------- #


def _memory_repl(tmp_path):
    from agent86.memory.embeddings import HashingEmbedder
    from agent86.memory.episodic import EpisodicMemory
    from agent86.memory.semantic import SemanticMemory
    from agent86.memory.store import MemoryStore
    from agent86.memory.system import MemorySystem

    store = MemoryStore(tmp_path / "mem.db", HashingEmbedder(64))
    memory = MemorySystem(
        store=store, episodic=EpisodicMemory(store), semantic=SemanticMemory(store)
    )
    cfg = load_config()
    cfg.ui.history_file = str(tmp_path / "history")
    harness = Harness(
        cfg, provider=make_text_provider("hi there"), memory=memory, workspace=tmp_path
    )
    return _Repl(cfg, resume=None, harness=harness), harness, store


def test_plain_loop_sessions_prints_the_table(tmp_path, monkeypatch, capsys):
    repl, _, store = _memory_repl(tmp_path)
    store.save_session("beefcafe1111", "{}", title="a session to find")
    _drive(repl, monkeypatch, ["/sessions"])
    out = capsys.readouterr().out
    assert "beefcafe" in out
    assert "a session to find" in out


def test_plain_loop_resume_replaces_the_state(tmp_path, monkeypatch, capsys):
    repl, harness, _ = _memory_repl(tmp_path)
    saved = harness.new_session()
    _drive(repl, monkeypatch, ["remember this", f"/resume {saved.session_id}"])
    capsys.readouterr()
    assert repl.state.session_id == saved.session_id


def test_resume_note_names_the_session(tmp_path):
    """--resume says WHICH conversation you walked back into, not just its id."""
    repl, harness, store = _memory_repl(tmp_path)
    saved = harness.new_session()
    saved.add_message(Message(role=Role.USER, content="the named conversation"))
    harness._persist(saved)

    resumed = _Repl(repl.cfg, resume=saved.session_id, harness=harness)
    assert any("the named conversation" in n for n in resumed.resume_notes)


# ---- the plain loop's approval prompt ------------------------------------ #


def _tty(monkeypatch, interactive: bool = True) -> None:
    """Make (or unmake) stdin look like a terminal, whatever pytest captured it with."""
    from types import SimpleNamespace

    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: interactive))


def _write_repl(tmp_path, approval=ApprovalMode.ASK):
    """A _Repl whose one turn asks to write `out.txt`."""
    from agent86.types import ToolCall
    from tests.support import ToolThenTextProvider

    cfg = load_config()
    cfg.guardrails.approval = approval
    cfg.ui.history_file = str(tmp_path / "history")
    call = ToolCall(id="c1", name="write_file", arguments={"path": "out.txt", "content": "hi\n"})
    harness = Harness(
        cfg, provider=ToolThenTextProvider(call, reply="done"), memory=None, workspace=tmp_path
    )
    return _Repl(cfg, resume=None, harness=harness), harness


def test_plain_loop_asks_before_a_side_effect_and_runs_it_on_yes(tmp_path, monkeypatch, capsys):
    """Without a prompt installed, `ask` mode declined every write in the plain loop."""
    _tty(monkeypatch)
    repl, harness = _write_repl(tmp_path)
    _drive(repl, monkeypatch, ["write the file", "y"])
    out = capsys.readouterr().out

    assert harness.gate.prompt is not None
    assert "approve write_file?" in out
    # The preview detail — the diff of what would be written — is shown ABOVE the question.
    assert "new file: out.txt" in out
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hi\n"


def test_plain_loop_declines_on_anything_but_yes(tmp_path, monkeypatch, capsys):
    _tty(monkeypatch)
    repl, _ = _write_repl(tmp_path)
    _drive(repl, monkeypatch, ["write the file", ""])
    out = capsys.readouterr().out

    assert "declined by user" in out
    assert not (tmp_path / "out.txt").exists()


def test_no_prompt_is_installed_without_a_tty(tmp_path, monkeypatch, capsys):
    """Piped stdin / CI keeps the old behaviour: decline, rather than block on a question."""
    _tty(monkeypatch, interactive=False)
    repl, harness = _write_repl(tmp_path)
    _drive(repl, monkeypatch, ["write the file"])
    capsys.readouterr()

    assert harness.gate.prompt is None
    assert not (tmp_path / "out.txt").exists()


def test_auto_mode_never_reaches_the_prompt(tmp_path, monkeypatch, capsys):
    _tty(monkeypatch)
    repl, _ = _write_repl(tmp_path, approval=ApprovalMode.AUTO)
    _drive(repl, monkeypatch, ["write the file"])
    out = capsys.readouterr().out

    assert "approve write_file?" not in out
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hi\n"


def test_approval_prompt_declines_when_stdin_ends(monkeypatch, capsys):
    from agent86.ui.repl import approval_prompt

    def _eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    assert approval_prompt("run_command", "ls") is False


def test_approval_prompt_caps_a_runaway_detail(monkeypatch, capsys):
    from agent86.guardrails.policy import ApprovalPreview
    from agent86.ui.repl import APPROVAL_DETAIL_LINES, approval_prompt

    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    detail = "\n".join(f"line {i}" for i in range(APPROVAL_DETAIL_LINES + 50))
    assert approval_prompt("write_file", ApprovalPreview("{}", detail)) is True
    out = capsys.readouterr().out
    assert "truncated (50 more lines)" in out


def test_install_approval_prompt_leaves_an_existing_one_alone(tmp_path, monkeypatch):
    from agent86.ui.repl import install_approval_prompt

    _tty(monkeypatch)
    _, harness = _write_repl(tmp_path)
    harness.gate.prompt = lambda name, preview: True
    assert install_approval_prompt(harness) is False
