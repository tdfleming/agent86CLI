"""Graceful degradation: every optional dependency can be missing, and a turn still runs.

agent86's core install is deliberately small — ``mcp``, ``keyring``, ``sentence-transformers``,
Docker, OpenTelemetry, ``beautifulsoup4`` and ``PyYAML`` are all extras. On a machine without
one of them the rule is the same every time: the feature degrades, the harness says so in a
one-line note, and the turn goes through. Nothing raises, and nothing is silently skipped.

Each case hides one dependency by poisoning ``sys.modules`` (the parent package *and* any
already-imported submodule, so a cached ``opentelemetry.sdk.trace`` cannot sneak the import
back in), builds a real ``Harness`` around a fake provider in a tmp workspace, and runs one
turn. Docker is the exception: nothing imports a ``docker`` module — availability is the
``docker`` executable — so its absence is simulated where the code actually looks.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import pytest

from agent86.config import Config, MCPServerConfig, load_config
from agent86.orchestration.loop import Harness
from tests.support import TextProvider


def _hide(monkeypatch, name: str) -> None:
    """Make ``import <name>`` (and any submodule of it) fail with ImportError."""
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            monkeypatch.setitem(sys.modules, key, None)
    monkeypatch.setitem(sys.modules, name, None)


# --------------------------------------------------------------------------- #
# per-dependency configuration — only the feature under test is switched on, so
# a case never pays for a dependency it isn't about.
# --------------------------------------------------------------------------- #


def _needs_mcp(cfg: Config) -> None:
    cfg.mcp_servers = {
        "probe": MCPServerConfig(command="this-command-does-not-exist", transport="stdio")
    }


def _needs_embeddings(cfg: Config) -> None:
    cfg.memory.embeddings = "sentence-transformers:all-MiniLM-L6-v2"


def _needs_docker(cfg: Config) -> None:
    cfg.sandbox.mode = "docker"


def _needs_otel(cfg: Config) -> None:
    cfg.observability.otel = True


def _nothing(cfg: Config) -> None:
    return None


#: ``(dependency, configure, note attribute, expected substring)``. A note of ``None``
#: means this dependency has no harness-level note — the assertion is simply that building
#: and running the harness is unaffected.
CASES: list[tuple[str, Callable[[Config], None], str | None, str | None]] = [
    ("mcp", _needs_mcp, "mcp_note", "mcp package not installed"),
    ("keyring", _nothing, None, None),
    ("sentence_transformers", _needs_embeddings, "memory_note", "sentence-transformers"),
    ("docker", _needs_docker, "sandbox_note", "subprocess sandbox"),
    ("opentelemetry", _needs_otel, "tracer.note", "otel"),
    ("bs4", _nothing, None, None),
    ("yaml", _nothing, None, None),
]


def _note(harness: Harness, path: str) -> str | None:
    """``harness.<path>``, walking one dot (``tracer.note``), never raising."""
    target: object = harness
    for part in path.split("."):
        target = getattr(target, part, None)
        if target is None:
            return None
    return str(target)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A tmp workspace whose memory db and trace dir cannot touch the real home."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize(
    ("dependency", "configure", "note_attr", "expected"),
    CASES,
    ids=[case[0] for case in CASES],
)
def test_a_turn_survives_a_missing_optional_dependency(
    dependency, configure, note_attr, expected, workspace, monkeypatch
):
    if dependency == "docker":
        # Nothing imports a `docker` module: `docker_available()` shells out to the CLI.
        monkeypatch.setattr("agent86.tools.sandbox.executor.shutil.which", lambda _name: None)
    _hide(monkeypatch, dependency)

    cfg = load_config()
    cfg.memory.path = str(workspace / "memory.db")
    cfg.memory.embeddings = "hash:32"
    configure(cfg)

    harness = Harness(cfg, provider=TextProvider("still here"), workspace=workspace)
    try:
        state = harness.new_session()
        streamed = "".join(d.text for d in harness.run_turn("are you there?", state) if d.text)
    finally:
        harness.close()

    assert "still here" in streamed
    if note_attr is not None:
        note = _note(harness, note_attr)
        assert note is not None, f"{dependency} degraded silently; no {note_attr}"
        assert expected in note, note


# --------------------------------------------------------------------------- #
# the individual fallbacks, where the note isn't the observable part
# --------------------------------------------------------------------------- #


def test_without_keyring_keys_resolve_from_the_environment_only(monkeypatch):
    from agent86.secrets import keyring_available, resolve_api_key

    _hide(monkeypatch, "keyring")
    monkeypatch.setenv("DEGRADE_TEST_KEY", "from-the-environment")

    assert keyring_available() is False
    assert resolve_api_key("anything", "DEGRADE_TEST_KEY") == "from-the-environment"
    # Nothing stored anywhere: None, not an exception.
    assert resolve_api_key("anything", "DEGRADE_TEST_KEY_UNSET") is None


def test_without_bs4_html_still_reduces_to_text(monkeypatch):
    from agent86.tools.builtin.web import _html_to_text

    _hide(monkeypatch, "bs4")

    text = _html_to_text(
        "<html><body><nav>skip me</nav><main><p>the actual content</p></main></body></html>"
    )

    assert "the actual content" in text


def test_without_yaml_skill_frontmatter_still_parses(tmp_path, monkeypatch):
    from agent86.skills.loader import discover_skills

    _hide(monkeypatch, "yaml")
    root = tmp_path / ".agent86" / "skills" / "greeter"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: greeter\ndescription: says hello\n---\n\nSay hello.\n", encoding="utf-8"
    )

    skills = discover_skills(load_config(), tmp_path)

    assert "greeter" in skills
    assert skills["greeter"].description == "says hello"
