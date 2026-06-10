from pathlib import Path

import pytest

from keystone_mcp.harness_scaffold import (
    BOOTSTRAP_DIRS,
    Scaffold,
    ScaffoldError,
    options_catalog,
    render_action,
    render_adapter_readme,
    render_agent_menu,
    render_guide,
    render_playbook,
    render_sensor,
)


# Render functions ---------------------------------------------------------


def test_render_guide_iron_law_section_present():
    out = render_guide("dangerous-actions", "iron-law")
    assert out.startswith("# Dangerous Actions\n")
    assert "## IRON LAW" in out
    assert "NEVER OR ALWAYS" in out


def test_render_guide_rules_default():
    out = render_guide("anything", "rules")
    assert "## RULES" in out
    assert "MUST <rule one>" in out


def test_render_guide_golden_tier():
    out = render_guide("aspirational", "golden")
    assert "## GOLDEN RULES" in out
    assert "Aim to" in out


def test_render_guide_invalid_tier_raises():
    with pytest.raises(ScaffoldError, match="guide tier"):
        render_guide("x", "bogus")


def test_render_sensor_writes_frontmatter():
    out = render_sensor("build", "computational")
    assert out.startswith("---\nkind: computational\n---")
    assert "# Sensor: build" in out


def test_render_sensor_invalid_kind_raises():
    with pytest.raises(ScaffoldError, match="sensor kind"):
        render_sensor("x", "bogus")


def test_render_action_minimal_shape():
    out = render_action("spec")
    assert "# spec" in out
    assert "## Activities" in out
    assert "## Output" in out


def test_render_playbook_inlines_action_steps():
    out = render_playbook("task", ["spec", "orient", "verify"])
    assert "spec → orient → verify" in out
    assert "**spec**" in out
    assert "[`orient.md`](../actions/orient.md)" in out


def test_render_playbook_empty_actions_falls_back_to_placeholders():
    out = render_playbook("task", [])
    assert "<list actions here>" in out
    assert "<first action>" in out


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
    s.new_guide("x", tier="golden", force=True)
    updated = (s.root / "guides" / "x.md").read_text()
    assert original != updated
    assert "## GOLDEN RULES" in updated


def test_new_guide_invalid_name_rejected(tmp_path):
    s = _scaffold(tmp_path)
    with pytest.raises(ScaffoldError, match="guide name"):
        s.new_guide("../etc/passwd")
    with pytest.raises(ScaffoldError, match="guide name"):
        s.new_guide("")


def test_new_sensor_writes_file(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    result = s.new_sensor("build", kind="build")
    path = Path(result["created"][0])
    assert path == s.root / "sensors" / "build.md"
    body = path.read_text()
    assert "kind: build" in body
    assert "Sensor: build" in body


def test_new_action_writes_file(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    result = s.new_action("spec")
    path = Path(result["created"][0])
    assert path == s.root / "actions" / "spec.md"


def test_new_playbook_with_actions(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    result = s.new_playbook("task", actions=["spec", "verify"])
    path = Path(result["created"][0])
    body = path.read_text()
    assert "spec → verify" in body
    assert "**spec**" in body


def test_new_playbook_validates_referenced_action_names(tmp_path):
    s = _scaffold(tmp_path)
    s.bootstrap()
    with pytest.raises(ScaffoldError, match="referenced action"):
        s.new_playbook("task", actions=["spec", "../bad"])


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
    status = s.status()
    assert status["root_exists"] is True
    assert status["subdirs"]["guides"]["files"] == 2
    assert status["subdirs"]["sensors"]["files"] == 1
    assert status["subdirs"]["actions"]["files"] == 0


def test_status_when_root_missing(tmp_path):
    s = Scaffold(tmp_path / "nope")
    status = s.status()
    assert status["root_exists"] is False
    assert status["subdirs"] == {}


def test_options_catalog_lists_choices():
    cat = options_catalog()
    assert "iron-law" in cat["guide_tiers"]
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
