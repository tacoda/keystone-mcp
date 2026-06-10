from pathlib import Path

import pytest

from keystone_mcp.adapters.harness import HarnessAdapter
from keystone_mcp.errors import AdapterError


def _adapter(root: Path) -> HarnessAdapter:
    return HarnessAdapter(root=root)


def _build_min_harness(root: Path) -> None:
    """A minimal harness tree exercising every supported subdir."""
    (root / "guides" / "process").mkdir(parents=True)
    (root / "guides" / "process" / "dangerous-actions.md").write_text(
        """# Dangerous Actions

## IRON LAW

**NEVER PERFORM A DANGEROUS ACTION WITHOUT EXPLICIT CONFIRMATION.**

## RULES

- Show, then confirm.
- Refuse to chain dangerous actions.

## GOLDEN RULES

- Aim to keep a recovery path open.
- Aim to never act on shared state without a written audit trail.

## Anti-patterns

- `&& rm -rf` tacked onto a normal command.
- Confirming once and assuming that covers future runs.
"""
    )
    (root / "guides" / "README.md").write_text("documentation, should be skipped")

    (root / "corpus").mkdir()
    (root / "corpus" / "architecture.md").write_text(
        """# Architecture overview

The system is a context broker.
"""
    )

    (root / "skills" / "cut-release").mkdir(parents=True)
    (root / "skills" / "cut-release" / "SKILL.md").write_text(
        """---
description: Cut a patch release
---

# cut-release

Bump version, tag, push.
"""
    )

    (root / "sensors").mkdir()
    (root / "sensors" / "build.md").write_text(
        """---
kind: computational
---

# Sensor: build

The project's build / compile / package step.
"""
    )


async def test_guides_emits_tiered_rules(tmp_path):
    _build_min_harness(tmp_path)
    docs = await _adapter(tmp_path).fetch({"type": "guides"}, {})
    rules = [d for d in docs if d.kind == "rule"]
    by_sev: dict[str, list] = {}
    for d in rules:
        by_sev.setdefault(d.severity, []).append(d)

    # Cascade: non-negotiable (must) > strong (should) > rules (may).
    # The fixture uses legacy headings (IRON LAW, GOLDEN RULES, RULES) —
    # those still map to the same tiers for backward compat.

    # IRON LAW (paragraph, must) → 1 doc
    musts = by_sev["must"]
    assert len(musts) == 1
    assert "NEVER PERFORM A DANGEROUS ACTION" in musts[0].text

    # GOLDEN RULES (2 bullets, should) → 2 docs
    shoulds = by_sev["should"]
    assert len(shoulds) == 2
    assert all("Aim to" in d.text for d in shoulds)

    # RULES (2 bullets, may) → 2 docs (un-prefixed bullets default to may)
    mays = by_sev["may"]
    assert len(mays) == 2
    assert any("Show, then confirm." in d.text for d in mays)


async def test_guides_emits_anti_patterns_as_reasoning(tmp_path):
    _build_min_harness(tmp_path)
    docs = await _adapter(tmp_path).fetch({"type": "guides"}, {})
    reasoning = [d for d in docs if d.kind == "reasoning"]
    assert len(reasoning) == 1
    assert "rm -rf" in reasoning[0].text


async def test_guides_severity_prefix_overrides_tier_default(tmp_path):
    (tmp_path / "guides").mkdir()
    (tmp_path / "guides" / "mix.md").write_text(
        """# mix

## RULES

- SHOULD prefer dataclasses.
- MAY use protocols.
- (no prefix) avoid global state.
"""
    )
    docs = await _adapter(tmp_path).fetch({"type": "guides"}, {})
    sevs = [d.severity for d in docs if d.kind == "rule"]
    # RULES tier defaults to `may`; bullet-level prefix wins when present.
    assert sevs == ["should", "may", "may"]
    texts = [d.text for d in docs if d.kind == "rule"]
    assert texts == [
        "prefer dataclasses.",
        "use protocols.",
        "(no prefix) avoid global state.",
    ]


async def test_guides_new_tier_names_recognized(tmp_path):
    (tmp_path / "guides").mkdir()
    (tmp_path / "guides" / "new.md").write_text(
        """# new

## NON-NEGOTIABLE

**Never push directly to main.**

## STRONG

- Run sensors before commit.

## RULES

- Prefer dataclasses.
"""
    )
    docs = await _adapter(tmp_path).fetch({"type": "guides"}, {})
    by_sev = {}
    for d in docs:
        if d.kind == "rule":
            by_sev.setdefault(d.severity, []).append(d.text)
    assert any("Never push" in t for t in by_sev["must"])
    assert any("Run sensors" in t for t in by_sev["should"])
    assert any("Prefer dataclasses" in t for t in by_sev["may"])


