"""Shared classifier primitives for heading-based adapters.

Markdown, Confluence, and Notion all parse content shaped the same way:

  H2 heading
    bullets...                ← used when classified as `rules`
    body paragraphs           ← used when classified as `reasoning`
    H3 sub-headings           ← each one is a `skill` or `command`
      sub-body text
      first code block        ← becomes a command's `invocation`

The adapter does the native parsing (regex / HTML / blocks) once, builds a
`list[Section]` with all three views populated, then hands it to
`classify_sections()`. The classifier picks which view to consume per
section based on the `classify` block in config.

Centralizing this in one module means:
  - Markdown / Confluence / Notion share severity-prefix parsing, slug
    generation, id format, source-URI shape, and the H2→H3 contract.
  - A new heading-based adapter only writes the native-to-Section parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..errors import AdapterError
from ..payload import ContextDoc, Severity


_SEVERITY_PREFIX_RE = re.compile(
    r"^(MUST|SHOULD|MAY)\b[:.\s]*(.+)$", re.IGNORECASE | re.DOTALL
)


@dataclass(frozen=True)
class SubBlock:
    """One H3-delimited entry inside a skills or commands section."""

    name: str
    body: str = ""
    code: str = ""


@dataclass(frozen=True)
class Section:
    """One H2-delimited section. All three views populated up front; the
    classifier picks one based on which kind the section's heading binds to.
    """

    heading: str
    bullets: list[str] = field(default_factory=list)
    sub_blocks: list[SubBlock] = field(default_factory=list)
    body: str = ""


def slugify(text: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return out or "section"


def headings_of(
    adapter_name: str, selector: dict[str, Any] | None
) -> set[str]:
    if not selector:
        return set()
    h = selector.get("heading")
    if h is None:
        return set()
    if isinstance(h, str):
        return {h.strip().lower()}
    if isinstance(h, list):
        return {str(x).strip().lower() for x in h}
    raise AdapterError(
        f"{adapter_name} adapter: classify.heading must be string or list, "
        f"got {type(h).__name__}"
    )


def severity_default(adapter_name: str, classify: dict[str, Any]) -> Severity:
    rules = classify.get("rules")
    if isinstance(rules, dict):
        sev = rules.get("severity", "must")
        if sev not in ("must", "should", "may"):
            raise AdapterError(
                f"{adapter_name} adapter: classify.rules.severity must be "
                f"must|should|may, got {sev!r}"
            )
        return sev  # type: ignore[return-value]
    return "must"


def _emit_rules(
    section: Section,
    *,
    source_base: str,
    heading_slug: str,
    default_severity: Severity,
) -> list[ContextDoc]:
    out: list[ContextDoc] = []
    idx = 0
    for raw in section.bullets:
        text = raw.strip()
        if not text:
            continue
        severity: Severity = default_severity
        m = _SEVERITY_PREFIX_RE.match(text)
        if m and m.group(1).lower() in ("must", "should", "may"):
            severity = m.group(1).lower()  # type: ignore[assignment]
            text = m.group(2).strip()
        idx += 1
        out.append(
            ContextDoc(
                kind="rule",
                text=text,
                source=f"{source_base}#{heading_slug}",
                severity=severity,
                id=f"{heading_slug}-{idx:03d}",
            )
        )
    return out


def _emit_reasoning(
    section: Section, *, source_base: str, heading_slug: str
) -> list[ContextDoc]:
    body = section.body.strip()
    if not body:
        return []
    return [
        ContextDoc(
            kind="reasoning", text=body, source=f"{source_base}#{heading_slug}"
        )
    ]


def _emit_skills(
    section: Section, *, source_base: str, heading_slug: str
) -> list[ContextDoc]:
    out: list[ContextDoc] = []
    for i, sb in enumerate(section.sub_blocks, start=1):
        sub_slug = slugify(sb.name)
        out.append(
            ContextDoc(
                kind="skill",
                text=sb.body.strip(),
                source=f"{source_base}#{heading_slug}/{sub_slug}",
                name=sb.name,
                id=f"{heading_slug}-{i:03d}",
            )
        )
    return out


def _emit_commands(
    section: Section, *, source_base: str, heading_slug: str
) -> list[ContextDoc]:
    out: list[ContextDoc] = []
    for i, sb in enumerate(section.sub_blocks, start=1):
        sub_slug = slugify(sb.name)
        out.append(
            ContextDoc(
                kind="command",
                text=sb.body.strip(),
                source=f"{source_base}#{heading_slug}/{sub_slug}",
                name=sb.name,
                invocation=sb.code.strip(),
                id=f"{heading_slug}-{i:03d}",
            )
        )
    return out


def classify_sections(
    *,
    sections: list[Section],
    source_base: str,
    classify: dict[str, Any],
    adapter_name: str,
    fallback_reasoning_body: str = "",
) -> list[ContextDoc]:
    """Apply `classify` selectors over pre-parsed sections.

    If `classify` declares no kind at all, the entire
    `fallback_reasoning_body` is emitted as a single reasoning doc (source
    URI = `source_base`, no fragment).
    """
    rule_h = headings_of(adapter_name, classify.get("rules"))
    reasoning_h = headings_of(adapter_name, classify.get("reasoning"))
    skill_h = headings_of(adapter_name, classify.get("skills"))
    command_h = headings_of(adapter_name, classify.get("commands"))
    reasoning_all = bool(
        isinstance(classify.get("reasoning"), dict)
        and classify["reasoning"].get("all")
    )
    default_severity = severity_default(adapter_name, classify)

    anything = bool(
        rule_h or reasoning_h or skill_h or command_h or reasoning_all
    )
    if not anything:
        body = fallback_reasoning_body.strip()
        if not body:
            return []
        return [ContextDoc(kind="reasoning", text=body, source=source_base)]

    docs: list[ContextDoc] = []
    for section in sections:
        lower = section.heading.lower()
        slug = slugify(section.heading)
        if lower in rule_h:
            docs.extend(
                _emit_rules(
                    section,
                    source_base=source_base,
                    heading_slug=slug,
                    default_severity=default_severity,
                )
            )
        elif lower in skill_h:
            docs.extend(
                _emit_skills(
                    section, source_base=source_base, heading_slug=slug
                )
            )
        elif lower in command_h:
            docs.extend(
                _emit_commands(
                    section, source_base=source_base, heading_slug=slug
                )
            )
        elif lower in reasoning_h or reasoning_all:
            docs.extend(
                _emit_reasoning(
                    section, source_base=source_base, heading_slug=slug
                )
            )
    return docs
