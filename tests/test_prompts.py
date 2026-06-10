from keystone_mcp.prompts import (
    render_audit,
    render_bootstrap,
    render_learn,
    render_task,
)


def test_bootstrap_mentions_state_ledger_paths():
    out = render_bootstrap()
    assert "# Bootstrap workflow" in out
    assert "CODEBASE_STATE.md" in out
    assert "code-debt.md" in out
    assert "risk-fingerprints.md" in out
    assert "traffic-topology.md" in out


def test_bootstrap_references_mcp_tools_and_resources():
    out = render_bootstrap()
    assert "harness_bootstrap" in out
    assert "harness://status" in out
    assert "context://list" in out
    assert "harness_new_guide" in out
    assert "harness_new_skill" in out


def test_bootstrap_includes_no_secrets_iron_law():
    out = render_bootstrap()
    assert "No secrets" in out
    assert "env:VAR" in out


def test_task_substitutes_description():
    out = render_task("Add SSO login")
    assert "> Add SSO login" in out


def test_task_lists_canonical_phases_in_order():
    out = render_task("x")
    # Phases must appear in this order.
    phases = ["spec", "orient", "load rules", "implement", "check-drift", "verify", "review", "learn"]
    positions = [out.find(p) for p in phases]
    assert all(p > 0 for p in positions), positions
    assert positions == sorted(positions)


def test_task_iron_laws_cover_acceptance_verification_no_force_commit():
    out = render_task("x")
    assert "acceptance criteria" in out
    assert "verification evidence" in out
    assert "No commits with failing sensors" in out
    assert "No AI attribution" in out


def test_audit_lists_both_flywheels():
    out = render_audit()
    assert "Learning flywheel" in out
    assert "Pruning flywheel" in out


def test_audit_enumerates_pruning_categories():
    out = render_audit()
    for category in (
        "Stale rules",
        "Dead idioms",
        "Placeholders",
        "Failing sensors",
        "Empty shells",
        "Drifted state",
    ):
        assert category in out


def test_audit_warns_against_silent_overwrites():
    out = render_audit()
    assert "do not silently overwrite" in out.lower() or "Propose every state-file diff" in out


def test_learn_substitutes_finding():
    out = render_learn("PRs to main require two approvers — caught on PR #420")
    assert "PR #420" in out


def test_learn_enumerates_classification_buckets():
    out = render_learn("x")
    assert "Iron law" in out
    assert "Skill" in out
    assert "Reasoning" in out


def test_learn_documents_inbox_path():
    out = render_learn("x")
    assert ".keystone/harness/learning/inbox/" in out


def test_learn_warns_against_secrets_and_invented_evidence():
    out = render_learn("x")
    assert "No invented evidence" in out
    assert "No secrets" in out
