"""Phase 16 — namespace invariants.

Every MCP primitive exposed by the Keystone Harness Manager must carry
the `keystone` namespace:

  - Tools and prompts → `keystone_*` prefix.
  - Resources and resource templates → `keystone://` scheme (or the
    FastMCP-native `skill://` scheme, which is reserved for project-local
    skills, not authored by the server itself).
  - Manager-authored skills → `keystone-<slug>` (enforced by
    `Scaffold.new_skill`).
"""

import asyncio
from pathlib import Path

import pytest

from keystone_mcp.harness_scaffold import Scaffold
from keystone_mcp.server import build_server


def _gather() -> dict[str, list[str]]:
    mcp = build_server()

    async def collect() -> dict[str, list[str]]:
        tools = await mcp.list_tools()
        prompts = await mcp.list_prompts()
        resources = await mcp.list_resources()
        templates = await mcp.list_resource_templates()
        return {
            "tools": [t.name for t in tools],
            "prompts": [p.name for p in prompts],
            "resources": [str(r.uri) for r in resources],
            "templates": [str(t.uri_template) for t in templates],
        }

    return asyncio.run(collect())


def test_every_tool_carries_keystone_prefix():
    surface = _gather()
    assert surface["tools"], "expected at least one tool registered"
    for name in surface["tools"]:
        assert name.startswith("keystone_"), name


def test_every_prompt_carries_keystone_prefix():
    surface = _gather()
    assert surface["prompts"], "expected at least one prompt registered"
    for name in surface["prompts"]:
        assert name.startswith("keystone_"), name


def test_every_resource_uri_rooted_at_keystone_scheme():
    surface = _gather()
    assert surface["resources"], "expected at least one resource registered"
    for uri in surface["resources"]:
        assert uri.startswith("keystone://"), uri


def test_every_resource_template_rooted_at_keystone_scheme():
    surface = _gather()
    assert surface["templates"], "expected at least one resource template registered"
    for uri in surface["templates"]:
        assert uri.startswith("keystone://"), uri


def test_manager_authored_skill_auto_prefixed(tmp_path: Path):
    scaffold = Scaffold(tmp_path / "harness")
    scaffold.bootstrap()
    result = scaffold.new_skill("release-notes", description="Cut release notes")
    created = result["created"]
    assert len(created) == 1
    assert "/skills/keystone-release-notes/SKILL.md" in created[0]


def test_manager_authored_skill_does_not_double_prefix(tmp_path: Path):
    scaffold = Scaffold(tmp_path / "harness")
    scaffold.bootstrap()
    result = scaffold.new_skill("keystone-release-notes")
    created = result["created"]
    assert len(created) == 1
    assert "/skills/keystone-release-notes/SKILL.md" in created[0]
    assert "keystone-keystone-" not in created[0]
