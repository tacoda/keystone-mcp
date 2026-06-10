from pathlib import Path

import pytest

from keystone_mcp.adapters.markdown import MarkdownAdapter
from keystone_mcp.errors import AdapterError


def _adapter(tmp_path: Path) -> MarkdownAdapter:
    return MarkdownAdapter(root=tmp_path)


async def test_classifies_by_heading(tmp_path):
    (tmp_path / "p.md").write_text(
        """# Title

## Rules

- MUST do X.
- SHOULD do Y.
- MAY do Z.

## Background

Why X matters.
"""
    )
    docs = await _adapter(tmp_path).fetch(
        {"file": "p.md"},
        {"rules": {"heading": "Rules"}, "reasoning": {"heading": "Background"}},
    )
    rules = [d for d in docs if d.kind == "rule"]
    reasoning = [d for d in docs if d.kind == "reasoning"]
    assert [r.severity for r in rules] == ["must", "should", "may"]
    assert rules[0].text == "do X."
    assert rules[0].source == "markdown://p.md#rules"
    assert rules[0].id == "rules-001"
    assert len(reasoning) == 1
    assert "Why X" in reasoning[0].text


async def test_default_severity_when_no_prefix(tmp_path):
    (tmp_path / "p.md").write_text(
        """## Standards

- prefer dataclasses.
- avoid global state.
"""
    )
    docs = await _adapter(tmp_path).fetch(
        {"file": "p.md"},
        {"rules": {"heading": "Standards", "severity": "should"}},
    )
    assert all(d.severity == "should" for d in docs)


async def test_default_classify_is_whole_file_reasoning(tmp_path):
    (tmp_path / "p.md").write_text("Free-form notes.\n")
    docs = await _adapter(tmp_path).fetch({"file": "p.md"}, {})
    assert len(docs) == 1
    assert docs[0].kind == "reasoning"
    assert "Free-form" in docs[0].text


async def test_heading_list_matches_any(tmp_path):
    (tmp_path / "p.md").write_text(
        """## Constraints

- MUST X.

## Requirements

- MUST Y.
"""
    )
    docs = await _adapter(tmp_path).fetch(
        {"file": "p.md"},
        {"rules": {"heading": ["Constraints", "Requirements"]}},
    )
    rules = [d.text for d in docs if d.kind == "rule"]
    assert rules == ["X.", "Y."]


async def test_missing_file_raises(tmp_path):
    with pytest.raises(AdapterError, match="not found"):
        await _adapter(tmp_path).fetch({"file": "ghost.md"}, {})


async def test_path_traversal_blocked(tmp_path):
    with pytest.raises(AdapterError, match="escapes"):
        await _adapter(tmp_path).fetch({"file": "../etc/passwd"}, {})


async def test_query_requires_file(tmp_path):
    with pytest.raises(AdapterError, match="query.file"):
        await _adapter(tmp_path).fetch({}, {})


async def test_health_ok_when_root_exists(tmp_path):
    h = await _adapter(tmp_path).health()
    assert h["ok"] is True
    assert h["source"] == "markdown"


async def test_health_fails_when_root_missing(tmp_path):
    a = MarkdownAdapter(root=tmp_path / "does-not-exist")
    h = await a.health()
    assert h["ok"] is False


async def test_extracts_skills(tmp_path):
    (tmp_path / "p.md").write_text(
        """## Procedures

### Cut a release

1. Confirm CI is green.
2. Bump version.
3. Tag and push.

### Roll back

1. Revert commit.
2. Re-tag.
"""
    )
    docs = await _adapter(tmp_path).fetch(
        {"file": "p.md"}, {"skills": {"heading": "Procedures"}}
    )
    skills = [d for d in docs if d.kind == "skill"]
    assert [s.name for s in skills] == ["Cut a release", "Roll back"]
    assert "Confirm CI" in skills[0].text
    assert skills[0].source.endswith("#procedures/cut-a-release")
    assert skills[0].id == "procedures-001"


async def test_extracts_commands_with_fenced_invocation(tmp_path):
    (tmp_path / "p.md").write_text(
        """## Commands

### deploy

```
./scripts/deploy.sh prod
```

Run from main branch after CI is green.

### rollback

```
./scripts/rollback.sh
```
"""
    )
    docs = await _adapter(tmp_path).fetch(
        {"file": "p.md"}, {"commands": {"heading": "Commands"}}
    )
    cmds = [d for d in docs if d.kind == "command"]
    assert [c.name for c in cmds] == ["deploy", "rollback"]
    assert cmds[0].invocation == "./scripts/deploy.sh prod"
    assert "main branch" in cmds[0].text
    assert cmds[1].invocation == "./scripts/rollback.sh"


async def test_mixed_kinds_in_one_file(tmp_path):
    (tmp_path / "p.md").write_text(
        """## Rules

- MUST X.

## Procedures

### Step

Do the thing.

## Commands

### run

```
echo hi
```
"""
    )
    docs = await _adapter(tmp_path).fetch(
        {"file": "p.md"},
        {
            "rules": {"heading": "Rules"},
            "skills": {"heading": "Procedures"},
            "commands": {"heading": "Commands"},
        },
    )
    by_kind = {d.kind for d in docs}
    assert by_kind == {"rule", "skill", "command"}
