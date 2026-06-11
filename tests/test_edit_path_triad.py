"""Phase 26 — edit-path triad.

The plan's invariant: the same logical operation produces byte-identical
output across three edit paths:

  1. **MCP tool** (`Scaffold.new_*`) — what an agent calls.
  2. **Shipped skill** (the agent walks a `SKILL.md` that ends up
     invoking the same scaffold). For test purposes we simulate this
     by calling the same `Scaffold.new_*` API the skill body would
     direct the agent to call; the byte-identity invariant is what
     matters.
  3. **Direct filesystem write** — a human opens the editor and writes
     `render_*(name).encode()` to the canonical path.

If any divergence creeps in (rendering changes in one path but not the
others, or a hidden side effect lands), these tests catch it before a
user sees template drift.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from keystone_mcp.harness_scaffold import (
    Scaffold,
    render_action,
    render_adapter_readme,
    render_corpus,
    render_guide,
    render_playbook,
    render_prompt,
    render_script,
    render_sensor,
    render_skill,
)


def _scaffold(tmp_path: Path) -> Scaffold:
    s = Scaffold(tmp_path / "harness")
    s.bootstrap(materialize_templates=False)
    return s


def _direct(
    s: Scaffold, port: str, name: str, body: str, *, suffix: str = ".md"
) -> Path:
    """Place a file directly on the filesystem the way a human editor would."""
    path = s.root / port / f"{name}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_guide_triad(tmp_path):
    name = "release-policy"
    body = render_guide(name, "rules")
    # 1. MCP tool path.
    s_tool = _scaffold(tmp_path / "tool")
    s_tool.new_guide(name, tier="rules")
    tool_body = (s_tool.root / "guides" / f"{name}.md").read_text()
    # 2. Skill path — simulated. The shipped skill that creates a
    # guide would invoke the same Scaffold.new_guide API.
    s_skill = _scaffold(tmp_path / "skill")
    s_skill.new_guide(name, tier="rules")
    skill_body = (s_skill.root / "guides" / f"{name}.md").read_text()
    # 3. Direct filesystem write.
    s_direct = _scaffold(tmp_path / "direct")
    direct_body = _direct(s_direct, "guides", name, body).read_text()
    assert tool_body == skill_body == direct_body == body


def test_sensor_triad(tmp_path):
    name = "build"
    sensor_body = render_sensor(name, "build", mode="computational")
    script_body = render_script(name)

    s_tool = _scaffold(tmp_path / "tool")
    s_tool.new_sensor(name, kind="build")
    tool_sensor = (s_tool.root / "sensors" / f"{name}.md").read_text()
    tool_script = (s_tool.root / "scripts" / f"{name}.sh").read_text()

    s_direct = _scaffold(tmp_path / "direct")
    direct_sensor = _direct(
        s_direct, "sensors", name, sensor_body
    ).read_text()
    direct_script = _direct(
        s_direct, "scripts", name, script_body, suffix=".sh"
    ).read_text()

    assert tool_sensor == direct_sensor == sensor_body
    assert tool_script == direct_script == script_body


def test_inferential_sensor_triad(tmp_path):
    name = "code-review"
    sensor_body = render_sensor(name, "custom", mode="inferential")
    prompt_body = render_prompt(name)

    s_tool = _scaffold(tmp_path / "tool")
    s_tool.new_sensor(name, kind="custom", mode="inferential")
    tool_sensor = (s_tool.root / "sensors" / f"{name}.md").read_text()
    tool_prompt = (s_tool.root / "prompts" / f"{name}.md").read_text()

    s_direct = _scaffold(tmp_path / "direct")
    direct_sensor = _direct(
        s_direct, "sensors", name, sensor_body
    ).read_text()
    direct_prompt = _direct(
        s_direct, "prompts", name, prompt_body
    ).read_text()

    assert tool_sensor == direct_sensor == sensor_body
    assert tool_prompt == direct_prompt == prompt_body


def test_skill_triad(tmp_path):
    name = "cut-release"
    description = "Cut a patch release"
    prefixed = f"keystone-{name}"
    body = render_skill(prefixed, description=description)

    s_tool = _scaffold(tmp_path / "tool")
    s_tool.new_skill(name, description=description)
    tool_body = (
        s_tool.root / "skills" / prefixed / "SKILL.md"
    ).read_text()

    s_direct = _scaffold(tmp_path / "direct")
    direct_path = s_direct.root / "skills" / prefixed / "SKILL.md"
    direct_path.parent.mkdir(parents=True, exist_ok=True)
    direct_path.write_text(body)
    direct_body = direct_path.read_text()

    assert tool_body == direct_body == body


def test_adapter_triad(tmp_path):
    agent = "claude-code"
    body = render_adapter_readme(agent)

    s_tool = _scaffold(tmp_path / "tool")
    s_tool.new_adapter(agent)
    tool_body = (
        s_tool.root / "adapters" / agent / "README.md"
    ).read_text()

    s_direct = _scaffold(tmp_path / "direct")
    direct_path = s_direct.root / "adapters" / agent / "README.md"
    direct_path.parent.mkdir(parents=True, exist_ok=True)
    direct_path.write_text(body)
    direct_body = direct_path.read_text()

    assert tool_body == direct_body == body


def test_action_triad(tmp_path):
    name = "orient"
    body = render_action(name)

    s_tool = _scaffold(tmp_path / "tool")
    s_tool.new_action(name)
    tool_body = (s_tool.root / "actions" / f"{name}.md").read_text()

    s_direct = _scaffold(tmp_path / "direct")
    direct_body = _direct(s_direct, "actions", name, body).read_text()

    assert tool_body == direct_body == body


def test_playbook_triad(tmp_path):
    name = "verify"
    body = render_playbook(name)

    s_tool = _scaffold(tmp_path / "tool")
    s_tool.new_playbook(name)
    tool_body = (s_tool.root / "playbooks" / f"{name}.md").read_text()

    s_direct = _scaffold(tmp_path / "direct")
    direct_body = _direct(s_direct, "playbooks", name, body).read_text()

    assert tool_body == direct_body == body


def test_corpus_triad(tmp_path):
    name = "architecture"
    body = render_corpus(name)

    s_tool = _scaffold(tmp_path / "tool")
    s_tool.new_corpus(name)
    tool_body = (s_tool.root / "corpus" / f"{name}.md").read_text()

    s_direct = _scaffold(tmp_path / "direct")
    direct_body = _direct(s_direct, "corpus", name, body).read_text()

    assert tool_body == direct_body == body


def test_script_triad(tmp_path):
    name = "deploy"
    body = render_script(name)

    s_tool = _scaffold(tmp_path / "tool")
    s_tool.new_script(name)
    tool_body = (s_tool.root / "scripts" / f"{name}.sh").read_text()

    s_direct = _scaffold(tmp_path / "direct")
    direct_body = _direct(
        s_direct, "scripts", name, body, suffix=".sh"
    ).read_text()

    assert tool_body == direct_body == body


def test_prompt_triad(tmp_path):
    name = "audit-prompt"
    body = render_prompt(name)

    s_tool = _scaffold(tmp_path / "tool")
    s_tool.new_prompt(name)
    tool_body = (s_tool.root / "prompts" / f"{name}.md").read_text()

    s_direct = _scaffold(tmp_path / "direct")
    direct_body = _direct(s_direct, "prompts", name, body).read_text()

    assert tool_body == direct_body == body
