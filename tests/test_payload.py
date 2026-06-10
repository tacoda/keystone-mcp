from keystone_mcp.payload import Rule, merge_rules


def _r(text: str, severity: str = "must", source: str = "a") -> Rule:
    return Rule(text=text, source=source, severity=severity)  # type: ignore[arg-type]


def test_dedup_identical_normalized_text_keeps_highest_severity():
    rules = [
        _r("Must pass CI.", severity="should", source="docs"),
        _r("must pass CI.", severity="must", source="github"),
    ]
    out = merge_rules(rules)
    assert len(out) == 1
    assert out[0].severity == "must"
    assert out[0].source == "github"


def test_tie_at_top_severity_keeps_both():
    rules = [
        _r("Must pass CI.", severity="must", source="docs"),
        _r("must pass ci", severity="must", source="github"),
    ]
    out = merge_rules(rules)
    assert len(out) == 2
    sources = {r.source for r in out}
    assert sources == {"docs", "github"}


def test_distinct_text_passes_through():
    rules = [
        _r("Run linters.", severity="should", source="docs"),
        _r("Two approvals required.", severity="must", source="github"),
    ]
    out = merge_rules(rules)
    assert len(out) == 2


def test_loser_below_winner_dropped():
    rules = [
        _r("X.", severity="may", source="a"),
        _r("X.", severity="must", source="b"),
        _r("X.", severity="should", source="c"),
    ]
    out = merge_rules(rules)
    assert len(out) == 1
    assert out[0].source == "b"


def test_preserves_first_occurrence_order():
    rules = [
        _r("alpha.", severity="must", source="a"),
        _r("beta.", severity="must", source="a"),
        _r("alpha.", severity="should", source="b"),  # dropped, lower
    ]
    out = merge_rules(rules)
    assert [r.text for r in out] == ["alpha.", "beta."]
