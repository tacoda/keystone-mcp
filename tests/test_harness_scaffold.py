from pathlib import Path

import pytest

from keystone_mcp.harness_scaffold import (
    BOOTSTRAP_DIRS,
    Scaffold,
    ScaffoldError,
    extract_tier_sections,
    options_catalog,
    render_adapter_readme,
    render_agent_menu,
    render_guide,
    render_prompt,
    render_script,
    render_sensor,
    render_skill,
)


# Render functions ---------------------------------------------------------


def test_render_guide_non_negotiable_section_present():
    out = render_guide("dangerous-actions", "non-negotiable")
    assert out.startswith("# Dangerous Actions\n")
    assert "## NON-NEGOTIABLE" in out
    assert "never be violated" in out


def test_render_guide_rules_default():
    out = render_guide("anything", "rules")
    assert "## RULES" in out
    assert "<regular rule" in out


def test_render_guide_strong_tier():
    out = render_guide("preferred", "strong")
    assert "## STRONG" in out
    assert "deviation requires explicit reasoning" in out


def test_render_guide_invalid_tier_raises():
    with pytest.raises(ScaffoldError, match="guide tier"):
        render_guide("x", "bogus")


def test_render_guide_rejects_old_tier_names():
    # The rename dropped the legacy keystone names.
    with pytest.raises(ScaffoldError):
        render_guide("x", "iron-law")
    with pytest.raises(ScaffoldError):
        render_guide("x", "golden")


def test_render_sensor_writes_frontmatter():
    out = render_sensor("build", "computational")
    assert "kind: computational" in out
    # No script field — adapter infers from <root>/scripts/<name>.sh.
    assert "script:" not in out
    assert out.startswith("---\n")
    assert "# Sensor: build" in out
    assert "blocking" in out
    assert ".keystone/harness/scripts/build.sh" in out


def test_render_sensor_invalid_kind_raises():
    with pytest.raises(ScaffoldError, match="sensor kind"):
        render_sensor("x", "bogus")


def test_render_script_emits_executable_bash():
    out = render_script("build")
    assert out.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in out
    assert "Sensor script: build" in out
    assert "exit 1" in out


def test_render_sensor_inferential_mode_points_at_prompt():
    out = render_sensor("code-review", "custom", mode="inferential")
    assert "kind: custom" in out
    assert ".keystone/harness/prompts/code-review.md" in out
    assert "agent reads" in out.lower()
    assert "PASS" in out and "FAIL" in out
    # Should NOT mention scripts/ when inferential.
    assert "scripts/" not in out


def test_render_sensor_invalid_mode_raises():
    with pytest.raises(ScaffoldError, match="sensor mode"):
        render_sensor("x", "lint", mode="bogus")


def test_render_skill_writes_frontmatter():
    out = render_skill("cut-release")
    assert out.startswith("---\n")
    assert "description: <one-line description of the cut-release skill>" in out
    assert "## When to use" in out
    assert "## Activities" in out


def test_render_skill_honors_explicit_description():
    out = render_skill("cut-release", description="Cut a patch release")
    assert "description: Cut a patch release" in out


def test_render_adapter_readme_mentions_agent():
    out = render_adapter_readme("claude-code")
    assert "claude-code" in out
    assert "## Activation" in out


def test_render_agent_menu_substitutes_harness_root():
    out = render_agent_menu(".keystone/harness")
    assert "`.keystone/harness/" in out
    assert "get_context(topic)" in out
    assert "context://" in out


def test_render_agent_menu_warns_about_secrets():
    out = render_agent_menu(".keystone/harness")
    assert "Never put secrets" in out
    assert "env:VAR" in out


def test_render_agent_menu_documents_strictness_cascade():
    out = render_agent_menu(".keystone/harness")
    assert "Non-negotiable" in out
    assert "Strong" in out
    assert "preferred path" in out.lower() or "preferred-path" in out.lower()


def test_render_agent_menu_inlines_provided_sections():
    sections = {
        "non-negotiable": [
            ("guides/dangerous.md", "**NEVER push to main directly.**"),
        ],
        "strong": [
            ("guides/quality.md", "- Run sensors before commit."),
        ],
    }
    out = render_agent_menu(".keystone/harness", sections=sections)
    assert "## Non-negotiable rules" in out
    assert "NEVER push to main directly" in out
    assert "guides/dangerous.md" in out
    assert "## Strong rules" in out
    assert "Run sensors before commit" in out
    assert "guides/quality.md" in out


def test_render_agent_menu_empty_sections_omits_inlined_sections():
    out = render_agent_menu(".keystone/harness", sections=None)
    assert "## Non-negotiable rules" not in out
    assert "## Strong rules" not in out


