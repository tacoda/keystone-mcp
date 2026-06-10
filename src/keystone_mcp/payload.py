from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Severity = Literal["must", "should", "may"]
DocKind = Literal["rule", "reasoning", "skill", "command"]


@dataclass(frozen=True)
class Rule:
    text: str
    source: str
    severity: Severity = "must"
    id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "text": self.text,
            "source": self.source,
            "severity": self.severity,
        }
        if self.id is not None:
            d["id"] = self.id
        return d


@dataclass(frozen=True)
class Reasoning:
    text: str
    source: str
    recency: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"text": self.text, "source": self.source}
        if self.recency is not None:
            d["recency"] = self.recency
        return d


@dataclass(frozen=True)
class Skill:
    """Procedural know-how the agent can follow. Multi-step how-to."""

    name: str
    body: str
    source: str
    id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "body": self.body, "source": self.source}
        if self.id is not None:
            d["id"] = self.id
        return d


@dataclass(frozen=True)
class Command:
    """A canned invocation (typically a shell command) with usage context."""

    name: str
    invocation: str
    description: str
    source: str
    id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "invocation": self.invocation,
            "description": self.description,
            "source": self.source,
        }
        if self.id is not None:
            d["id"] = self.id
        return d


@dataclass(frozen=True)
class ContextDoc:
    """One classified chunk emitted by an adapter.

    Fields used by each kind:
      rule       → text, source, severity, id
      reasoning  → text, source, recency
      skill      → name, text (=body), source, id
      command    → name, invocation, text (=description), source, id
    """

    kind: DocKind
    text: str
    source: str
    severity: Severity = "must"
    recency: str | None = None
    id: str | None = None
    name: str | None = None
    invocation: str | None = None


@dataclass
class ContextEnvelope:
    topic: str
    rules: list[Rule] = field(default_factory=list)
    reasoning: list[Reasoning] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    fetched_at: str = ""
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "rules": [r.to_dict() for r in self.rules],
            "reasoning": [r.to_dict() for r in self.reasoning],
            "skills": [s.to_dict() for s in self.skills],
            "commands": [c.to_dict() for c in self.commands],
            "fetched_at": self.fetched_at,
            "cache_hit": self.cache_hit,
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_SEVERITY_RANK: dict[str, int] = {"may": 0, "should": 1, "must": 2}


def _norm_rule_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def merge_rules(rules: list[Rule]) -> list[Rule]:
    """Dedup rules by normalized text. Highest severity wins; ties keep all.

    Two rules whose `text` normalizes to the same string are treated as the
    same rule expressed by different sources. The highest severity in the
    group wins and is emitted as-is; lower-severity duplicates are dropped.
    On a tie at the top severity, all tied rules are kept so the agent can
    cite both sources.
    """
    by_key: dict[str, list[Rule]] = {}
    order: list[str] = []
    for r in rules:
        k = _norm_rule_text(r.text)
        if k not in by_key:
            order.append(k)
            by_key[k] = []
        by_key[k].append(r)
    out: list[Rule] = []
    for k in order:
        group = by_key[k]
        if len(group) == 1:
            out.append(group[0])
            continue
        top = max(_SEVERITY_RANK[r.severity] for r in group)
        out.extend(r for r in group if _SEVERITY_RANK[r.severity] == top)
    return out


def docs_to_envelope(topic: str, docs: list[ContextDoc]) -> ContextEnvelope:
    rules: list[Rule] = []
    reasoning: list[Reasoning] = []
    skills: list[Skill] = []
    commands: list[Command] = []
    for d in docs:
        if d.kind == "rule":
            rules.append(Rule(text=d.text, source=d.source, severity=d.severity, id=d.id))
        elif d.kind == "reasoning":
            reasoning.append(Reasoning(text=d.text, source=d.source, recency=d.recency))
        elif d.kind == "skill":
            skills.append(
                Skill(
                    name=d.name or "(unnamed)",
                    body=d.text,
                    source=d.source,
                    id=d.id,
                )
            )
        elif d.kind == "command":
            commands.append(
                Command(
                    name=d.name or "(unnamed)",
                    invocation=d.invocation or "",
                    description=d.text,
                    source=d.source,
                    id=d.id,
                )
            )
    return ContextEnvelope(
        topic=topic,
        rules=rules,
        reasoning=reasoning,
        skills=skills,
        commands=commands,
        fetched_at=now_iso(),
    )
