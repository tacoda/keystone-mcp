"""Unit tests for the shared classifier primitives.

Each heading-based adapter (markdown, confluence, notion) has its own
integration tests; this file exercises `classify_sections` directly against
constructed `Section` objects so the contract is locked in independently of
any one adapter's parser.
"""

import pytest

from keystone_mcp.adapters._classify import (
    Section,
    SubBlock,
    classify_sections,
    headings_of,
    severity_default,
    slugify,
)
from keystone_mcp.errors import AdapterError


def test_slugify_collapses_punctuation_and_lowercases():
    assert slugify("Hello World!") == "hello-world"
    assert slugify("  Multi   word  ") == "multi-word"
    assert slugify("!!!") == "section"
    assert slugify("") == "section"


def test_headings_of_accepts_string_or_list():
    assert headings_of("x", {"heading": "Foo"}) == {"foo"}
    assert headings_of("x", {"heading": ["Foo", "Bar"]}) == {"foo", "bar"}
    assert headings_of("x", {}) == set()
    assert headings_of("x", None) == set()


def test_headings_of_rejects_invalid_type():
    with pytest.raises(AdapterError, match="must be string or list"):
        headings_of("x", {"heading": 42})


def test_severity_default_returns_must_without_classify():
    assert severity_default("x", {}) == "must"


def test_severity_default_honors_override():
    assert severity_default("x", {"rules": {"severity": "should"}}) == "should"


def test_severity_default_rejects_invalid():
    with pytest.raises(AdapterError, match="must\\|should\\|may"):
        severity_default("x", {"rules": {"severity": "ghost"}})


def _section(
    heading: str,
    *,
    bullets: list[str] | None = None,
    sub_blocks: list[SubBlock] | None = None,
    body: str = "",
) -> Section:
    return Section(
        heading=heading,
        bullets=bullets or [],
        sub_blocks=sub_blocks or [],
        body=body,
    )


def test_classify_rules_emits_one_per_bullet_with_severity_prefix():
    sections = [
        _section(
            "Rules",
            bullets=["MUST pass CI.", "SHOULD lint.", "Review the diff."],
        )
    ]
    docs = classify_sections(
        sections=sections,
        source_base="x://1",
        classify={"rules": {"heading": "Rules"}},
        adapter_name="test",
    )
    assert [d.text for d in docs] == ["pass CI.", "lint.", "Review the diff."]
    assert [d.severity for d in docs] == ["must", "should", "must"]
    assert docs[0].source == "x://1#rules"
    assert docs[0].id == "rules-001"
    assert docs[2].id == "rules-003"


def test_classify_rules_skips_blank_bullets():
    sections = [_section("Rules", bullets=["  ", "MUST X."])]
    docs = classify_sections(
        sections=sections,
        source_base="x://1",
        classify={"rules": {"heading": "Rules"}},
        adapter_name="t",
    )
    assert [d.text for d in docs] == ["X."]
    assert docs[0].id == "rules-001"


def test_classify_rules_default_severity_override():
    sections = [_section("Standards", bullets=["use dataclasses."])]
    docs = classify_sections(
        sections=sections,
        source_base="x://1",
        classify={"rules": {"heading": "Standards", "severity": "should"}},
        adapter_name="t",
    )
    assert docs[0].severity == "should"


def test_classify_reasoning_collapses_section_body_to_one_doc():
    sections = [_section("Background", body="line one\n\nline two")]
    docs = classify_sections(
        sections=sections,
        source_base="x://1",
        classify={"reasoning": {"heading": "Background"}},
        adapter_name="t",
    )
    assert len(docs) == 1
    assert docs[0].kind == "reasoning"
    assert "line one" in docs[0].text
    assert docs[0].source == "x://1#background"


def test_classify_reasoning_empty_body_emits_nothing():
    sections = [_section("Background", body="   ")]
    docs = classify_sections(
        sections=sections,
        source_base="x://1",
        classify={"reasoning": {"heading": "Background"}},
        adapter_name="t",
    )
    assert docs == []


