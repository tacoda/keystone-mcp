"""Phase 23 — folder adapter.

Walks a local directory of markdown, delegates per-file to the
markdown parser, surfaces docs with `folder://<rel>` sources.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from keystone_mcp.adapters.folder import FolderAdapter
from keystone_mcp.errors import AdapterError


def _seed(tmp_path: Path) -> Path:
    root = tmp_path / "policies"
    root.mkdir()
    (root / "release.md").write_text(
        "# Release\n\n## Rules\n\n- MUST tag every release.\n\n## Background\n\nWhy releases matter.\n"
    )
    sub = root / "process"
    sub.mkdir()
    (sub / "rollback.md").write_text(
        "# Rollback\n\n## Rules\n\n- MUST capture a postmortem.\n"
    )
    (root / "README.md").write_text("# README — skip me\n\n## Rules\n\n- ignored\n")
    return root


async def test_walks_default_glob_md_files(tmp_path):
    root = _seed(tmp_path)
    adapter = FolderAdapter(root=root)
    docs = await adapter.fetch(
        query={},
        classify={
            "rules": {"heading": "Rules"},
            "reasoning": {"heading": "Background"},
        },
    )
    sources = sorted({d.source for d in docs})
    assert any(s.startswith("folder://release.md") for s in sources)
    assert any(s.startswith("folder://process/rollback.md") for s in sources)


async def test_exclude_skips_matched_files(tmp_path):
    root = _seed(tmp_path)
    adapter = FolderAdapter(root=root)
    docs = await adapter.fetch(
        query={"exclude": ["**/rollback.md"]},
        classify={"rules": {"heading": "Rules"}},
    )
    sources = {d.source for d in docs}
    assert not any("rollback.md" in s for s in sources)


async def test_single_file_query_overrides_globbing(tmp_path):
    root = _seed(tmp_path)
    adapter = FolderAdapter(root=root)
    docs = await adapter.fetch(
        query={"file": "release.md"},
        classify={"rules": {"heading": "Rules"}},
    )
    assert docs
    assert all(d.source.startswith("folder://release.md") for d in docs)


async def test_path_traversal_blocked(tmp_path):
    root = _seed(tmp_path)
    adapter = FolderAdapter(root=root)
    with pytest.raises(AdapterError, match="escapes"):
        await adapter.fetch(
            query={"file": "../etc/passwd"},
            classify={"rules": {"heading": "Rules"}},
        )


async def test_health_reports_missing_root(tmp_path):
    adapter = FolderAdapter(root=tmp_path / "nope")
    health = await adapter.health()
    assert health["ok"] is False


async def test_health_reports_present_root(tmp_path):
    root = _seed(tmp_path)
    adapter = FolderAdapter(root=root)
    health = await adapter.health()
    assert health["ok"] is True
    assert health["root"].endswith("policies")
