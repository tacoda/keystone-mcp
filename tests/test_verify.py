"""Phase 20 — verify + doctor wiring.

Drives `keystone_mcp.verify.run_verify` / `run_doctor` against a
freshly-bootstrapped harness with synthetic external sources.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from keystone_mcp.config import KeystoneConfig, SourceConfig
from keystone_mcp.harness_scaffold import Scaffold
from keystone_mcp.verify import run_doctor, run_verify


def _config(**sources: SourceConfig) -> KeystoneConfig:
    return KeystoneConfig(sources=dict(sources), topics={})


def _seed_harness(tmp_path: Path) -> Scaffold:
    s = Scaffold(tmp_path / "harness")
    s.bootstrap(materialize_templates=True)
    return s


def test_verify_with_no_external_sources_returns_only_project_items(tmp_path):
    s = _seed_harness(tmp_path)
    payload = run_verify(s.root, _config())
    assert payload["summary"]["resolved"] > 0
    assert payload["summary"]["canonical_violations"] == 0
    assert payload["summary"]["required_gaps"] == 0
    assert payload["summary"]["unreachable"] == 0
    # Every winner should be the project layer when no external source
    # declares anything.
    for r in payload["cascade"]["resolved"]:
        assert r["winning_layer"] == "<project>"


def test_verify_canonical_lock_marks_project_file_unreachable(tmp_path):
    s = _seed_harness(tmp_path)
    # The project layer ships a `code-review` sensor by default.
    src = SourceConfig(
        name="org-standards",
        type="markdown",
        settings={"root": "/tmp/x"},
        canonical={"sensors": ("code-review",)},
    )
    payload = run_verify(s.root, _config(**{"org-standards": src}))
    assert payload["summary"]["unreachable"] == 1
    unreachable = payload["cascade"]["unreachable"][0]
    assert unreachable["port"] == "sensors"
    assert unreachable["name"] == "code-review"
    assert unreachable["shadowing_layer"] == "org-standards"
    assert "sensors/code-review.md" in unreachable["project_layer_path"]


def test_verify_required_gap_surfaces_when_no_layer_supplies_item(tmp_path):
    s = _seed_harness(tmp_path)
    # Project does not ship a `release-notes` action by default.
    src = SourceConfig(
        name="org-standards",
        type="markdown",
        settings={"root": "/tmp/x"},
        required={"actions": ("release-notes",)},
    )
    payload = run_verify(s.root, _config(**{"org-standards": src}))
    assert payload["summary"]["required_gaps"] == 1
    gap = payload["cascade"]["required_gaps"][0]
    assert gap["port"] == "actions"
    assert gap["name"] == "release-notes"


def test_verify_required_gap_closes_when_project_supplies_item(tmp_path):
    s = _seed_harness(tmp_path)
    # Add a project-layer `release-notes` action that fulfills the
    # external source's `required:` declaration.
    s.new_action("release-notes")
    src = SourceConfig(
        name="org-standards",
        type="markdown",
        settings={"root": "/tmp/x"},
        required={"actions": ("release-notes",)},
    )
    payload = run_verify(s.root, _config(**{"org-standards": src}))
    assert payload["summary"]["required_gaps"] == 0


def test_doctor_path_conformance_flags_missing_bootstrap_dirs(tmp_path):
    s = Scaffold(tmp_path / "harness")
    # No bootstrap call — everything is missing.
    s.root.mkdir(parents=True)
    payload = run_doctor(s.root, _config())
    assert payload["path_conformance"]["ok"] is False
    missing = payload["path_conformance"]["missing_bootstrap_dirs"]
    assert "guides" in missing
    assert "playbooks" in missing


def test_doctor_budget_proxy_reports_word_counts(tmp_path):
    s = _seed_harness(tmp_path)
    payload = run_doctor(s.root, _config())
    budget = payload["budget_proxy"]
    assert budget["total_words"] > 0
    assert "guides" in budget["per_port"]
    assert budget["per_port"]["sensors"]["files"] > 0


def test_doctor_sensor_health_clean_when_all_match(tmp_path):
    s = _seed_harness(tmp_path)
    payload = run_doctor(s.root, _config())
    health = payload["sensor_health"]
    # All shipped sensors have a matching implementation.
    assert health["missing_implementation"] == []
    assert health["ok"] is True


def test_doctor_sensor_health_flags_missing_implementation(tmp_path):
    s = _seed_harness(tmp_path)
    # Drop a sensor declaration with no script and no prompt.
    (s.root / "sensors" / "orphaned.md").write_text(
        "---\nkind: custom\n---\n\n# orphaned\n"
    )
    payload = run_doctor(s.root, _config())
    health = payload["sensor_health"]
    assert "orphaned" in health["missing_implementation"]
    assert health["ok"] is False


def test_doctor_sensor_health_flags_ambiguous(tmp_path):
    s = _seed_harness(tmp_path)
    # Add both a script and a prompt for the same sensor name.
    (s.root / "sensors" / "double.md").write_text(
        "---\nkind: custom\n---\n\n# double\n"
    )
    (s.root / "scripts" / "double.sh").write_text("#!/bin/sh\nexit 0\n")
    (s.root / "prompts" / "double.md").write_text("# double\n")
    payload = run_doctor(s.root, _config())
    health = payload["sensor_health"]
    assert "double" in health["ambiguous"]
    assert health["ok"] is False


def test_doctor_sensor_health_flags_orphan_implementations(tmp_path):
    s = _seed_harness(tmp_path)
    # Script + prompt with no matching sensor declaration.
    (s.root / "scripts" / "no-sensor.sh").write_text(
        "#!/bin/sh\nexit 0\n"
    )
    (s.root / "prompts" / "stranded.md").write_text("# stranded\n")
    payload = run_doctor(s.root, _config())
    health = payload["sensor_health"]
    assert "no-sensor" in health["orphan_scripts"]
    assert "stranded" in health["orphan_prompts"]


def test_verify_reports_serializable_to_json(tmp_path):
    import json

    s = _seed_harness(tmp_path)
    payload = run_verify(s.root, _config())
    # Must round-trip through JSON without raising.
    json.dumps(payload)
