"""Phase 6 / v0.9 — skill discovery, the Agent Skills convention, and allowed-tools.

Discovery follows the convention: `SKILL.md` with YAML frontmatter, found under the
project's `.agent86/skills` and `.claude/skills` first, then the user's, then the configured
paths — first root wins. `allowed-tools` is *enforced*, not merely advertised.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent86.cognitive.prompt import build_system_prompt
from agent86.config import load_config
from agent86.skills.loader import (
    default_skill_paths,
    discover_skills,
    parse_allowed_tools,
    parse_skill_md,
    skill_roots,
)
from agent86.tools.base import ToolContext
from agent86.tools.builtin.files import ReadFileTool
from agent86.tools.builtin.skills_tool import UseSkillTool
from agent86.tools.registry import default_registry
from agent86.tools.sandbox.policy import default_policy
from agent86.types import ToolCall


def _make_skill(root: Path, name: str, desc: str, body: str, tools=None, extra=None) -> Path:
    d = root / name
    d.mkdir(parents=True)
    fm = f"---\nname: {name}\ndescription: {desc}\n"
    if tools:
        fm += f"allowed-tools: {', '.join(tools)}\n"
    fm += "---\n" + body
    (d / "SKILL.md").write_text(fm, encoding="utf-8")
    if extra:
        (d / extra).write_text("resource", encoding="utf-8")
    return d


def _write_skill_md(root: Path, name: str, text: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    return d


def _cfg(tmp_path: Path):
    cfg = load_config()
    cfg.skills.paths = [str(tmp_path / "skills")]
    return cfg


@pytest.fixture(params=["pyyaml", "mini"])
def any_parser(request, monkeypatch):
    """Exercise the frontmatter tests against PyYAML *and* the no-dependency fallback.

    PyYAML is optional — plenty of installs will not have it — so the mini parser is not a
    curiosity, it is the parser half the world runs. `sys.modules["yaml"] = None` makes the
    loader's `import yaml` raise ImportError exactly as it does on a machine without it.
    """
    if request.param == "mini":
        monkeypatch.setitem(sys.modules, "yaml", None)
    else:
        pytest.importorskip("yaml")
    return request.param


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point ``Path.home()`` at a scratch dir so the developer's real skills stay out."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


# ---- frontmatter parsing ----------------------------------------------- #


def test_parse_frontmatter(any_parser):
    meta, body = parse_skill_md(
        "---\nname: x\ndescription: does x\nallowed-tools: a, b\n---\nHello body\n"
    )
    assert meta["name"] == "x"
    assert meta["description"] == "does x"
    assert body.strip() == "Hello body"


def test_parse_folded_block_scalar_description(any_parser):
    meta, body = parse_skill_md(
        "---\n"
        "name: pirate\n"
        "description: >\n"
        "  Rewrite text in pirate dialect.\n"
        "  Use when the user asks for a nautical voice.\n"
        "---\n"
        "Arr.\n"
    )
    assert meta["name"] == "pirate"
    assert meta["description"] == (
        "Rewrite text in pirate dialect. Use when the user asks for a nautical voice."
    )
    assert body.strip() == "Arr."


def test_parse_literal_block_scalar_keeps_line_breaks(any_parser):
    meta, _ = parse_skill_md("---\nname: x\ndescription: |\n  line one\n  line two\n---\nbody\n")
    assert meta["description"] == "line one\nline two"


def test_parse_quoted_values_are_unquoted(any_parser):
    meta, _ = parse_skill_md(
        "---\nname: \"quoted-name\"\ndescription: 'has: a colon'\nlicense: MIT\n---\nbody\n"
    )
    assert meta["name"] == "quoted-name"
    assert meta["description"] == "has: a colon"
    assert meta["license"] == "MIT"


def test_body_containing_a_horizontal_rule_is_not_truncated(any_parser):
    """The closing delimiter is a `---` on its own LINE, not the next three hyphens."""
    _, body = parse_skill_md("---\nname: x\ndescription: d\n---\nintro\n\n---\n\noutro\n")
    assert "intro" in body and "outro" in body


def test_frontmatter_without_a_closing_delimiter_is_all_body(any_parser):
    meta, body = parse_skill_md("---\nname: x\nno closing marker\n")
    assert meta == {}
    assert "no closing marker" in body


def test_parse_allowed_tools_accepts_spaces_commas_and_lists():
    assert parse_allowed_tools("read_file write_file") == ["read_file", "write_file"]
    assert parse_allowed_tools("read_file, write_file") == ["read_file", "write_file"]
    assert parse_allowed_tools("[read_file, write_file]") == ["read_file", "write_file"]
    assert parse_allowed_tools(["read_file", "write_file"]) == ["read_file", "write_file"]
    assert parse_allowed_tools(None) == []


def test_block_list_allowed_tools(tmp_path, isolated_home, any_parser):
    root = tmp_path / "skills"
    _write_skill_md(
        root,
        "blocky",
        "---\nname: blocky\ndescription: d\nallowed-tools:\n  - read_file\n  - list_dir\n"
        "---\nbody\n",
    )
    skills = discover_skills(_cfg(tmp_path))
    assert skills["blocky"].allowed_tools == ["read_file", "list_dir"]


def test_license_and_metadata_are_carried(tmp_path, isolated_home, any_parser):
    root = tmp_path / "skills"
    _write_skill_md(
        root,
        "meta",
        "---\nname: meta\ndescription: d\nlicense: Apache-2.0\nmetadata:\n  version: 1.2.0\n"
        "---\nbody\n",
    )
    skill = discover_skills(_cfg(tmp_path))["meta"]
    assert skill.license == "Apache-2.0"
    # `metadata:` is carried when a real YAML parser is present; never interpreted.
    assert isinstance(skill.metadata, dict)


# ---- discovery & precedence -------------------------------------------- #


def test_discover_finds_skills(tmp_path, isolated_home):
    root = tmp_path / "skills"
    _make_skill(root, "pirate", "Speak like a pirate.", "Arr, rewrite as a pirate.")
    _make_skill(root, "haiku", "Write a haiku.", "5-7-5 syllables.")
    skills = discover_skills(_cfg(tmp_path))
    assert "pirate" in skills and "haiku" in skills
    assert skills["pirate"].description == "Speak like a pirate."


def test_claude_skills_directories_are_discovered(tmp_path, isolated_home):
    workspace = tmp_path / "ws"
    _make_skill(workspace / ".claude" / "skills", "project-claude", "From .claude.", "body")
    _make_skill(isolated_home / ".claude" / "skills", "user-claude", "From ~/.claude.", "body")

    skills = discover_skills(load_config(), workspace)

    assert "project-claude" in skills and "user-claude" in skills


def test_project_skills_override_user_skills(tmp_path, isolated_home):
    """Search order is project → user → config paths; the FIRST root wins."""
    workspace = tmp_path / "ws"
    _make_skill(workspace / ".agent86" / "skills", "shared", "project version", "project body")
    _make_skill(isolated_home / ".agent86" / "skills", "shared", "user version", "user body")

    skills = discover_skills(load_config(), workspace)

    assert skills["shared"].description == "project version"


def test_agent86_project_dir_wins_over_claude_project_dir(tmp_path, isolated_home):
    workspace = tmp_path / "ws"
    _make_skill(workspace / ".agent86" / "skills", "shared", "agent86 version", "body")
    _make_skill(workspace / ".claude" / "skills", "shared", "claude version", "body")

    skills = discover_skills(load_config(), workspace)

    assert skills["shared"].description == "agent86 version"


def test_config_paths_never_override_the_project(tmp_path, isolated_home):
    workspace = tmp_path / "ws"
    _make_skill(workspace / ".agent86" / "skills", "shared", "project version", "body")
    _make_skill(tmp_path / "skills", "shared", "config version", "body")

    skills = discover_skills(_cfg(tmp_path), workspace)

    assert skills["shared"].description == "project version"


def test_project_roots_resolve_against_the_workspace_not_the_cwd(tmp_path, isolated_home):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    paths = default_skill_paths(load_config(), workspace)
    assert paths[0] == workspace / ".agent86" / "skills"
    assert paths[1] == workspace / ".claude" / "skills"
    # ...and with no workspace the caller gets the CWD fallback, documented in the loader.
    assert default_skill_paths(load_config())[0] == Path.cwd() / ".agent86" / "skills"


def test_skills_disabled_discovers_nothing(tmp_path, isolated_home):
    _make_skill(tmp_path / "skills", "pirate", "d", "body")
    cfg = _cfg(tmp_path)
    cfg.skills.enabled = False
    assert discover_skills(cfg) == {}
    assert skill_roots(cfg) == []


# ---- bundled resources & the sandbox ----------------------------------- #


def test_skill_resources_are_readable_through_the_jail(tmp_path, isolated_home):
    """A user-level skill's bundled file lives outside the workspace — and must still open."""
    skill_dir = _make_skill(
        isolated_home / ".claude" / "skills", "ref", "Has a reference.", "body",
        extra="reference.md",
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = load_config()
    policy = default_policy(cfg, workspace)

    assert skill_dir.parent.resolve() in policy.allow_paths

    ctx = ToolContext(workspace=policy.workspace, policy=policy, config=cfg)
    res = ReadFileTool().run(
        ToolCall(id="1", name="read_file", arguments={"path": str(skill_dir / "reference.md")}),
        ctx,
    )
    assert res.ok and "resource" in res.content


def test_the_jail_still_holds_outside_skill_roots(tmp_path, isolated_home):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    cfg = load_config()
    ctx = ToolContext(
        workspace=workspace, policy=default_policy(cfg, workspace), config=cfg
    )
    res = ReadFileTool().run(
        ToolCall(id="1", name="read_file", arguments={"path": str(tmp_path / "secret.txt")}), ctx
    )
    assert not res.ok and "jail" in (res.error or "").lower()


# ---- use_skill & enforcement ------------------------------------------- #


def test_use_skill_loads_instructions(tmp_path, isolated_home):
    root = tmp_path / "skills"
    _make_skill(root, "pirate", "Speak like a pirate.", "Arr! Rewrite the text as a pirate.",
                tools=["read_file"], extra="glossary.txt")
    cfg = _cfg(tmp_path)
    skills = discover_skills(cfg)
    ctx = ToolContext(
        workspace=tmp_path, policy=default_policy(cfg, tmp_path), config=cfg, skills=skills
    )
    res = UseSkillTool().run(ToolCall(id="1", name="use_skill", arguments={"name": "pirate"}), ctx)
    assert res.ok
    assert "Rewrite the text as a pirate" in res.content
    assert "glossary.txt" in res.content  # bundled resource surfaced
    assert skills["pirate"].allowed_tools == ["read_file"]


def test_use_skill_unknown(tmp_path, isolated_home):
    cfg = _cfg(tmp_path)
    ctx = ToolContext(
        workspace=tmp_path, policy=default_policy(cfg, tmp_path), config=cfg, skills={}
    )
    res = UseSkillTool().run(ToolCall(id="1", name="use_skill", arguments={"name": "nope"}), ctx)
    assert not res.ok and "No skill named" in (res.error or "")


def _skill_ctx(tmp_path, isolated_home, **skills_spec):
    root = tmp_path / "skills"
    for name, tools in skills_spec.items():
        _make_skill(root, name, f"{name} skill", "body", tools=tools)
    cfg = _cfg(tmp_path)
    skills = discover_skills(cfg)
    ctx = ToolContext(
        workspace=tmp_path, policy=default_policy(cfg, tmp_path), config=cfg, skills=skills
    )
    return cfg, skills, ctx


def test_allowed_tools_are_enforced_and_lift_at_the_end_of_the_turn(tmp_path, isolated_home):
    cfg, skills, ctx = _skill_ctx(tmp_path, isolated_home, reader=["read_file"])
    registry = default_registry(cfg, skills=skills)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    write = ToolCall(id="2", name="write_file", arguments={"path": "b.txt", "content": "x"})

    # Before activation: unrestricted.
    assert registry.dispatch(write, ctx).ok

    registry.dispatch(ToolCall(id="1", name="use_skill", arguments={"name": "reader"}), ctx)
    assert ctx.active_skill is not None and ctx.active_skill.name == "reader"

    refused = registry.dispatch(write, ctx)
    assert not refused.ok
    assert "reader" in (refused.error or "") and "read_file" in (refused.error or "")
    # The allowed tool still runs...
    read = ToolCall(id="3", name="read_file", arguments={"path": "a.txt"})
    assert registry.dispatch(read, ctx).ok

    ctx.clear_skill()  # end of turn
    assert registry.dispatch(write, ctx).ok


def test_activating_a_different_skill_replaces_the_restriction(tmp_path, isolated_home):
    cfg, skills, ctx = _skill_ctx(
        tmp_path, isolated_home, reader=["read_file"], lister=["list_dir"]
    )
    registry = default_registry(cfg, skills=skills)

    registry.dispatch(ToolCall(id="1", name="use_skill", arguments={"name": "reader"}), ctx)
    assert not registry.dispatch(
        ToolCall(id="2", name="list_dir", arguments={"path": "."}), ctx
    ).ok

    # use_skill itself is never refused — it is how the model changes skills.
    switched = registry.dispatch(ToolCall(id="3", name="use_skill", arguments={"name": "lister"}),
                                 ctx)
    assert switched.ok and ctx.active_skill.name == "lister"
    assert registry.dispatch(ToolCall(id="4", name="list_dir", arguments={"path": "."}), ctx).ok


def test_a_skill_without_allowed_tools_restricts_nothing(tmp_path, isolated_home):
    cfg, skills, ctx = _skill_ctx(tmp_path, isolated_home, freeform=None)
    registry = default_registry(cfg, skills=skills)
    registry.dispatch(ToolCall(id="1", name="use_skill", arguments={"name": "freeform"}), ctx)
    assert registry.dispatch(
        ToolCall(id="2", name="write_file", arguments={"path": "b.txt", "content": "x"}), ctx
    ).ok


def test_registry_adds_use_skill_only_with_skills(tmp_path, isolated_home):
    root = tmp_path / "skills"
    _make_skill(root, "pirate", "pirate", "arr")
    cfg = _cfg(tmp_path)
    skills = discover_skills(cfg)
    assert "use_skill" in default_registry(cfg, skills=skills).names()
    assert "use_skill" not in default_registry(cfg).names()


# ---- the system prompt -------------------------------------------------- #


def test_system_prompt_advertises_skills(tmp_path, isolated_home):
    root = tmp_path / "skills"
    _make_skill(root, "pirate", "Speak like a pirate.", "arr")
    skills = discover_skills(_cfg(tmp_path))
    prompt = build_system_prompt(load_config(), skills)
    assert "Available skills" in prompt.content
    assert "pirate: Speak like a pirate." in prompt.content
    assert "use_skill" in prompt.content


def test_system_prompt_lists_allowed_tools(tmp_path, isolated_home):
    root = tmp_path / "skills"
    _make_skill(root, "reader", "Reads things.", "body", tools=["read_file", "list_dir"])
    skills = discover_skills(_cfg(tmp_path))
    prompt = build_system_prompt(load_config(), skills)
    assert "[tools while active: read_file, list_dir]" in prompt.content


def test_system_prompt_flattens_a_multiline_description(tmp_path, isolated_home):
    root = tmp_path / "skills"
    _write_skill_md(
        root, "folded",
        "---\nname: folded\ndescription: |\n  line one\n  line two\n---\nbody\n",
    )
    skills = discover_skills(_cfg(tmp_path))
    prompt = build_system_prompt(load_config(), skills)
    assert "- folded: line one line two" in prompt.content


# ---- turn scoping (the harness) ----------------------------------------- #


def _turn_script(*completions):
    from tests.support import ScriptedProvider

    return ScriptedProvider(list(completions))


def _tool_step(call_id: str, name: str, arguments: dict):
    from agent86.types import Completion, Usage

    return Completion(
        text="",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        usage=Usage(input_tokens=5, output_tokens=2),
        stop_reason="tool_use",
    )


def _text_only():
    """A provider that just answers — for tests about construction, not about turns."""
    from tests.support import make_text_provider

    return make_text_provider("ok")


def _text_step(text: str):
    from agent86.types import Completion, Usage

    return Completion(text=text, usage=Usage(input_tokens=3, output_tokens=1))


def test_allowed_tools_restriction_is_turn_scoped(tmp_path, isolated_home):
    """A skill activated in turn 1 must not still be refusing tools in turn 2.

    `use_skill` sets `ToolContext.active_skill`, and the context outlives the turn — so
    without the harness clearing it, one `use_skill` call silently narrowed the toolset for
    the rest of the session, with nothing in the conversation to explain the refusals.
    """
    from agent86.orchestration.loop import Harness

    _make_skill(tmp_path / "skills", "reader", "Reads things.", "read stuff",
                tools=["read_file"])
    cfg = _cfg(tmp_path)
    provider = _turn_script(
        _tool_step("c1", "use_skill", {"name": "reader"}),   # turn 1, step 1
        _tool_step("c2", "list_dir", {"path": "."}),         # turn 1, step 2 — refused
        _text_step("turn one done"),                         # turn 1, step 3
        _tool_step("c3", "list_dir", {"path": "."}),         # turn 2, step 1 — permitted
        _text_step("turn two done"),                         # turn 2, step 2
    )
    harness = Harness(cfg, provider=provider, memory=None, workspace=tmp_path)
    assert "reader" in harness.skills

    state = harness.new_session()
    list(harness.run_turn("use the reader skill", state))
    # In force for the rest of that turn...
    refused = state.steps[1].results[0]
    assert not refused.ok and "not permitted while the skill 'reader'" in refused.error
    # ...and lifted the moment the turn ended.
    assert harness.context.active_skill is None

    list(harness.run_turn("now list the directory", state))
    assert state.steps[-2].results[0].ok


def test_abandoning_a_turn_mid_stream_still_lifts_the_restriction(tmp_path, isolated_home):
    """The clear is in a `finally`, so closing the generator early runs it too."""
    from agent86.orchestration.loop import Harness

    _make_skill(tmp_path / "skills", "reader", "Reads things.", "read stuff",
                tools=["read_file"])
    cfg = _cfg(tmp_path)
    provider = _turn_script(
        _tool_step("c1", "use_skill", {"name": "reader"}),
        _text_step("done"),
    )
    harness = Harness(cfg, provider=provider, memory=None, workspace=tmp_path)
    turn = harness.run_turn("use the reader skill", state=harness.new_session())
    next(turn)                       # start it, then walk away mid-turn
    turn.close()
    assert harness.context.active_skill is None


def test_the_harness_discovers_skills_from_the_workspace_not_the_cwd(tmp_path, isolated_home):
    """Project skill roots hang off the RESOLVED workspace (`--workspace`), not `Path.cwd()`."""
    from agent86.orchestration.loop import Harness

    workspace = tmp_path / "project"
    _make_skill(workspace / ".agent86" / "skills", "local", "A project skill.", "body")
    harness = Harness(
        load_config(), provider=_text_only(), memory=None, workspace=workspace
    )
    assert "local" in harness.skills


def test_the_gate_gets_the_tool_context_for_previews(tmp_path, isolated_home):
    """`ApprovalGate.preview` resolves paths through the sandbox policy — it needs a context."""
    from agent86.orchestration.loop import Harness

    harness = Harness(
        load_config(), provider=_text_only(), memory=None, workspace=tmp_path
    )
    assert harness.gate.context is harness.context
