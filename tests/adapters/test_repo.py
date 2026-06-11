"""Phase 23 — repo adapter.

Uses a fake `git_clone` callable that materializes a local tree, so no
network or real git invocation runs in tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from keystone_mcp.adapters.repo import (
    RepoAdapter,
    _is_mutable_ref,
    _normalize_url,
)
from keystone_mcp.errors import ConfigError


def _materializer(tree: dict[str, str]):
    """Return a `git_clone` callable that writes `tree` into `dest`."""

    def clone(url: str, ref: str, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        for rel, body in tree.items():
            path = dest / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)

    return clone


def test_normalize_url_owner_repo_to_github_https():
    assert _normalize_url("tacoda/repo") == "https://github.com/tacoda/repo.git"


def test_normalize_url_passes_full_url_through():
    url = "https://gitlab.com/team/repo.git"
    assert _normalize_url(url) == url
    assert _normalize_url("git@github.com:foo/bar.git") == "git@github.com:foo/bar.git"


def test_normalize_url_rejects_nonsense():
    with pytest.raises(ConfigError):
        _normalize_url("not-an-identifier")


def test_is_mutable_ref_distinguishes_tags_shas_branches():
    assert _is_mutable_ref("main") is True
    assert _is_mutable_ref("feature-branch") is True
    assert _is_mutable_ref("v1.2.3") is False
    assert _is_mutable_ref("1.2.3-rc1") is False
    assert _is_mutable_ref("abc1234") is False  # sha7
    assert _is_mutable_ref("0123456789abcdef0123456789abcdef01234567") is False


async def test_repo_adapter_clones_and_fetches(tmp_path):
    tree = {
        "release.md": "# Release\n\n## Rules\n\n- MUST tag every release.\n",
        "policies/rollback.md": "# Rollback\n\n## Rules\n\n- MUST postmortem.\n",
    }
    adapter = RepoAdapter(
        source="tacoda/repo",
        version="v1.0.0",
        cache_root=tmp_path / "cache",
        git_clone=_materializer(tree),
    )
    docs = await adapter.fetch(
        query={},
        classify={"rules": {"heading": "Rules"}},
    )
    sources = sorted({d.source for d in docs})
    assert any(s.startswith("repo://tacoda/repo@v1.0.0/") for s in sources)
    assert any("release.md" in s for s in sources)
    assert any("policies/rollback.md" in s for s in sources)


async def test_repo_adapter_immutable_ref_caches(tmp_path):
    tree = {"release.md": "# r\n\n## Rules\n\n- a.\n"}
    call_count = {"n": 0}

    def clone(url: str, ref: str, dest: Path) -> None:
        call_count["n"] += 1
        return _materializer(tree)(url, ref, dest)

    adapter = RepoAdapter(
        source="tacoda/repo",
        version="v1.0.0",
        cache_root=tmp_path / "cache",
        git_clone=clone,
    )
    await adapter.fetch(query={}, classify={"rules": {"heading": "Rules"}})
    await adapter.fetch(query={}, classify={"rules": {"heading": "Rules"}})
    # Immutable tag: clone once.
    assert call_count["n"] == 1


async def test_repo_adapter_branch_ref_respects_ttl(tmp_path):
    tree = {"release.md": "# r\n\n## Rules\n\n- a.\n"}
    call_count = {"n": 0}

    def clone(url: str, ref: str, dest: Path) -> None:
        call_count["n"] += 1
        return _materializer(tree)(url, ref, dest)

    adapter = RepoAdapter(
        source="tacoda/repo",
        version="main",  # mutable
        cache_root=tmp_path / "cache",
        ttl="1h",
        git_clone=clone,
    )
    await adapter.fetch(query={}, classify={"rules": {"heading": "Rules"}})
    # Within TTL: second call reuses cache.
    await adapter.fetch(query={}, classify={"rules": {"heading": "Rules"}})
    assert call_count["n"] == 1


async def test_repo_adapter_health_before_fetch_is_not_ok(tmp_path):
    adapter = RepoAdapter(
        source="tacoda/repo",
        version="v1.0.0",
        cache_root=tmp_path / "cache",
        git_clone=_materializer({"x.md": "x"}),
    )
    health = await adapter.health()
    assert health["ok"] is False
    assert "not yet fetched" in health["detail"]


async def test_repo_adapter_health_after_fetch_is_ok(tmp_path):
    adapter = RepoAdapter(
        source="tacoda/repo",
        version="v1.0.0",
        cache_root=tmp_path / "cache",
        git_clone=_materializer({"x.md": "# x\n\n## Rules\n\n- a.\n"}),
    )
    await adapter.fetch(query={}, classify={"rules": {"heading": "Rules"}})
    health = await adapter.health()
    assert health["ok"] is True
