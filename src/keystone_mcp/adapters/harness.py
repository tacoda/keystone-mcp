"""Harness adapter — Phase 11a (revised Phase 14a, Phase 14c).

Reads a keystone-style harness directory tree natively. The directory layout
encodes the kind of each file:

    <root>/
      guides/**.md       → rules (tiered by H2 section name)
      corpus/**.md       → reasoning (one doc per file)
      sensors/*.md       → commands (blocking checks; invocation pulled from
                          YAML frontmatter `script:` field pointing into
                          `<root>/scripts/`)

Sensors are *blocking rules* — the agent must run them and they must pass
for any workflow to continue. The sensor markdown describes WHAT to check;
the matching shell script under `<root>/scripts/` is HOW to check.

Project-local skills live at `<root>/skills/<name>/SKILL.md` and are served
by FastMCP's `SkillsDirectoryProvider` as `skill://` resources, NOT through
this adapter.

`README.md` files at any depth are skipped — they document the layout, not
content.

Guides classify by section heading. Bullets inside each tiered section
become individual rules. An IRON LAW that's a single paragraph (no bullets)
emits as one rule with `must` severity.

Tier strictness cascade (non-negotiable > strong > rules):
  NON-NEGOTIABLE / IRON LAW(S)  → must     (can never be violated)
  STRONG / GOLDEN RULE(S)       → should   (hard rule; deviation needs reasoning)
  RULES                         → may      (regular rule; strong rules override)
  Anti-patterns                 → reasoning (educational context, not constraints)
  any other H2                  → ignored

Older keystone-style headings (IRON LAW, GOLDEN RULES) are still recognized
so harnesses written before the rename keep parsing.

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
    "non-negotiable": "must",
    "non negotiable": "must",
    # Backward compat with older keystone harnesses:
    "iron law": "must",
    "iron laws": "must",
    "strong": "should",
    # Backward compat:
    "golden rule": "should",
    "golden rules": "should",
    "rules": "may",
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


_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _parse_frontmatter(body: str) -> tuple[dict[str, str], str]:
    """Parse a tiny `key: value` YAML frontmatter. Returns (fields, rest).

    Deliberately not full YAML — keystone sensor frontmatter is a small,
    flat key/value set and pulling in PyYAML for this is overkill.
    """
    m = _FRONTMATTER_RE.match(body)
    if not m:
        return {}, body
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body[m.end():]


def _read_sensor_file(path: Path, rel: str) -> list[ContextDoc]:
    """Read a sensor file. Sensors emit `command` kind — they are blocking
    rules whose invocation is the shell script under `<root>/scripts/`.
    """
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []
    frontmatter, body = _parse_frontmatter(text)
    name = path.stem
    script = frontmatter.get("script", "").strip()
    invocation = f".keystone/harness/scripts/{script}" if script else ""
    return [
        ContextDoc(
            kind="command",
            text=body.strip(),
            source=f"harness://{rel}",
            name=name,
            invocation=invocation,
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
        if qtype == "sensors":
            return self._read_dir("sensors", _read_sensor_file)
        raise AdapterError(
            f"harness adapter: unknown query.type {qtype!r} "
            "(known: guides, corpus, sensors). "
            "Project-local skills live at .keystone/harness/skills/<name>/SKILL.md "
            "and are served via FastMCP's SkillsDirectoryProvider as `skill://` "
            "resources, not through this adapter."
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
            for sub in ("guides", "corpus", "sensors", "skills"):
                if (self._root / sub).is_dir():
                    present.append(sub)
        return {
            "source": self.name,
            "ok": ok,
            "root": str(self._root),
            "subdirs_present": present,
            "detail": "" if ok else "root does not exist or is not a directory",
        }