async def test_guides_skips_readme(tmp_path):
    _build_min_harness(tmp_path)
    docs = await _adapter(tmp_path).fetch({"type": "guides"}, {})
    sources = {d.source for d in docs}
    assert all("README.md" not in s for s in sources)


async def test_guides_ignores_unknown_h2_sections(tmp_path):
    (tmp_path / "guides").mkdir()
    (tmp_path / "guides" / "x.md").write_text(
        """# x

## Background

Just prose, not a constraint.

## RULES

- MUST do X.
"""
    )
    docs = await _adapter(tmp_path).fetch({"type": "guides"}, {})
    assert [d.kind for d in docs] == ["rule"]
    assert docs[0].text == "do X."


async def test_guides_source_uri_includes_section_slug(tmp_path):
    _build_min_harness(tmp_path)
    docs = await _adapter(tmp_path).fetch({"type": "guides"}, {})
    iron = next(d for d in docs if "NEVER PERFORM" in d.text)
    assert iron.source.endswith("#iron-law")
    assert "guides/process/dangerous-actions.md" in iron.source


async def test_guides_rule_id_includes_file_section_index(tmp_path):
    _build_min_harness(tmp_path)
    docs = await _adapter(tmp_path).fetch({"type": "guides"}, {})
    first_rule = next(d for d in docs if "Show, then confirm" in d.text)
    # File stem slug: guides-process-dangerous-actions; section slug: rules
    assert first_rule.id.startswith("guides-process-dangerous-actions-rules-")


async def test_corpus_emits_one_reasoning_per_file(tmp_path):
    _build_min_harness(tmp_path)
    docs = await _adapter(tmp_path).fetch({"type": "corpus"}, {})
    assert len(docs) == 1
    assert docs[0].kind == "reasoning"
    assert "context broker" in docs[0].text
    assert docs[0].source == "harness://corpus/architecture.md"


async def test_actions_query_type_removed(tmp_path):
    _build_min_harness(tmp_path)
    with pytest.raises(AdapterError, match="unknown query.type"):
        await _adapter(tmp_path).fetch({"type": "actions"}, {})


async def test_playbooks_query_type_removed(tmp_path):
    _build_min_harness(tmp_path)
    with pytest.raises(AdapterError, match="unknown query.type"):
        await _adapter(tmp_path).fetch({"type": "playbooks"}, {})


async def test_sensors_emit_commands_with_script_invocation(tmp_path):
    _build_min_harness(tmp_path)
    docs = await _adapter(tmp_path).fetch({"type": "sensors"}, {})
    assert [d.kind for d in docs] == ["command"]
    assert docs[0].name == "build"
    # The fixture sensor has frontmatter `kind: computational` but no script
    # field, so invocation is empty.
    assert docs[0].invocation == ""
    assert "build / compile / package" in docs[0].text


async def test_sensors_pulls_invocation_from_frontmatter(tmp_path):
    (tmp_path / "sensors").mkdir()
    (tmp_path / "sensors" / "lint.md").write_text(
        """---
kind: lint
script: lint.sh
---

# Sensor: lint

Static check.
"""
    )
    docs = await _adapter(tmp_path).fetch({"type": "sensors"}, {})
    assert len(docs) == 1
    assert docs[0].kind == "command"
    assert docs[0].invocation == ".keystone/harness/scripts/lint.sh"


async def test_unknown_query_type_raises(tmp_path):
    with pytest.raises(AdapterError, match="unknown query.type"):
        await _adapter(tmp_path).fetch({"type": "bogus"}, {})


async def test_missing_query_type_raises(tmp_path):
    with pytest.raises(AdapterError, match="query.type is required"):
        await _adapter(tmp_path).fetch({}, {})


async def test_missing_subdir_returns_empty(tmp_path):
    # Empty harness root, no guides/ dir at all.
    docs = await _adapter(tmp_path).fetch({"type": "guides"}, {})
    assert docs == []


async def test_empty_file_yields_no_docs(tmp_path):
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "blank.md").write_text("   \n  \n")
    docs = await _adapter(tmp_path).fetch({"type": "corpus"}, {})
    assert docs == []


async def test_health_reports_present_subdirs(tmp_path):
    _build_min_harness(tmp_path)
    h = await _adapter(tmp_path).health()
    assert h["ok"] is True
    assert set(h["subdirs_present"]) == {
        "guides", "corpus", "sensors", "skills"
    }


async def test_health_fails_when_root_missing(tmp_path):
    a = HarnessAdapter(root=tmp_path / "nope")
    h = await a.health()
    assert h["ok"] is False
