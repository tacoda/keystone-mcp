"""Shipped template tree for the Keystone Harness Manager.

This package is data, not code. It ships the markdown / yaml the
manager materializes into a consumer project's `.keystone/harness/` at
bootstrap or patch time. Loaded via `importlib.resources` — the file
tree under `templates/harness/` mirrors the on-disk layout in the
consumer project verbatim.

Phase 18 introduces this tree. Earlier phases inlined template strings
in `harness_scaffold.py`. The inline strings remain canonical for
single-file `Scaffold.new_*` writes; the shipped tree is what
`Scaffold.bootstrap()` materializes when the consumer asks for a
full-featured default harness.
"""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import PurePosixPath


def harness_root() -> Traversable:
    """Return a `Traversable` rooted at the shipped `templates/harness/` tree."""
    return resources.files(__name__).joinpath("harness")


def iter_harness_files() -> list[tuple[str, str]]:
    """Walk the shipped harness tree and return `[(relative_path, body)]`.

    Paths use POSIX separators so the result is portable. Hidden
    sentinel files (`.keep`, names starting with `.`) and `__pycache__`
    are skipped.
    """
    out: list[tuple[str, str]] = []
    root = harness_root()

    def walk(node: Traversable, prefix: PurePosixPath) -> None:
        for child in sorted(node.iterdir(), key=lambda c: c.name):
            name = child.name
            if name.startswith(".") or name == "__pycache__":
                continue
            sub = prefix / name
            if child.is_dir():
                walk(child, sub)
            else:
                body = child.read_text(encoding="utf-8")
                out.append((str(sub), body))

    walk(root, PurePosixPath())
    return out
