"""Repo adapter — Phase 23.

Resolves `owner/repo@version` (or a fully-qualified git URL) to a
checked-out tree and delegates to the `folder` adapter.

Settings (in `.keystone/context.yaml`):

    sources:
      org-standards:
        type: repo
        source: tacoda/tacoda-org    # owner/repo (GitHub-style) OR full git URL
        version: v1.1.2              # tag, sha, or branch (default: "main")
        cache_root: ~/.cache/keystone-mcp/repos   # optional; default shown
        ttl: 1h                       # only honored for branch refs (mutable)

Query selectors mirror the folder adapter (`include` / `exclude` /
`file`).

Cache semantics:

  * Tag or sha refs are immutable. Once fetched, the cache directory
    is never re-cloned for that combination.
  * Branch refs are mutable. The adapter respects `ttl`: if the
    on-disk fetch is older than `ttl`, the repo is re-fetched on next
    `fetch()`. Default TTL: 1h.

The actual `git` invocation is delegated to a `git_clone` callable so
tests can substitute a local-bare-repo fixture without spawning a
subprocess. Production code uses `_git_clone_subprocess`.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from ..cache import parse_ttl
from ..errors import AdapterError, ConfigError
from ..payload import ContextDoc
from .folder import FolderAdapter


_BRANCH_TTL_DEFAULT = "1h"
_MUTABLE_REF_PATTERN = re.compile(r"^(main|master|develop|trunk)$|^.*-branch$")


def _is_mutable_ref(version: str) -> bool:
    """Heuristic: tags/shas are immutable, branch names are mutable.

    Pure-hex refs ≥ 7 chars look like shas. Standard prefixed semver
    (e.g. `v1.2.3` or `1.2.3`) reads as a tag. Anything else is treated
    as a branch and respects TTL.
    """
    if re.match(r"^[0-9a-f]{7,40}$", version):
        return False
    if re.match(r"^v?\d+\.\d+(\.\d+)?(-[\w\.-]+)?$", version):
        return False
    return True


def _normalize_url(source: str) -> str:
    """Convert `owner/repo` into a GitHub HTTPS URL; pass through full URLs."""
    if "://" in source or source.startswith("git@"):
        return source
    if "/" in source and not source.startswith("/"):
        return f"https://github.com/{source}.git"
    raise ConfigError(
        f"repo adapter: source {source!r} is neither owner/repo nor a git URL"
    )


def _cache_path(url: str, version: str, cache_root: Path) -> Path:
    """Deterministic cache directory per (url, version)."""
    h = hashlib.sha256(f"{url}@{version}".encode("utf-8")).hexdigest()[:16]
    return cache_root / h


def _git_clone_subprocess(url: str, ref: str, dest: Path) -> None:
    """Production git clone. Shallow, single-branch where possible."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    cmd = [
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        ref,
        "--single-branch",
        url,
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return
    except subprocess.CalledProcessError:
        # Fall back to a full clone + checkout for sha refs that
        # `--branch` can't reach.
        pass
    if dest.exists():
        shutil.rmtree(dest)
    subprocess.run(["git", "clone", url, str(dest)], check=True, capture_output=True)
    subprocess.run(
        ["git", "checkout", ref], cwd=str(dest), check=True, capture_output=True
    )


GitCloneFn = Callable[[str, str, Path], None]


class RepoAdapter:
    name = "repo"

    def __init__(
        self,
        source: str,
        version: str = "main",
        cache_root: str | Path | None = None,
        ttl: str | None = None,
        git_clone: GitCloneFn | None = None,
    ) -> None:
        self._source = source
        self._version = version
        self._url = _normalize_url(source)
        default_cache = Path(
            os.environ.get(
                "KEYSTONE_REPO_CACHE",
                "~/.cache/keystone-mcp/repos",
            )
        )
        self._cache_root = Path(cache_root or default_cache).expanduser().resolve()
        ttl_str = ttl or _BRANCH_TTL_DEFAULT
        self._ttl_seconds = parse_ttl(ttl_str)
        self._git_clone = git_clone or _git_clone_subprocess

    def _ensure_clone(self) -> Path:
        dest = _cache_path(self._url, self._version, self._cache_root)
        mutable = _is_mutable_ref(self._version)
        if dest.exists():
            if not mutable:
                # Immutable refs: never re-fetch.
                return dest
            # Mutable: respect TTL.
            stamp = dest / ".keystone-fetched"
            if stamp.exists():
                age = time.time() - stamp.stat().st_mtime
                if age < self._ttl_seconds:
                    return dest
            shutil.rmtree(dest)
        self._git_clone(self._url, self._version, dest)
        (dest / ".keystone-fetched").write_text("")
        return dest

    async def fetch(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        root = await asyncio.to_thread(self._ensure_clone)
        folder = FolderAdapter(root=root)
        docs = await folder.fetch(query, classify)
        # Rewrite source prefixes to `repo://owner/repo@version/…` so
        # consumers know which checkout the doc came from.
        prefix = f"repo://{self._source}@{self._version}/"
        return [
            ContextDoc(
                kind=d.kind,
                text=d.text,
                source=d.source.replace("folder://", prefix),
                severity=d.severity,
                recency=d.recency,
                id=d.id,
                name=d.name,
                invocation=d.invocation,
            )
            for d in docs
        ]

    async def health(self) -> dict[str, Any]:
        # Health reports whether the cache directory exists and is
        # readable. It does NOT perform a fresh clone — that's
        # expensive. Doctor / verify can drill in with `fetch()` when
        # the user explicitly asks.
        dest = _cache_path(self._url, self._version, self._cache_root)
        ok = dest.exists() and dest.is_dir()
        return {
            "source": self.name,
            "ok": ok,
            "url": self._url,
            "version": self._version,
            "cache_path": str(dest),
            "detail": "" if ok else "not yet fetched; call fetch() to populate cache",
        }
