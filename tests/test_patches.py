"""Phase 21 — patch system skeleton.

No patches ship in 0.2.0; the module reports an empty state.
"""

from __future__ import annotations

from keystone_mcp.patches import (
    apply_patches,
    list_shipped_versions,
    pending_patches,
)


def test_no_shipped_versions_in_initial_release(tmp_path):
    # `templates/patches/` is shipped empty in 0.2.0.
    assert list_shipped_versions() == []


def test_pending_patches_reports_empty_when_no_versions(tmp_path):
    harness = tmp_path / "harness"
    harness.mkdir()
    summary = pending_patches(harness)
    assert summary["versions"] == []
    assert summary["pending"] == []
    assert summary["skipped_conflicts"] == []


def test_apply_patches_returns_empty_applied_when_no_versions(tmp_path):
    harness = tmp_path / "harness"
    harness.mkdir()
    result = apply_patches(harness)
    assert result["versions"] == []
    assert result["applied"] == []
    assert result["skipped_conflicts"] == []
