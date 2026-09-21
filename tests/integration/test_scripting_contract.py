"""The scripting / CI contract, pinned.

Everything a script or a CI job is allowed to depend on lives here:

- ``agent86 run <goal> --json`` writes **one** JSON object to stdout, with a fixed set of
  keys. New keys may be added; these five may never be removed or renamed.
- the egress guardrail applies to that JSON as much as to the streamed text — a redact-mode
  config must not leak a key through the machine-readable path;
- a provider failure is exit code 1, a message on **stderr**, and nothing on stdout, so
  ``agent86 run ... > out.json`` never leaves a half-file that parses as success;
- approvals are explicit: piped (non-TTY) and without ``--yes``, side-effecting tools are
  declined; ``--yes`` runs them;
- ``--session`` continues an existing session rather than starting a new one;
- ``--plain`` / ``AGENT86_PLAIN`` never import Textual;
- the read-only inspection commands work on a machine with no config and no keys.

No network: the provider is faked at the router seam (``provider_for_model``), which is the
one place every code path — ``Harness.__init__``, ``set_model``, per-turn routing — goes
through.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from agent86 import cli as cli_mod
from agent86.cognitive.base import ModelProvider, ProviderError
from agent86.types import Completion, CompletionDelta, CompletionRequest, ToolCall, Usage

#: The keys `run --json` promises. Extra keys are allowed (the payload is additive);
#: these are the ones a script may rely on.
REQUIRED_JSON_KEYS = frozenset({"session_id", "output", "steps", "usage", "turn"})

runner = CliRunner()


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #


class _Fake(ModelProvider):
    """Streams ``reply``; optionally asks for one tool call on its first turn."""

    name = "fake"

    def __init__(self, reply: str = "all done", tool_call: ToolCall | None = None):
        self.model = "fake:scripting"
        self._reply = reply
        self._call = tool_call
        self.calls = 0

    def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
        self.calls += 1
        if self._call is not None and self.calls == 1:
            yield CompletionDelta(
                done=True,
                completion=Completion(
                    text="",
                    tool_calls=[self._call],
                    usage=Usage(input_tokens=5, output_tokens=2),
                    model=self.model,
                    stop_reason="tool_use",
                ),
            )
            return
        yield CompletionDelta(text=self._reply)
        yield CompletionDelta(
            done=True,
            completion=Completion(
                text=self._reply,
                usage=Usage(input_tokens=7, output_tokens=3),
                model=self.model,
                stop_reason="end_turn",
            ),
        )


#: The one thing these tests pin that a real fresh machine would not: the offline hash
#: embedder. The default (`sentence-transformers:...`) imports torch and looks in the HF
#: cache, which under a tmp HOME is empty — seconds of import time per test for a
#: dimension none of these assertions touch.
_BASE_CONFIG = """
[memory]
embeddings = "hash:64"
"""


@pytest.fixture
def fresh_home(tmp_path, monkeypatch):
    """A machine with no agent86 config, no keys, and an empty workspace.

    The user config path is an import-time constant (``Path.home()`` is read once), so it is
    repointed directly; everything that expands ``~`` at call time (the memory db, the trace
    directory) follows ``HOME`` / ``USERPROFILE``.
    """
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
    _project_config(work, "")
    return work


def _install(monkeypatch, provider: ModelProvider | Exception) -> None:
    """Make every provider construction yield ``provider`` (or raise it)."""

    def _factory(model: str, config):  # noqa: ANN001, ANN202
        if isinstance(provider, Exception):
            raise provider
        return provider

    monkeypatch.setattr("agent86.orchestration.router.provider_for_model", _factory)


def _project_config(work, body: str) -> None:
    (work / ".agent86").mkdir(exist_ok=True)
    (work / ".agent86" / "config.toml").write_text(
        _BASE_CONFIG + textwrap.dedent(body), encoding="utf-8"
    )


def _payload(result) -> dict:  # noqa: ANN001 - click Result
    assert result.exit_code == 0, result.output
    text = result.stdout.strip()
    assert text.startswith("{") and text.endswith("}"), text
    return json.loads(text)


# --------------------------------------------------------------------------- #
# run --json
# --------------------------------------------------------------------------- #


def test_run_json_emits_one_object_with_the_contract_keys(fresh_home, monkeypatch):
    _install(monkeypatch, _Fake("the answer"))

    result = runner.invoke(cli_mod.app, ["run", "what is the answer", "--json"])
    payload = _payload(result)

    assert REQUIRED_JSON_KEYS <= set(payload)
    assert payload["output"] == "the answer"
    assert payload["steps"] == 1
    assert isinstance(payload["session_id"], str) and payload["session_id"]
    assert payload["usage"]["output_tokens"] == 3
    # `turn` is the per-turn summary object (null only on a state that never ran one).
    assert payload["turn"] is not None and payload["turn"]["steps"] == 1


def test_run_json_writes_nothing_but_json_to_stdout(fresh_home, monkeypatch):
    """Degradation notes and the cost line go to stderr, so stdout stays parseable."""
    _install(monkeypatch, _Fake("hello"))

    result = runner.invoke(cli_mod.app, ["run", "hi", "--json"])

    assert result.exit_code == 0
    json.loads(result.stdout)  # the WHOLE of stdout is the object, not a prefix of it


def test_run_json_output_honours_the_egress_guardrail(fresh_home, monkeypatch):
    _project_config(fresh_home, """
        [guardrails]
        egress = "redact"
    """)
    leak = "the key is sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAA"
    _install(monkeypatch, _Fake(leak))

    payload = _payload(runner.invoke(cli_mod.app, ["run", "leak it", "--json"]))

    assert "sk-ant-" not in payload["output"]
    assert "[REDACTED:anthropic-key]" in payload["output"]


def test_run_exits_1_on_a_provider_error_with_stdout_clean(fresh_home, monkeypatch):
    _install(monkeypatch, ProviderError("ANTHROPIC_API_KEY is not set"))

    result = runner.invoke(cli_mod.app, ["run", "go", "--json"])

    assert result.exit_code == 1
    assert result.stdout.strip() == ""
    assert "ANTHROPIC_API_KEY is not set" in result.stderr


def test_run_exits_1_when_the_stream_fails_mid_turn(fresh_home, monkeypatch):
    class _Dies(_Fake):
        def stream(self, request: CompletionRequest) -> Iterator[CompletionDelta]:
            raise ProviderError("upstream returned 503")
            yield  # pragma: no cover - makes this a generator function

    _install(monkeypatch, _Dies())

    result = runner.invoke(cli_mod.app, ["run", "go", "--json"])

    assert result.exit_code == 1
    assert result.stdout.strip() == ""
    assert "503" in result.stderr


# --------------------------------------------------------------------------- #
# approvals
# --------------------------------------------------------------------------- #

WRITE = ToolCall(
    id="w1", name="write_file", arguments={"path": "out.txt", "content": "written\n"}
)


def test_piped_without_yes_declines_side_effects(fresh_home, monkeypatch):
    _install(monkeypatch, _Fake("tried", tool_call=WRITE))

    payload = _payload(runner.invoke(cli_mod.app, ["run", "write the file", "--json"]))

    assert not (fresh_home / "out.txt").exists()
    assert payload["steps"] == 2  # the call was made, answered "not executed", and observed


def test_yes_auto_approves_side_effects(fresh_home, monkeypatch):
    _install(monkeypatch, _Fake("wrote it", tool_call=WRITE))

    payload = _payload(runner.invoke(cli_mod.app, ["run", "write the file", "--json", "--yes"]))

    assert (fresh_home / "out.txt").read_text(encoding="utf-8") == "written\n"
    # `output` is every text delta of the turn, tool activity lines included; the answer
    # is the tail of it.
    assert payload["output"].endswith("wrote it")
    assert "[tool] write_file" in payload["output"]


# --------------------------------------------------------------------------- #
# sessions
# --------------------------------------------------------------------------- #


def test_session_resumes_the_same_session(fresh_home, monkeypatch):
    _install(monkeypatch, _Fake("first"))
    first = _payload(runner.invoke(cli_mod.app, ["run", "one", "--json"]))
    sid = first["session_id"]

    second = _payload(runner.invoke(cli_mod.app, ["run", "two", "--json", "--session", sid]))

    assert second["session_id"] == sid
    # The step counter is cumulative over the session, so a resumed turn continues it.
    assert second["steps"] == first["steps"] + 1


def test_an_unknown_session_starts_a_fresh_one(fresh_home, monkeypatch):
    _install(monkeypatch, _Fake("fresh"))

    payload = _payload(
        runner.invoke(cli_mod.app, ["run", "go", "--json", "--session", "nope-not-a-session"])
    )

    assert payload["session_id"] != "nope-not-a-session"
    assert payload["steps"] == 1


# --------------------------------------------------------------------------- #
# the plain path stays Textual-free
# --------------------------------------------------------------------------- #

_PLAIN_PROBE = """
import sys
from typer.testing import CliRunner
from agent86 import cli
CliRunner().invoke(cli.app, {argv})
print("TEXTUAL" if "textual" in sys.modules else "CLEAN")
"""


@pytest.mark.parametrize(
    ("argv", "env"),
    [
        ("['--plain']", {}),
        ("[]", {"AGENT86_PLAIN": "1"}),
        ("['run', 'hello']", {}),
    ],
    ids=["--plain", "AGENT86_PLAIN", "run"],
)
def test_the_scripting_paths_never_import_textual(argv, env, tmp_path):
    environ = {**os.environ, **env, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-c", _PLAIN_PROBE.format(argv=argv)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environ,
    )
    assert result.returncode == 0, result.stderr
    assert "CLEAN" in result.stdout, result.stdout + result.stderr


# --------------------------------------------------------------------------- #
# the read-only inspection commands
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "argv",
    [
        ["models"],
        ["config", "show"],
        ["config", "path"],
        ["skills", "list"],
        ["mcp", "list"],
        ["memory", "stats"],
    ],
    ids=lambda a: " ".join(a),
)
def test_inspection_commands_work_with_no_config_and_no_keys(argv, fresh_home):
    result = runner.invoke(cli_mod.app, argv)

    assert result.exit_code == 0, result.output + result.stderr
    assert "Traceback" not in result.output
