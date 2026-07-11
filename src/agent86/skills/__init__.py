"""Skills — self-contained folders with a markdown instruction file.

Discovered from configured skill paths. Uses progressive disclosure: only each
skill's name + description sit in context until the model invokes it, at which point
its full ``SKILL.md`` instructions (and any bundled resources) load. Keeps the token
budget lean. Populated in Phase 6.

Modules:
    loader.py  — discover skill folders, parse frontmatter, load on demand
    models.py  — Skill dataclass
"""
