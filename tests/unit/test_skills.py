"""Phase 6 — skill discovery, progressive disclosure, and the use_skill tool."""

from __future__ import annotations

from pathlib import Path

from agent86.cognitive.prompt import build_system_prompt
from agent86.config import load_config
from agent86.skills.loader import discover_skills, parse_skill_md
from agent86.tools.base import ToolContext
from agent86.tools.builtin.skills_tool import UseSkillTool
from agent86.tools.registry import default_registry
from agent86.tools.sandbox.policy import default_policy
from agent86.types import ToolCall


def _make_skill(root: Path, name: str, desc: str, body: str, tools=None, extra=None) -> None:
    d = root / name
    d.mkdir(parents=True)
    fm = f"---\nname: {name}\ndescription: {desc}\n"
    if tools:
        fm += f"allowed-tools: {', '.join(tools)}\n"
    fm += "---\n" + body
    (d / "SKILL.md").write_text(fm, encoding="utf-8")
    if extra:
        (d / extra).write_text("resource", encoding="utf-8")


def _cfg(tmp_path: Path):
    cfg = load_config()
    cfg.skills.paths = [str(tmp_path / "skills")]
    return cfg


def test_parse_frontmatter():
    meta, body = parse_skill_md(
        "---\nname: x\ndescription: does x\nallowed-tools: a, b\n---\nHello body\n"
    )
    assert meta["name"] == "x"
    assert meta["description"] == "does x"
    assert body.strip() == "Hello body"


def test_discover_finds_skills(tmp_path):
    root = tmp_path / "skills"
    _make_skill(root, "pirate", "Speak like a pirate.", "Arr, rewrite as a pirate.")
    _make_skill(root, "haiku", "Write a haiku.", "5-7-5 syllables.")
    skills = discover_skills(_cfg(tmp_path))
    assert "pirate" in skills and "haiku" in skills
    assert skills["pirate"].description == "Speak like a pirate."


def test_use_skill_loads_instructions(tmp_path):
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


def test_use_skill_unknown(tmp_path):
    cfg = _cfg(tmp_path)
    ctx = ToolContext(
        workspace=tmp_path, policy=default_policy(cfg, tmp_path), config=cfg, skills={}
    )
    res = UseSkillTool().run(ToolCall(id="1", name="use_skill", arguments={"name": "nope"}), ctx)
    assert not res.ok and "No skill named" in (res.error or "")


def test_registry_adds_use_skill_only_with_skills(tmp_path):
    root = tmp_path / "skills"
    _make_skill(root, "pirate", "pirate", "arr")
    cfg = _cfg(tmp_path)
    skills = discover_skills(cfg)
    assert "use_skill" in default_registry(cfg, skills=skills).names()
    assert "use_skill" not in default_registry(cfg).names()


def test_system_prompt_advertises_skills(tmp_path):
    root = tmp_path / "skills"
    _make_skill(root, "pirate", "Speak like a pirate.", "arr")
    skills = discover_skills(_cfg(tmp_path))
    prompt = build_system_prompt(load_config(), skills)
    assert "Available skills" in prompt.content
    assert "pirate: Speak like a pirate." in prompt.content
    assert "use_skill" in prompt.content
