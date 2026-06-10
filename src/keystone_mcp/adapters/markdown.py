"""Markdown adapter — Phase 1, refactored in Phase 8.

Reads a repo-local markdown file. Splits into sections by H2 heading; each
section is normalized to the shared `Section` shape and handed to the shared
classifier in `_classify.py`.

Classify selector vocabulary (shared across markdown, Confluence, Notion):

    classify:
      rules:
        heading: "Rules"             # single heading
        # or
        heading: ["Rules", "Must"]   # any of
        severity: must               # default severity (default: "must")
      reasoning:
        heading: "Background"
        all: true                    # everything not matched (when heading omitted)
      skills:
        heading: "Skills"            # each H3 under this H2 = one skill
      commands:
        heading: "Commands"          # each H3 under this H2 = one command
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..errors import AdapterError
from ..payload import ContextDoc
from ._classify import Section, SubBlock, classify_sections


_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H3_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)\n```", re.DOTALL)


def _split_by(pattern: re.Pattern[str], body: str) -> list[tuple[str, str]]:
    matches = list(pattern.finditer(body))
    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append((heading, body[start:end].strip()))
    return sections


def _bullets_in(body: str) -> list[str]:
    out: list[str] = []
    for line in body.splitlines():
        m = _BULLET_RE.match(line.strip())
        if m:
            out.append(m.group(1).strip())
    return out


def _sub_blocks_in(body: str) -> list[SubBlock]:
    blocks: list[SubBlock] = []
    for name, sub_body in _split_by(_H3_RE, body):
        fence = _FENCE_RE.search(sub_body)
        if fence:
            code = fence.group(1).strip()
            without_code = (sub_body[: fence.start()] + sub_body[fence.end():]).strip()
        else:
            code = ""
            without_code = sub_body.strip()
        blocks.append(SubBlock(name=name, body=without_code, code=code))
    return blocks


def _parse_sections(body: str) -> list[Section]:
    sections: list[Section] = []
    for heading, section_body in _split_by(_H2_RE, body):
        sections.append(
            Section(
                heading=heading,
                bullets=_bullets_in(section_body),
                sub_blocks=_sub_blocks_in(section_body),
                body=section_body,
            )
        )
    return sections


class MarkdownAdapter:
    name = "markdown"

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()

    async def fetch(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        rel = query.get("file")
        if not rel or not isinstance(rel, str):
            raise AdapterError("markdown adapter: query.file is required (string)")
        path = (self._root / rel).resolve()
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise AdapterError(
                f"markdown adapter: file {rel!r} escapes configured root"
            ) from exc
        if not path.exists():
            raise AdapterError(f"markdown adapter: file not found: {path}")
        body = path.read_text(encoding="utf-8")
        source_base = f"markdown://{rel}"
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