def test_classify_skills_one_per_sub_block():
    sections = [
        _section(
            "Procedures",
            sub_blocks=[
                SubBlock(name="Cut release", body="bump, tag, push"),
                SubBlock(name="Roll back", body="revert, redeploy"),
            ],
        )
    ]
    docs = classify_sections(
        sections=sections,
        source_base="x://1",
        classify={"skills": {"heading": "Procedures"}},
        adapter_name="t",
    )
    assert [d.kind for d in docs] == ["skill", "skill"]
    assert [d.name for d in docs] == ["Cut release", "Roll back"]
    assert docs[0].source == "x://1#procedures/cut-release"
    assert docs[0].id == "procedures-001"
    assert docs[1].id == "procedures-002"


def test_classify_commands_uses_subblock_code_as_invocation():
    sections = [
        _section(
            "Commands",
            sub_blocks=[
                SubBlock(name="deploy", body="Run after CI is green.", code="./deploy.sh"),
                SubBlock(name="rollback", body="", code="./rollback.sh"),
            ],
        )
    ]
    docs = classify_sections(
        sections=sections,
        source_base="x://1",
        classify={"commands": {"heading": "Commands"}},
        adapter_name="t",
    )
    assert [d.kind for d in docs] == ["command", "command"]
    assert [c.invocation for c in docs] == ["./deploy.sh", "./rollback.sh"]
    assert "CI is green" in docs[0].text
    assert docs[1].text == ""
    assert docs[0].source == "x://1#commands/deploy"


def test_classify_heading_list_matches_any_member():
    sections = [
        _section("Constraints", bullets=["MUST X."]),
        _section("Requirements", bullets=["MUST Y."]),
    ]
    docs = classify_sections(
        sections=sections,
        source_base="x://1",
        classify={"rules": {"heading": ["Constraints", "Requirements"]}},
        adapter_name="t",
    )
    assert [d.text for d in docs] == ["X.", "Y."]
    assert {d.source for d in docs} == {
        "x://1#constraints",
        "x://1#requirements",
    }


def test_classify_reasoning_all_picks_up_unmatched_sections():
    sections = [
        _section("Rules", bullets=["MUST X."]),
        _section("Background", body="some background."),
        _section("Notes", body="extra notes."),
    ]
    docs = classify_sections(
        sections=sections,
        source_base="x://1",
        classify={
            "rules": {"heading": "Rules"},
            "reasoning": {"all": True},
        },
        adapter_name="t",
    )
    kinds = [d.kind for d in docs]
    assert kinds.count("rule") == 1
    assert kinds.count("reasoning") == 2


def test_classify_fallback_emits_whole_body_as_reasoning_when_nothing_configured():
    docs = classify_sections(
        sections=[],
        source_base="x://1",
        classify={},
        adapter_name="t",
        fallback_reasoning_body="freeform body.",
    )
    assert len(docs) == 1
    assert docs[0].kind == "reasoning"
    assert docs[0].text == "freeform body."
    assert docs[0].source == "x://1"  # no fragment in the fallback path


def test_classify_fallback_empty_body_emits_nothing():
    docs = classify_sections(
        sections=[],
        source_base="x://1",
        classify={},
        adapter_name="t",
        fallback_reasoning_body="   ",
    )
    assert docs == []


def test_classify_section_with_no_matching_kind_is_skipped():
    sections = [
        _section("Rules", bullets=["MUST X."]),
        _section("Unrelated", body="ignored body."),
    ]
    docs = classify_sections(
        sections=sections,
        source_base="x://1",
        classify={"rules": {"heading": "Rules"}},
        adapter_name="t",
    )
    assert [d.kind for d in docs] == ["rule"]


def test_classify_severity_prefix_with_newline_in_body_preserved():
    sections = [_section("Rules", bullets=["MUST do X.\nThen do Y."])]
    docs = classify_sections(
        sections=sections,
        source_base="x://1",
        classify={"rules": {"heading": "Rules"}},
        adapter_name="t",
    )
    assert docs[0].severity == "must"
    assert docs[0].text.startswith("do X.")
    assert "Then do Y." in docs[0].text
