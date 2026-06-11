"""Phase 20 — cascade engine.

Verifies the precedence + canonical/required semantics in
`keystone_mcp.cascade.resolve`.
"""

from __future__ import annotations

from keystone_mcp.cascade import (
    PROJECT_LAYER,
    Item,
    resolve,
)


def test_resolve_specific_beats_broad():
    # Two non-canonical declarations of the same guide. Project (deeper)
    # wins by default; external source is recorded as overridden.
    layers = [
        [Item(layer="org-standards", port="guides", name="release-policy")],
        [Item(layer=PROJECT_LAYER, port="guides", name="release-policy")],
    ]
    report = resolve(layers)
    assert len(report.resolved) == 1
    winner = report.resolved[0]
    assert winner.winning_layer == PROJECT_LAYER
    assert winner.canonical is False
    assert report.conflicts
    assert report.conflicts[0].overridden_layers == ("org-standards",)


def test_resolve_single_source_no_conflict():
    layers = [
        [Item(layer="org-standards", port="guides", name="release-policy")],
    ]
    report = resolve(layers)
    assert len(report.resolved) == 1
    assert report.conflicts == ()


def test_canonical_lock_shadows_deeper_project_item():
    # Org declares release-policy canonical. The project ships a file of
    # the same name; the cascade engine refuses to load it, surfaces it
    # as unreachable, and the user can rename or relocate.
    layers = [
        [
            Item(
                layer="org-standards",
                port="guides",
                name="release-policy",
                canonical=True,
            )
        ],
        [
            Item(
                layer=PROJECT_LAYER,
                port="guides",
                name="release-policy",
            )
        ],
    ]
    project_paths = {
        ("guides", "release-policy"): "/p/.keystone/harness/guides/release-policy.md",
    }
    report = resolve(layers, project_paths=project_paths)
    assert len(report.resolved) == 1
    winner = report.resolved[0]
    assert winner.winning_layer == "org-standards"
    assert winner.canonical is True
    assert len(report.unreachable) == 1
    skip = report.unreachable[0]
    assert skip.shadowing_layer == "org-standards"
    assert skip.project_layer_path.endswith("release-policy.md")
    # And it is NOT in conflicts — unreachable items don't generate
    # override notices.
    assert report.conflicts == ()


def test_canonical_lock_shadows_deeper_external_source_as_violation():
    # Two external sources both declare the same item, the upstream one
    # canonical. The downstream override is a violation.
    layers = [
        [
            Item(
                layer="org-standards",
                port="guides",
                name="release-policy",
                canonical=True,
            )
        ],
        [Item(layer="team-extras", port="guides", name="release-policy")],
        [Item(layer=PROJECT_LAYER, port="guides", name="other")],
    ]
    report = resolve(layers)
    assert len(report.canonical_violations) == 1
    v = report.canonical_violations[0]
    assert v.locked_at_layer == "org-standards"
    assert v.violating_layer == "team-extras"


def test_required_gap_when_no_body_provided():
    # Org references release-notes but does not ship one. No deeper
    # layer fulfills the requirement.
    layers = [
        [
            Item(
                layer="org-standards",
                port="actions",
                name="release-notes",
                has_body=False,
            )
        ],
    ]
    report = resolve(layers)
    assert report.resolved == ()
    assert len(report.required_gaps) == 1
    gap = report.required_gaps[0]
    assert gap.declared_by_layer == "org-standards"
    assert gap.port == "actions"
    assert gap.name == "release-notes"


def test_required_satisfied_by_deeper_layer():
    layers = [
        [
            Item(
                layer="org-standards",
                port="actions",
                name="release-notes",
                has_body=False,
            )
        ],
        [
            Item(
                layer=PROJECT_LAYER,
                port="actions",
                name="release-notes",
                has_body=True,
            )
        ],
    ]
    report = resolve(layers)
    assert report.required_gaps == ()
    assert len(report.resolved) == 1
    assert report.resolved[0].winning_layer == PROJECT_LAYER


def test_canonical_without_body_surfaces_as_gap():
    # Canonical declaration that bears no body locks the item but
    # supplies nothing — by construction this is unreachable; cascade
    # reports a `required_gap` so the user notices.
    layers = [
        [
            Item(
                layer="org-standards",
                port="actions",
                name="release-notes",
                has_body=False,
                canonical=True,
            )
        ],
    ]
    report = resolve(layers)
    assert report.resolved == ()
    assert len(report.required_gaps) == 1


def test_to_dict_is_serializable():
    report = resolve(
        [
            [Item(layer="org-standards", port="guides", name="r")],
            [Item(layer=PROJECT_LAYER, port="guides", name="r")],
        ]
    )
    payload = report.to_dict()
    assert payload["resolved"][0]["winning_layer"] == PROJECT_LAYER
    assert payload["conflicts"][0]["overridden_layers"] == ("org-standards",)
