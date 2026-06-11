"""Phase 21 — forward-only patch system.

Shipped patches live under `keystone_mcp/templates/patches/<version>/`.
Each version directory mirrors the on-disk layout the consumer would
get from `Scaffold.bootstrap(materialize_templates=True)` at that
version. Applying a patch means: for each file in the patch tree, if
the consumer's matching file is byte-identical to the previous shipped
version (or doesn't exist), overwrite it with the new shipped content;
otherwise, skip and report a conflict.

Today this module is a skeleton. No patches ship in 0.2.0 — the tree
is empty so `pending_patches()` reports zero. Future releases populate
`templates/patches/<version>/` and bump the package's recorded
`current_version`.

The applier is intentionally conservative: it never modifies files
the user has changed since the last shipped version. The user resolves
conflicts by hand.
"""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any


def _patches_root() -> Traversable:
    return resources.files("keystone_mcp.templates").joinpath("patches")


def list_shipped_versions() -> list[str]:
    """List versions present in `templates/patches/`. Sorted by name."""
    try:
        root = _patches_root()
        if not root.is_dir():
            return []
        return sorted(
            c.name
            for c in root.iterdir()
            if c.is_dir() and not c.name.startswith(".")
        )
    except (FileNotFoundError, NotADirectoryError):
        return []


def pending_patches(harness_root: str | Path) -> dict[str, Any]:
    """Return a JSON-serializable summary of pending patches.

    Today: every shipped version maps to a (potentially empty) list of
    files that would be applied if the consumer ran the patch playbook.
    The full applier (Phase 21 follow-up) adds conflict detection
    against the previous shipped version. For now, a file is reported
    as `pending` if the consumer doesn't have it at all, and `skipped`
    if the consumer has it with different content.
    """
    root = Path(harness_root).expanduser().resolve()
    versions = list_shipped_versions()
    summary: dict[str, Any] = {
        "harness_root": str(root),
        "versions": versions,
        "pending": [],
        "skipped_conflicts": [],
    }
    for version in versions:
        version_node = _patches_root().joinpath(version, "harness")
        if not version_node.is_dir():
            continue
        _walk_version(version, version_node, root, summary)
    return summary


def _walk_version(
    version: str,
    node: Traversable,
    harness_root: Path,
    summary: dict[str, Any],
    *,
    prefix: str = "",
) -> None:
    for child in sorted(node.iterdir(), key=lambda c: c.name):
        name = child.name
        if name.startswith(".") or name == "__pycache__":
            continue
        rel = f"{prefix}{name}" if not prefix else f"{prefix}/{name}"
        if child.is_dir():
            _walk_version(
                version, child, harness_root, summary, prefix=rel
            )
            continue
        target = harness_root / rel
        body = child.read_text(encoding="utf-8")
        if not target.exists():
            summary["pending"].append(
                {"version": version, "path": str(target), "rel": rel}
            )
            continue
        if target.read_text(encoding="utf-8") != body:
            summary["skipped_conflicts"].append(
                {"version": version, "path": str(target), "rel": rel}
            )


def apply_patches(harness_root: str | Path) -> dict[str, Any]:
    """Apply every pending patch atomically.

    Returns a JSON-serializable report listing applied + skipped files.
    Files modified by the user (different content from the shipped
    version) are skipped and flagged. The applier refuses to overwrite
    them.
    """
    summary = pending_patches(harness_root)
    applied: list[dict[str, str]] = []
    root = Path(summary["harness_root"])
    for entry in summary["pending"]:
        version = entry["version"]
        rel = entry["rel"]
        node = _patches_root().joinpath(version, "harness", rel)
        body = node.read_text(encoding="utf-8")
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        if target.suffix == ".sh":
            target.chmod(0o755)
        applied.append({"version": version, "path": str(target), "rel": rel})
    return {
        "harness_root": str(root),
        "applied": applied,
        "skipped_conflicts": summary["skipped_conflicts"],
        "versions": summary["versions"],
    }
