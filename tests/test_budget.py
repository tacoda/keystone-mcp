"""Phase 27 — ambient-load budget reporter."""

from __future__ import annotations

from pathlib import Path

from keystone_mcp.budget import budget_report
from keystone_mcp.cascade import Item, PROJECT_LAYER, resolve
from keystone_mcp.harness_scaffold import Scaffold


def _harness(tmp_path: Path) -> Scaffold:
    s = Scaffold(tmp_path / "harness")
    s.bootstrap(materialize_templates=True)
    return s


def test_budget_report_totals_match_per_port_sum(tmp_path):
    s = _harness(tmp_path)
    report = budget_report(s.root)
    total = report["totals"]["words"]
    port_sum = sum(p["words"] for p in report["per_port"].values())
    assert total == port_sum


def test_budget_report_hot_files_sorted_desc(tmp_path):
    s = _harness(tmp_path)
    report = budget_report(s.root, top_n=5)
    counts = [f["words"] for f in report["hot_files"]]
    assert counts == sorted(counts, reverse=True)
    assert len(counts) <= 5


def test_budget_report_approx_tokens_uses_consistent_multiplier(tmp_path):
    s = _harness(tmp_path)
    report = budget_report(s.root)
    for port in report["per_port"].values():
        # 0.75 words/token → tokens = words / 0.75
        assert port["approx_tokens"] == int(port["words"] / 0.75)


def test_budget_report_cascade_excluded_counts_unreachable(tmp_path):
    s = _harness(tmp_path)
    # Synthesize a cascade where the project's shipped `code-review`
    # sensor is shadowed by an upstream canonical lock.
    cascade = resolve(
        [
            [
                Item(
                    layer="org",
                    port="sensors",
                    name="code-review",
                    canonical=True,
                )
            ],
            [
                Item(
                    layer=PROJECT_LAYER,
                    port="sensors",
                    name="code-review",
                )
            ],
        ],
        project_paths={
            ("sensors", "code-review"): str(
                s.root / "sensors" / "code-review.md"
            )
        },
    )
    report = budget_report(s.root, cascade=cascade)
    assert report["cascade_excluded"]["files"] == 1
    assert report["cascade_excluded"]["words"] > 0


def test_budget_report_serializable_to_json(tmp_path):
    import json

    s = _harness(tmp_path)
    report = budget_report(s.root)
    json.dumps(report)
