"""Folder adapter — Phase 23.

Walks a directory tree of markdown files and delegates per-file parsing
to the `markdown` adapter. Useful for shared-standards repos checked
out locally, or any directory of markdown the team wants to expose as
a single source.

Query selectors:

    query:
      include: ["**/*.md"]        # glob patterns, default ["**/*.md"]
      exclude: ["**/README.md"]   # glob patterns; matched files are skipped
      file: "guides/release.md"   # OR a single-file query (overrides include/exclude)

Classify selectors mirror the markdown adapter exactly (per-H2
section). Each file produces its own per-section docs; sources are
prefixed `folder://<relative-path>`.

Path-traversal is blocked: file paths must resolve under the
configured `root`. Symlinks that escape the root are refused at fetch
time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import AdapterError
from ..payload import ContextDoc
from ._classify import classify_sections
from .markdown import _parse_sections


_DEFAULT_INCLUDE = ("**/*.md",)


class FolderAdapter:
    name = "folder"

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()

    async def fetch(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        # Single-file shortcut — keeps parity with the markdown adapter
        # for trivial cases.
        single = query.get("file")
        if isinstance(single, str) and single:
            return await self._fetch_one(single, classify)
        include = self._glob_list(query.get("include"), default=_DEFAULT_INCLUDE)
        exclude = self._glob_list(query.get("exclude"), default=())
        out: list[ContextDoc] = []
        if not self._root.is_dir():
            raise AdapterError(
                f"folder adapter: root {self._root!s} does not exist"
            )
        seen: set[Path] = set()
        for pattern in include:
            for path in sorted(self._root.glob(pattern)):
                if not path.is_file():
                    continue
                if path in seen:
                    continue
                rel = self._relative(path)
                if any(path.match(p) for p in exclude):
                    continue
                seen.add(path)
                out.extend(await self._fetch_one(rel, classify))
        return out

    async def _fetch_one(
        self, rel: str, classify: dict[str, Any]
    ) -> list[ContextDoc]:
        path = (self._root / rel).resolve()
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise AdapterError(
                f"folder adapter: file {rel!r} escapes configured root"
            ) from exc
        if not path.exists():
            raise AdapterError(f"folder adapter: file not found: {path}")
        body = path.read_text(encoding="utf-8")
        source_base = f"folder://{rel}"
        return classify_sections(
            sections=_parse_sections(body),
            source_base=source_base,
            classify=classify,
            adapter_name=self.name,
            fallback_reasoning_body=body,
        )

    async def health(self) -> dict[str, Any]:
        ok = self._root.exists() and self._root.is_dir()
        return {
            "source": self.name,
            "ok": ok,
            "root": str(self._root),
            "detail": "" if ok else "root does not exist or is not a directory",
        }

    @staticmethod
    def _glob_list(
        raw: Any, *, default: tuple[str, ...]
    ) -> tuple[str, ...]:
        if raw is None:
            return tuple(default)
        if isinstance(raw, str):
            return (raw,)
        if isinstance(raw, list) and all(isinstance(p, str) for p in raw):
            return tuple(raw)
        raise AdapterError(
            "folder adapter: glob list must be a string or list of strings"
        )

    def _relative(self, path: Path) -> str:
        return str(path.relative_to(self._root))
