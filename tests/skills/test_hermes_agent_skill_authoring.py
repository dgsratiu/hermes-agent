"""Regression coverage for the in-repo skill-authoring workflow."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from tools.skill_manager_tool import _validate_frontmatter


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_MD = (
    REPO_ROOT
    / "skills"
    / "software-development"
    / "hermes-agent-skill-authoring"
    / "SKILL.md"
)


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _frontmatter() -> dict:
    src = _skill_text()
    match = re.search(r"^---\n(.*?)\n---", src, re.DOTALL)
    assert match, "SKILL.md missing YAML frontmatter"
    return yaml.safe_load(match.group(1))


def test_skill_authoring_frontmatter_is_valid() -> None:
    content = _skill_text()
    frontmatter = _frontmatter()

    assert _validate_frontmatter(content) is None
    assert frontmatter["name"] == "hermes-agent-skill-authoring"
    assert len(frontmatter["description"]) <= 60
    assert frontmatter["description"].endswith(".")


def test_skill_authoring_documents_save_time_skill_parity() -> None:
    content = _skill_text()

    required_phrases = [
        "## Session-Save Skill Parity",
        "treat repo skills as durable repo surfaces, just like docs",
        "`skills/`, `optional-skills/`, and plugin `SKILL.md` files",
        "`website/scripts/generate-skill-docs.py`",
        "`website/docs/user-guide/skills/`",
        "`website/docs/reference/skills-catalog.md`",
        "`website/docs/reference/optional-skills-catalog.md`",
        "`website/sidebars.ts`",
        "Do not edit `~/.hermes/skills/`",
    ]
    for phrase in required_phrases:
        assert phrase in content
