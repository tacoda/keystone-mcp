"""Harness adapter — Phase 11a.

Reads a keystone-style harness directory tree natively. The directory layout
encodes the kind of each file:

    <root>/
      guides/**.md       → rules (tiered by H2 section name)
      corpus/**.md       → reasoning (one doc per file)
      actions/*.md       → skills (one skill per file)
      playbooks/*.md     → skills (one skill per file)
      sensors/*.md       → skills (description of computational checks)

`README.md` files at any depth are skipped — they document the layout, not
content.

Guides classify by section heading. Bullets inside each tiered section
become individual rules. An IRON LAW that's a single paragraph (no bullets)
emits as one rule with `must` severity.

Tier → severity:
  IRON LAW / IRON LAWS  → must
  RULES                 → must
  GOLDEN RULE(S)        → should
  Anti-patterns         → reasoning (educational context, not constraints)
  any other H2          → ignored

A leading `MUST/SHOULD/MAY` token on a bullet still overrides the tier
default, matching the shared classifier vocabulary.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..errors import AdapterError
from ..payload import ContextDoc, Severity


_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_SEVERITY_PREFIX_RE = re.compile(
    r"^(MUST|SHOULD|MAY)\b[:.\s]*(.+)$", re.IGNORECASE | re.DOTALL
)

# Tier section name → rule severity. Matched case-insensitively against the
# H2 heading text (stripped of trailing punctuation).
_TIER_RULES: dict[str, Severity] = {
    "iron law": "must",
    "iron laws": "must",
    "rules": "must",
    "golden rule": "should",
    "golden rules": "should",
}

_TIER_REASONING = {"anti-patterns", "anti patterns"}


def _slugify(text: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return out or "section"


def _split_h2(body: str) -> list[tuple[str, str]]:
    matches = list(_H2_RE.finditer(body))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out.append((heading, body[start:end].strip()))
    return out


def _bullets(body: str) -> list[str]:
    out: list[str] = []
    for line in body.splitlines():
        m = _BULLET_RE.match(line.strip())
        if m:
            out.append(m.group(1).strip())
    return out


def _apply_severity_prefix(
    text: str, default: Severity
) -> tuple[str, Severity]:
    m = _SEVERITY_PREFIX_RE.match(text)
    if m and m.group(1).lower() in ("must", "should", "may"):
        return m.group(2).strip(), m.group(1).lower()  # type: ignore[return-value]
    return text, default


def _walk_md(root: Path) -> list[Path]:
    out: list[Path] = []
    if not root.exists():
        return out
    for p in sorted(root.rglob("*.md")):
        if p.name == "README.md":
            continue
        if not p.is_file():
            continue
        out.append(p)
    return out


def _read_guide_file(path: Path, rel: str) -> list[ContextDoc]:
    text = path.read_text(encoding="utf-8")
    file_stem = _slugify(rel.removesuffix(".md").replace("/", "-"))
    docs: list[ContextDoc] = []
    for heading, section_body in _split_h2(text):
        lower = heading.lower().strip(":.")
        slug = _slugify(heading)
        source = f"harness://{rel}#{slug}"
        if lower in _TIER_RULES:
            default_sev = _TIER_RULES[lower]
            bullets = _bullets(section_body)
            if bullets:
                for i, raw in enumerate(bullets, start=1):
                    if not raw:
                        continue
                    rule_text, severity = _apply_severity_prefix(raw, default_sev)
                    docs.append(
                        ContextDoc(
                            kind="rule",
                            text=rule_text,
                            source=source,
                            severity=severity,
                            id=f"{file_stem}-{slug}-{i:03d}",
                        )
                    )
            else:
                # IRON LAW or RULES as a single prose paragraph.
                body_clean = section_body.strip()
                if body_clean:
                    docs.append(
                        ContextDoc(
                            kind="rule",
                            text=body_clean,
                            source=source,
                            severity=default_sev,
                            id=f"{file_stem}-{slug}",
                        )
                    )
        elif lower in _TIER_REASONING:
            body_clean = section_body.strip()
            if body_clean:
                docs.append(
                    ContextDoc(
                        kind="reasoning", text=body_clean, source=source
                    )
                )
    return docs


def _read_corpus_file(path: Path, rel: str) -> list[ContextDoc]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [
        ContextDoc(kind="reasoning", text=text, source=f"harness://{rel}")
    ]


def _read_skill_file(path: Path, rel: str) -> list[ContextDoc]:
    """Read an actions/, playbooks/, or sensors/ file as a single skill."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    name = path.stem
    return [
        ContextDoc(
            kind="skill",
            text=text,
            source=f"harness://{rel}",
            name=name,
            id=_slugify(name),
        )
    ]


class HarnessAdapter:
    name = "harness"

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()

    def _subdir(self, name: str) -> Path:
        return self._root / name

    def _rel(self, path: Path) -> str:
        return str(path.relative_to(self._root))

    async def fetch(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        qtype = query.get("type")
        if not qtype:
            raise AdapterError("harness adapter: query.type is required")
        if qtype == "guides":
            return self._read_dir("guides", _read_guide_file)
        if qtype == "corpus":
            return self._read_dir("corpus", _read_corpus_file)
        if qtype == "actions":
            return self._read_dir("actions", _read_skill_file)
        if qtype == "playbooks":
            return self._read_dir("playbooks", _read_skill_file)
        if qtype == "sensors":
            return self._read_dir("sensors", _read_skill_file)
        raise AdapterError(
            f"harness adapter: unknown query.type {qtype!r} "
            "(known: guides, corpus, actions, playbooks, sensors)"
        )

    def _read_dir(self, name: str, reader) -> list[ContextDoc]:
        out: list[ContextDoc] = []
        sub = self._subdir(name)
        for path in _walk_md(sub):
            out.extend(reader(path, self._rel(path)))
        return out

    async def health(self) -> dict[str, Any]:
        ok = self._root.exists() and self._root.is_dir()
        present: list[str] = []
        if ok:
            for sub in ("guides", "corpus", "actions", "playbooks", "sensors"):
                if (self._root / sub).is_dir():
                    present.append(sub)
        return {
            "source": self.name,
            "ok": ok,
            "root": str(self._root),
            "subdirs_present": present,
            "detail": "" if ok else "root does not exist or is not a directory",
        }