# Scaffold (write side) ----------------------------------------------------


def _scaffold(tmp_path: Path) -> Scaffold:
    return Scaffold(tmp_path / "harness")


def test_bootstrap_creates_skeleton(tmp_path):
    s = _scaffold(tmp_path)
    result = s.bootstrap()
    created = set(result["created"])
    for sub in BOOTSTRAP_DIRS:
        assert str(s.root / sub) in created
        assert (s.root / sub).is_dir()
    assert result["skipped"] == []


def test_bootstrap_is_idempotent(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    result = s.bootstrap()
    assert result["created"] == []
    assert len(result["skipped"]) == len(BOOTSTRAP_DIRS)


def test_new_guide_writes_file(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    result = s.new_guide("rollback-policy", tier="rules")
    assert len(result["created"]) == 1
    path = Path(result["created"][0])
    assert path == s.root / "guides" / "rollback-policy.md"
    body = path.read_text()
    assert "# Rollback Policy" in body
    assert "## RULES" in body


def test_new_guide_refuses_overwrite_without_force(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    s.new_guide("x")
    second = s.new_guide("x")
    assert second["created"] == []
    assert len(second["skipped"]) == 1


def test_new_guide_overwrites_with_force(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    s.new_guide("x", tier="rules")
    original = (s.root / "guides" / "x.md").read_text()
    s.new_guide("x", tier="strong", force=True)
    updated = (s.root / "guides" / "x.md").read_text()
    assert original != updated
    assert "## STRONG" in updated


def test_new_guide_invalid_name_rejected(tmp_path):
    s = _scaffold(tmp_path)
    with pytest.raises(ScaffoldError, match="guide name"):
        s.new_guide("../etc/passwd")
    with pytest.raises(ScaffoldError, match="guide name"):
        s.new_guide("")


def test_new_sensor_writes_sensor_and_script(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    result = s.new_sensor("build", kind="build")
    paths = [Path(p) for p in result["created"]]
    assert s.root / "sensors" / "build.md" in paths
    assert s.root / "scripts" / "build.sh" in paths
    sensor_body = (s.root / "sensors" / "build.md").read_text()
    assert "kind: build" in sensor_body
    assert "script:" not in sensor_body  # convention-by-name, not declared
    assert "Sensor: build" in sensor_body
    assert ".keystone/harness/scripts/build.sh" in sensor_body
    # Script is chmod +x
    script_path = s.root / "scripts" / "build.sh"
    assert script_path.stat().st_mode & 0o111


def test_new_sensor_force_does_not_overwrite_script(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    s.new_sensor("build", kind="build")
    custom_body = "#!/usr/bin/env bash\nmake build\n"
    (s.root / "scripts" / "build.sh").write_text(custom_body)
    s.new_sensor("build", kind="build", force=True)
    assert (s.root / "scripts" / "build.sh").read_text() == custom_body


def test_new_script_writes_executable_with_default_body(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    result = s.new_script("deploy")
    path = Path(result["created"][0])
    assert path == s.root / "scripts" / "deploy.sh"
    assert path.stat().st_mode & 0o111
    assert path.read_text().startswith("#!/usr/bin/env bash")


def test_new_script_accepts_explicit_body(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    body = "#!/bin/sh\necho hi\n"
    s.new_script("hello", body=body)
    assert (s.root / "scripts" / "hello.sh").read_text() == body


def test_new_script_refuses_overwrite_without_force(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    s.new_script("x")
    second = s.new_script("x")
    assert second["created"] == []
    assert len(second["skipped"]) == 1


def test_new_script_overwrites_with_force(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    s.new_script("x", body="A")
    s.new_script("x", body="B", force=True)
    assert (s.root / "scripts" / "x.sh").read_text() == "B"


def test_new_sensor_inferential_stamps_prompt_not_script(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    result = s.new_sensor("code-review", kind="custom", mode="inferential")
    paths = [Path(p) for p in result["created"]]
    assert s.root / "sensors" / "code-review.md" in paths
    assert s.root / "prompts" / "code-review.md" in paths
    # NO matching script.
    assert not (s.root / "scripts" / "code-review.sh").exists()
    # Sensor body points at the prompt, not a script.
    sensor_body = (s.root / "sensors" / "code-review.md").read_text()
    assert ".keystone/harness/prompts/code-review.md" in sensor_body
    assert "scripts/" not in sensor_body


def test_new_sensor_invalid_mode_raises(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    with pytest.raises(ScaffoldError, match="sensor mode"):
        s.new_sensor("x", kind="custom", mode="bogus")


def test_new_prompt_writes_file(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    result = s.new_prompt("security-review")
    path = Path(result["created"][0])
    assert path == s.root / "prompts" / "security-review.md"
    body = path.read_text()
    assert "# security-review" in body
    assert "PASS" in body


def test_new_prompt_accepts_explicit_body(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    custom = "# custom\n\nDo the thing.\n"
    s.new_prompt("custom", body=custom)
    assert (s.root / "prompts" / "custom.md").read_text() == custom


def test_new_prompt_refuses_overwrite_without_force(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    s.new_prompt("x")
    second = s.new_prompt("x")
    assert second["created"] == []
    assert len(second["skipped"]) == 1


def test_render_prompt_includes_pass_fail_contract():
    out = render_prompt("security-review")
    assert "PASS" in out
    assert "FAIL" in out
    # "halts the workflow" can wrap across a newline in the rendered body.
    collapsed = " ".join(out.split())
    assert "halts the workflow" in collapsed


def test_new_skill_creates_subdir_with_SKILL_md(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    result = s.new_skill("cut-release", description="Cut a patch release")
    path = Path(result["created"][0])
    assert path == s.root / "skills" / "cut-release" / "SKILL.md"
    body = path.read_text()
    assert body.startswith("---\n")
    assert "description: Cut a patch release" in body
    assert "# cut-release" in body


def test_new_skill_refuses_overwrite_without_force(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    s.new_skill("cut-release")
    second = s.new_skill("cut-release")
    assert second["created"] == []
    assert len(second["skipped"]) == 1


def test_new_skill_invalid_name_rejected(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    with pytest.raises(ScaffoldError, match="skill name"):
        s.new_skill("../bad")


def test_new_adapter_creates_dir_and_readme(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    result = s.new_adapter("claude-code")
    path = Path(result["created"][0])
    assert path == s.root / "adapters" / "claude-code" / "README.md"
    body = path.read_text()
    assert "claude-code" in body


def test_target_add_writes_menu_file_at_project_root(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    project = tmp_path / "proj"
    project.mkdir()
    result = s.target_add("claude-code", project_root=project)
    path = Path(result["created"][0])
    assert path == project / "CLAUDE.md"
    body = path.read_text()
    assert "get_context(topic)" in body
    assert "harness/" in body
    assert "Never put secrets" in body


def test_target_add_inlines_non_negotiable_and_strong_rules(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    # Drop a guide with both tiers.
    (s.root / "guides" / "dangerous.md").write_text(
        """# Dangerous

## NON-NEGOTIABLE

**Never push directly to main.**

## STRONG

- Run sensors before commit.

## RULES

- Prefer dataclasses.
"""
    )
    project = tmp_path / "proj"
    project.mkdir()
    s.target_add("claude-code", project_root=project)
    body = (project / "CLAUDE.md").read_text()
    assert "Never push directly to main." in body
    assert "Run sensors before commit." in body
    # Regular rules are NOT inlined — they load on demand via MCP.
    assert "Prefer dataclasses." not in body


def test_target_add_refresh_picks_up_rule_edits(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    (s.root / "guides" / "x.md").write_text(
        "# x\n\n## NON-NEGOTIABLE\n\n**Original rule.**\n"
    )
    project = tmp_path / "proj"
    project.mkdir()
    s.target_add("claude-code", project_root=project)
    first = (project / "CLAUDE.md").read_text()
    assert "Original rule" in first

    # Edit the guide. target_add(force=True) should regenerate.
    (s.root / "guides" / "x.md").write_text(
        "# x\n\n## NON-NEGOTIABLE\n\n**Updated rule.**\n"
    )
    s.target_add("claude-code", project_root=project, force=True)
    second = (project / "CLAUDE.md").read_text()
    assert "Updated rule" in second
    assert "Original rule" not in second


def test_extract_tier_sections_returns_empty_when_no_guides(tmp_path):
    sections = extract_tier_sections(tmp_path)
    assert sections == {"non-negotiable": [], "strong": []}


def test_extract_tier_sections_walks_nested_guides(tmp_path):
    (tmp_path / "guides" / "process").mkdir(parents=True)
    (tmp_path / "guides" / "process" / "a.md").write_text(
        "# a\n\n## NON-NEGOTIABLE\n\nrule A.\n\n## STRONG\n\n- rule B.\n"
    )
    (tmp_path / "guides" / "b.md").write_text(
        "# b\n\n## STRONG\n\n- rule C.\n"
    )
    sections = extract_tier_sections(tmp_path)
    nn = sections["non-negotiable"]
    strong = sections["strong"]
    assert len(nn) == 1
    assert "rule A" in nn[0][1]
    assert nn[0][0] == "guides/process/a.md"
    assert len(strong) == 2
    sources = sorted(s for s, _ in strong)
    assert sources == ["guides/b.md", "guides/process/a.md"]


def test_extract_tier_sections_recognizes_legacy_headings(tmp_path):
    (tmp_path / "guides").mkdir()
    (tmp_path / "guides" / "legacy.md").write_text(
        "# legacy\n\n## IRON LAW\n\n**Legacy IRON LAW text.**\n\n"
        "## GOLDEN RULES\n\n- Legacy golden rule.\n"
    )
    sections = extract_tier_sections(tmp_path)
    assert any("IRON LAW text" in body for _, body in sections["non-negotiable"])
    assert any("Legacy golden rule" in body for _, body in sections["strong"])


def test_extract_tier_sections_skips_readme(tmp_path):
    (tmp_path / "guides").mkdir()
    (tmp_path / "guides" / "README.md").write_text(
        "## NON-NEGOTIABLE\n\nshould-not-show.\n"
    )
    (tmp_path / "guides" / "real.md").write_text(
        "## NON-NEGOTIABLE\n\nincluded.\n"
    )
    sections = extract_tier_sections(tmp_path)
    bodies = [b for _, b in sections["non-negotiable"]]
    assert "included." in bodies
    assert not any("should-not-show" in b for b in bodies)


def test_target_add_cursor_writes_nested_path(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    project = tmp_path / "proj"
    project.mkdir()
    result = s.target_add("cursor", project_root=project)
    path = Path(result["created"][0])
    assert path == project / ".cursor" / "rules" / "000-harness.mdc"
    assert path.exists()


def test_target_add_unknown_agent_raises(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    with pytest.raises(ScaffoldError, match="agent must be one of"):
        s.target_add("gpt-9000", project_root=tmp_path)


def test_target_add_refuses_overwrite(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    project = tmp_path / "proj"
    project.mkdir()
    (project / "CLAUDE.md").write_text("existing content")
    result = s.target_add("claude-code", project_root=project)
    assert result["created"] == []
    assert len(result["skipped"]) == 1
    assert (project / "CLAUDE.md").read_text() == "existing content"


def test_status_reports_subdir_counts(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    s.new_guide("a")
    s.new_guide("b")
    s.new_sensor("build", kind="build")
    s.new_skill("cut-release")
    status = s.status()
    assert status["root_exists"] is True
    assert status["subdirs"]["guides"]["files"] == 2
    assert status["subdirs"]["sensors"]["files"] == 1
    assert status["subdirs"]["skills"]["files"] == 1


def test_status_counts_skills_by_subdir_with_SKILL_md(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    # Bare directory without SKILL.md should not count.
    (s.root / "skills" / "empty-dir").mkdir()
    s.new_skill("real-skill")
    status = s.status()
    assert status["subdirs"]["skills"]["files"] == 1


def test_status_when_root_missing(tmp_path):
    s = Scaffold(tmp_path / "nope")
    status = s.status()
    assert status["root_exists"] is False
    assert status["subdirs"] == {}


def test_options_catalog_lists_choices():
    cat = options_catalog()
    assert set(cat["guide_tiers"]) == {"non-negotiable", "strong", "rules"}
    assert "build" in cat["sensor_kinds"]
    assert "claude-code" in cat["supported_agents"]
    assert "CLAUDE.md" in cat["agent_menu_files"]["claude-code"]


# Secret-name guard -------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "secret",
        "my-secret",
        "auth-token",
        "api_key",
        "api-key",
        "apikey",
        "credentials",
        "github-credential",
        "password",
        "db-passwd",
        "private",
        "envfile",
    ],
)
def test_scaffold_rejects_secret_like_names(tmp_path, name):
    s = _scaffold(tmp_path)
    s.bootstrap()
    with pytest.raises(ScaffoldError, match="looks like a secret"):
        s.new_guide(name)


@pytest.mark.parametrize("name", [".env", "production.env"])
def test_scaffold_rejects_dotenv_names_via_regex(tmp_path, name):
    # Names with dots fail the alphanumeric regex BEFORE the secret check.
    # Either rejection is safe — both prevent the file from being written.
    s = _scaffold(tmp_path)
    s.bootstrap()
    with pytest.raises(ScaffoldError):
        s.new_guide(name)


def test_scaffold_rejects_secret_like_sensor_name(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    with pytest.raises(ScaffoldError, match="looks like a secret"):
        s.new_sensor("token-leak-scanner", kind="custom")


def test_scaffold_rejects_secret_like_adapter_agent(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    with pytest.raises(ScaffoldError, match="looks like a secret"):
        s.new_adapter("secret-agent")


def test_scaffold_message_mentions_env_indirection(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    with pytest.raises(ScaffoldError, match="env:VAR"):
        s.new_guide("api_token")
