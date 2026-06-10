"""Markdown adapter — Phase 1.

Reads a repo-local markdown file. Splits into sections by H2 heading. Each
section is classified as rules, reasoning, skills, or commands based on the
`classify` block in config.

Classify selector vocabulary (Phase 1):

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

For a `rules` section, each top-level bullet (`-` or `*`) becomes one rule.
A leading `MUST`/`SHOULD`/`MAY` token overrides the default severity.

For a `reasoning` section, the entire body becomes one reasoning entry.

For `skills` and `commands` sections, each `### Name` sub-heading delimits one
entry. For commands, the first fenced code block in the entry body is parsed
out as the invocation; the remaining prose is the description.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..errors import AdapterError, ConfigError
from ..payload import ContextDoc, Severity


_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H3_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_SEVERITY_PREFIX_RE = re.compile(r"^(MUST|SHOULD|MAY)\b[:.\s]*(.+)$", re.IGNORECASE)
_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)\n```", re.DOTALL)


def _slugify(text: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return out or "section"


def _split_by(pattern: re.Pattern[str], body: str) -> list[tuple[str, str]]:
    """Return [(heading, content)] split by pattern. Content before first match dropped."""
    matches = list(pattern.finditer(body))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out.append((heading, body[start:end].strip()))
    return out


def _headings_of(selector: dict[str, Any] | None) -> set[str]:
    if not selector:
        return set()
    h = selector.get("heading")
    if h is None:
        return set()
    if isinstance(h, str):
        return {h.strip().lower()}
    if isinstance(h, list):
        return {str(x).strip().lower() for x in h}
    raise ConfigError(f"classify.heading must be string or list, got {type(h).__name__}")


def _extract_rules(
    body: str,
    *,
    source_base: str,
    heading_slug: str,
    default_severity: Severity,
) -> list[ContextDoc]:
    out: list[ContextDoc] = []
    idx = 0
    for line in body.splitlines():
        m = _BULLET_RE.match(line.strip())
        if not m:
            continue
        text = m.group(1).strip()
        severity: Severity = default_severity
        sev_match = _SEVERITY_PREFIX_RE.match(text)
        if sev_match:
            tok = sev_match.group(1).lower()
            if tok in ("must", "should", "may"):
                severity = tok  # type: ignore[assignment]
                text = sev_match.group(2).strip()
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


def _extract_reasoning(
    body: str, *, source_base: str, heading_slug: str
) -> list[ContextDoc]:
    text = body.strip()
    if not text:
        return []
    return [
        ContextDoc(
            kind="reasoning", text=text, source=f"{source_base}#{heading_slug}"
        )
    ]


def _extract_skills(
    body: str, *, source_base: str, heading_slug: str
) -> list[ContextDoc]:
    out: list[ContextDoc] = []
    idx = 0
    for name, sub_body in _split_by(_H3_RE, body):
        idx += 1
        sub_slug = _slugify(name)
        out.append(
            ContextDoc(
                kind="skill",
                text=sub_body,
                source=f"{source_base}#{heading_slug}/{sub_slug}",
                name=name,
                id=f"{heading_slug}-{idx:03d}",
            )
        )
    return out


def _extract_commands(
    body: str, *, source_base: str, heading_slug: str
) -> list[ContextDoc]:
    out: list[ContextDoc] = []
    idx = 0
    for name, sub_body in _split_by(_H3_RE, body):
        idx += 1
        sub_slug = _slugify(name)
        fence = _FENCE_RE.search(sub_body)
        invocation = fence.group(1).strip() if fence else ""
        if fence:
            description = (sub_body[: fence.start()] + sub_body[fence.end():]).strip()
        else:
            description = sub_body.strip()
        out.append(
            ContextDoc(
                kind="command",
                text=description,
                source=f"{source_base}#{heading_slug}/{sub_slug}",
                name=name,
                invocation=invocation,
                id=f"{heading_slug}-{idx:03d}",
            )
        )
    return out


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

        rules_sel = classify.get("rules")
        reasoning_sel = classify.get("reasoning")
        skills_sel = classify.get("skills")
        commands_sel = classify.get("commands")

        default_severity: Severity = "must"
        if isinstance(rules_sel, dict):
            sev = rules_sel.get("severity", "must")
            if sev not in ("must", "should", "may"):
                raise ConfigError(
                    f"classify.rules.severity must be must|should|may, got {sev!r}"
                )
            default_severity = sev  # type: ignore[assignment]

        rule_headings = _headings_of(rules_sel)
        reasoning_headings = _headings_of(reasoning_sel)
        skill_headings = _headings_of(skills_sel)
        command_headings = _headings_of(commands_sel)
        reasoning_all = bool(
            isinstance(reasoning_sel, dict) and reasoning_sel.get("all")
        )

        anything_configured = bool(
            rule_headings
            or reasoning_headings
            or skill_headings
            or command_headings
            or reasoning_all
        )
        if not anything_configured:
            # Default: whole file is reasoning.
            return [
                ContextDoc(kind="reasoning", text=body.strip(), source=source_base)
            ]

        docs: list[ContextDoc] = []
        for heading, content in _split_by(_H2_RE, body):
            lower = heading.lower()
            slug = _slugify(heading)
            if lower in rule_headings:
                docs.extend(
                    _extract_rules(
                        content,
                        source_base=source_base,
                        heading_slug=slug,
                        default_severity=default_severity,
                    )
                )
            elif lower in skill_headings:
                docs.extend(
                    _extract_skills(
                        content, source_base=source_base, heading_slug=slug
                    )
                )
            elif lower in command_headings:
                docs.extend(
                    _extract_commands(
                        content, source_base=source_base, heading_slug=slug
                    )
                )
            elif lower in reasoning_headings or reasoning_all:
                docs.extend(
                    _extract_reasoning(
                        content, source_base=source_base, heading_slug=slug
                    )
                )
        return docs

    async def health(self) -> dict[str, Any]:
        ok = self._root.exists() and self._root.is_dir()
        return {
            "source": self.name,
            "ok": ok,
            "root": str(self._root),
            "detail": "" if ok else "root does not exist or is not a directory",
        }
