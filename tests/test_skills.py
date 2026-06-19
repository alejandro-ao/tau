from pathlib import Path

import pytest

from tau_coding import (
    Skill,
    TauResourcePaths,
    build_skill_index,
    expand_skill_command,
    format_skill_invocation,
    load_skills,
    load_skills_with_diagnostics,
    parse_skill_invocation,
)
from tau_coding.resources import ResourceError


def test_load_skills_missing_directory_returns_empty(tmp_path: Path) -> None:
    assert load_skills(TauResourcePaths(root=tmp_path, agents_root=None)) == []


def test_load_skills_from_directory_and_file(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    (skills_dir / "python-testing").mkdir(parents=True)
    (skills_dir / "python-testing" / "SKILL.md").write_text(
        "---\ndescription: Test Python code\n---\n# Python Testing\nUse pytest.",
        encoding="utf-8",
    )
    (skills_dir / "git-review.md").write_text("# Git Review\nReview diffs.", encoding="utf-8")

    skills = load_skills(TauResourcePaths(root=tmp_path, agents_root=None))

    assert [skill.name for skill in skills] == ["git-review", "python-testing"]
    assert skills[0].description == "Git Review"
    assert skills[1].description == "Test Python code"


def test_load_skills_includes_user_and_project_agents_directories(tmp_path: Path) -> None:
    tau_home = tmp_path / "home" / ".tau"
    agents_home = tmp_path / "home" / ".agents"
    cwd = tmp_path / "project"
    (agents_home / "skills").mkdir(parents=True)
    (agents_home / "skills" / "user-skill.md").write_text(
        "# User Skill\nFrom user agents.", encoding="utf-8"
    )
    (cwd / ".agents" / "skills").mkdir(parents=True)
    (cwd / ".agents" / "skills" / "project-skill.md").write_text(
        "# Project Skill\nFrom project agents.", encoding="utf-8"
    )

    skills = load_skills(TauResourcePaths(root=tau_home, agents_root=agents_home, cwd=cwd))

    assert [skill.name for skill in skills] == ["project-skill", "user-skill"]


def test_project_agents_skill_overrides_user_agents_skill(tmp_path: Path) -> None:
    tau_home = tmp_path / "home" / ".tau"
    agents_home = tmp_path / "home" / ".agents"
    cwd = tmp_path / "project"
    (agents_home / "skills").mkdir(parents=True)
    (agents_home / "skills" / "review.md").write_text("# User Review", encoding="utf-8")
    (cwd / ".agents" / "skills").mkdir(parents=True)
    (cwd / ".agents" / "skills" / "review.md").write_text("# Project Review", encoding="utf-8")

    skills = load_skills(TauResourcePaths(root=tau_home, agents_root=agents_home, cwd=cwd))

    assert len(skills) == 1
    assert skills[0].path == cwd / ".agents" / "skills" / "review.md"
    assert skills[0].description == "Project Review"


def test_load_skills_with_diagnostics_reports_overrides(tmp_path: Path) -> None:
    tau_home = tmp_path / "home" / ".tau"
    agents_home = tmp_path / "home" / ".agents"
    cwd = tmp_path / "project"
    (tau_home / "skills").mkdir(parents=True)
    (tau_home / "skills" / "review.md").write_text("# User Tau Review", encoding="utf-8")
    (cwd / ".tau" / "skills").mkdir(parents=True)
    (cwd / ".tau" / "skills" / "review.md").write_text("# Project Tau Review", encoding="utf-8")

    skills, diagnostics = load_skills_with_diagnostics(
        TauResourcePaths(root=tau_home, agents_root=agents_home, cwd=cwd)
    )

    assert [skill.name for skill in skills] == ["review"]
    assert skills[0].path == cwd / ".tau" / "skills" / "review.md"
    assert len(diagnostics) == 1
    assert diagnostics[0].kind == "skill"
    assert diagnostics[0].name == "review"
    assert "overrides lower-precedence resource" in diagnostics[0].message


def test_load_skills_with_diagnostics_ignores_duplicate_within_directory(
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"
    (skills_dir / "dup").mkdir(parents=True)
    (skills_dir / "dup" / "SKILL.md").write_text("# Directory skill", encoding="utf-8")
    (skills_dir / "dup.md").write_text("# File skill", encoding="utf-8")

    skills, diagnostics = load_skills_with_diagnostics(
        TauResourcePaths(root=tmp_path, agents_root=None)
    )

    assert [skill.name for skill in skills] == ["dup"]
    assert skills[0].path == skills_dir / "dup" / "SKILL.md"
    assert len(diagnostics) == 1
    assert "Duplicate skill name" in diagnostics[0].message


def test_agents_md_is_not_loaded_as_a_skill(tmp_path: Path) -> None:
    agents_home = tmp_path / ".agents"
    agents_home.mkdir()
    (agents_home / "AGENTS.md").write_text("# Instructions", encoding="utf-8")
    (agents_home / "review.md").write_text("# Review", encoding="utf-8")

    skills = load_skills(TauResourcePaths(root=tmp_path / ".tau", agents_root=agents_home))

    assert [skill.name for skill in skills] == ["review"]


def test_load_skills_rejects_duplicate_names(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    (skills_dir / "dup").mkdir(parents=True)
    (skills_dir / "dup" / "SKILL.md").write_text("# Directory skill", encoding="utf-8")
    (skills_dir / "dup.md").write_text("# File skill", encoding="utf-8")

    with pytest.raises(ResourceError, match="Duplicate skill name"):
        load_skills(TauResourcePaths(root=tmp_path, agents_root=None))


def test_expand_skill_command_includes_skill_and_user_request(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "testing.md").write_text("# Testing\nRun pytest.", encoding="utf-8")
    skills = load_skills(TauResourcePaths(root=tmp_path, agents_root=None))

    expanded = expand_skill_command("/skill:testing add parser tests", skills)

    assert expanded is not None
    assert f'<skill name="testing" location="{skills[0].path}">' in expanded
    assert f"References are relative to {skills[0].path.parent}." in expanded
    assert "Run pytest." in expanded
    assert expanded.endswith("</skill>\n\nadd parser tests")


def test_format_skill_invocation_without_extra_instructions(tmp_path: Path) -> None:
    skill = Skill(
        name="testing",
        path=tmp_path / "skills" / "testing" / "SKILL.md",
        content="# Testing\nRun pytest.",
        description="Test code",
    )

    formatted = format_skill_invocation(skill)

    assert formatted == (
        f'<skill name="testing" location="{skill.path}">\n'
        f"References are relative to {skill.path.parent}.\n\n"
        "# Testing\n"
        "Run pytest.\n"
        "</skill>"
    )


def test_parse_skill_invocation_extracts_display_metadata(tmp_path: Path) -> None:
    skill = Skill(
        name="testing",
        path=tmp_path / "skills" / "testing" / "SKILL.md",
        content="# Testing\nRun pytest.",
        description="Test Python code",
    )
    formatted = format_skill_invocation(skill, "add parser tests")

    parsed = parse_skill_invocation(formatted)

    assert parsed is not None
    assert parsed.name == "testing"
    assert parsed.location == str(skill.path)
    assert "# Testing" in parsed.content
    assert parsed.additional_instructions == "add parser tests"


def test_expand_skill_command_returns_none_for_normal_prompt(tmp_path: Path) -> None:
    assert (
        expand_skill_command(
            "hello", load_skills(TauResourcePaths(root=tmp_path, agents_root=None))
        )
        is None
    )


def test_expand_skill_command_rejects_unknown_skill() -> None:
    with pytest.raises(ResourceError, match="Unknown skill"):
        expand_skill_command("/skill:missing", [])


def test_build_skill_index(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "testing.md").write_text(
        "---\ndescription: Test things\n---\nBody",
        encoding="utf-8",
    )

    assert build_skill_index(load_skills(TauResourcePaths(root=tmp_path, agents_root=None))) == (
        "Available skills:\n- testing: Test things"
    )
