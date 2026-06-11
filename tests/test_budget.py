"""Phase 27 — ambient-load budget reporter."""

from __future__ import annotations

from pathlib import Path

import pytest

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
    # Hot files are sorted by tokens (the metric the budget reports
    # on), not by word count. Word count tracks tokens but isn't
    # monotonically equal.
    token_counts = [f["tokens"] for f in report["hot_files"]]
    assert token_counts == sorted(token_counts, reverse=True)
    assert len(token_counts) <= 5


def test_budget_report_tokens_consistent_with_active_tokenizer(tmp_path):
    s = _harness(tmp_path)
    report = budget_report(s.root)
    for port in report["per_port"].values():
        if port["words"] == 0:
            assert port["tokens"] == 0
            continue
        ratio = port["tokens"] / port["words"]
        # Word-count proxy: 0.75 words/token → tokens ≈ words * 1.33.
        # tiktoken-cl100k-base on English markdown: similar order of
        # magnitude. Either way the ratio sits comfortably in this
        # band.
        assert 0.5 < ratio < 3.0, ratio
    # `approx_tokens` is preserved as an alias for `tokens`.
    for port in report["per_port"].values():
        assert port["approx_tokens"] == port["tokens"]


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


def test_budget_report_reports_active_tokenizer(tmp_path):
    s = _harness(tmp_path)
    report = budget_report(s.root)
    assert report["tokenizer"] in {"word_count", "tiktoken-cl100k-base"}


def test_budget_report_uses_tiktoken_when_available(tmp_path):
    pytest.importorskip("tiktoken")
    s = _harness(tmp_path)
    report = budget_report(s.root)
    assert report["tokenizer"] == "tiktoken-cl100k-base"
    # tiktoken counts must populate the new `tokens` field.
    assert report["totals"]["tokens"] > 0


def test_budget_report_falls_back_to_word_count(monkeypatch, tmp_path):
    # Simulate `tiktoken` not being installed by stubbing the import.
    import sys

    monkeypatch.setitem(sys.modules, "tiktoken", None)
    s = _harness(tmp_path)
    report = budget_report(s.root)
    assert report["tokenizer"] == "word_count"


def test_budget_report_serializable_to_json(tmp_path):
    import json

    s = _harness(tmp_path)
    report = budget_report(s.root)
    json.dumps(report)
