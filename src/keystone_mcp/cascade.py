"""Phase 20 — cascade engine.

Layered resolution of harness items (guides, actions, playbooks,
sensors, skills, …) across:

  1. External sources declared in `.keystone/context.yaml`
     (broad → specific, in declaration order).
  2. The project's own `.keystone/harness/` layer (most specific).

The engine never fetches content. It takes pre-collected declarations
from each layer and produces:

  * `resolved` — for each `(port, item)` reachable to the agent, which
    layer wins and why.
  * `unreachable` — items shadowed by a canonical lock upstream. The
    project file is NEVER loaded into ambient context; no tokens spent,
    no conflict guidance.
  * `canonical_violations` — items declared `canonical` at one layer
    that a deeper layer attempted to redefine. Surfaced so the user can
    rename or relocate the conflicting file.
  * `required_gaps` — items declared `required` (referenced but not
    shipped) by some source that no deeper layer fulfills.
  * `conflicts` — non-canonical items present at the project layer AND
    at one or more external layers. The project wins by default
    ("specific beats broad"); the audit log surfaces the override so
    the user can decide whether the project layer is intentional.

Inputs are intentionally simple — plain tuples — so the function is
trivially testable in isolation. Callers build `Item` tuples from
whatever the actual source layout looks like (markdown files, YAML
manifests, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


# Identifier for the project's own harness layer. Reserved name; no
# external source may use this string for its layer.
PROJECT_LAYER = "<project>"


@dataclass(frozen=True)
class Item:
    """One declared harness item at one layer.

    `layer` is the source name (or `PROJECT_LAYER` for the project's own
    harness). `port` is the directory bucket (`guides`, `actions`,
    `playbooks`, `sensors`, `skills`, `corpus`, …). `name` is the bare
    item name without extension.

    `has_body=True` means the layer actually ships the item content.
    `has_body=False` is used for `required` declarations: the source
    references the item but does not provide a body — a deeper layer
    must supply it.

    `canonical=True` means this layer claims exclusive ownership of the
    item; no deeper layer may override.
    """

    layer: str
    port: str
    name: str
    has_body: bool = True
    canonical: bool = False


@dataclass(frozen=True)
class Resolved:
    """The winning layer for one `(port, name)` pair."""

    port: str
    name: str
    winning_layer: str
    canonical: bool


@dataclass(frozen=True)
class Unreachable:
    """A project-layer item shadowed by a canonical declaration upstream.

    The project file is never loaded; the user is told why so they can
    delete it, move it under a different name, or relocate it under a
    non-canonical namespace.
    """

    port: str
    name: str
    shadowing_layer: str
    project_layer_path: str


@dataclass(frozen=True)
class CanonicalViolation:
    """Two layers both claim canonical ownership of the same item, or a
    deeper non-canonical layer attempted to override a canonical lock."""

    port: str
    name: str
    locked_at_layer: str
    violating_layer: str


@dataclass(frozen=True)
class RequiredGap:
    """An item declared `required` by some source but never supplied."""

    port: str
    name: str
    declared_by_layer: str


@dataclass(frozen=True)
class Conflict:
    """Non-canonical override: the project layer shadows an external
    source's item. The project wins by default; this entry surfaces it
    for the audit log."""

    port: str
    name: str
    overridden_layers: tuple[str, ...]


@dataclass(frozen=True)
class CascadeReport:
    """Result of one cascade resolution pass."""

    resolved: tuple[Resolved, ...]
    unreachable: tuple[Unreachable, ...] = ()
    canonical_violations: tuple[CanonicalViolation, ...] = ()
    required_gaps: tuple[RequiredGap, ...] = ()
    conflicts: tuple[Conflict, ...] = ()

    def to_dict(self) -> dict:
        def _dump(items):
            return [item.__dict__ for item in items]

        return {
            "resolved": _dump(self.resolved),
            "unreachable": _dump(self.unreachable),
            "canonical_violations": _dump(self.canonical_violations),
            "required_gaps": _dump(self.required_gaps),
            "conflicts": _dump(self.conflicts),
        }


def resolve(
    layers: Iterable[Iterable[Item]],
    *,
    project_paths: dict[tuple[str, str], str] | None = None,
) -> CascadeReport:
    """Resolve the cascade across `layers`.

    `layers` is an ordered iterable, broad → specific. Each entry is an
    iterable of `Item` declarations from that layer. The project layer
    must use `layer=PROJECT_LAYER` and should be the LAST entry (most
    specific). External sources earlier in the order are progressively
    less specific.

    `project_paths` maps `(port, name)` → on-disk path for any item
    declared at the project layer. Used to produce a helpful
    `Unreachable.project_layer_path` so the user can locate the file
    they need to rename/relocate.

    Precedence:

      1. A canonical declaration at any layer locks the item at that
         layer. No deeper layer may override; if one tries, the result
         is a `CanonicalViolation`. The project file (if any) is
         reported in `unreachable` and never loaded.
      2. Among non-canonical declarations, specific beats broad: the
         deepest layer with `has_body=True` wins.
      3. A `required` declaration (has_body=False) consumes nothing on
         its own. If no deeper layer fulfills it, the cascade emits a
         `RequiredGap`.
    """
    project_paths = project_paths or {}
    materialized: list[tuple[int, Item]] = []
    for depth, layer_items in enumerate(layers):
        for item in layer_items:
            materialized.append((depth, item))

    # Group declarations by (port, name).
    by_key: dict[tuple[str, str], list[tuple[int, Item]]] = {}
    for depth, item in materialized:
        by_key.setdefault((item.port, item.name), []).append((depth, item))

    resolved: list[Resolved] = []
    unreachable: list[Unreachable] = []
    canonical_violations: list[CanonicalViolation] = []
    required_gaps: list[RequiredGap] = []
    conflicts: list[Conflict] = []

    for (port, name), declarations in by_key.items():
        declarations.sort(key=lambda d: d[0])  # broad → specific
        canonical_decls = [
            (depth, item) for depth, item in declarations if item.canonical
        ]
        if canonical_decls:
            # First canonical declaration wins; later layers that also
            # claim canonical or try to redefine the item are violations.
            lock_depth, lock_item = canonical_decls[0]
            for depth, item in canonical_decls[1:]:
                canonical_violations.append(
                    CanonicalViolation(
                        port=port,
                        name=name,
                        locked_at_layer=lock_item.layer,
                        violating_layer=item.layer,
                    )
                )
            for depth, item in declarations:
                if depth <= lock_depth:
                    continue
                if item.canonical:
                    continue  # already recorded above
                # Deeper non-canonical decl is shadowed by the lock.
                if item.layer == PROJECT_LAYER:
                    unreachable.append(
                        Unreachable(
                            port=port,
                            name=name,
                            shadowing_layer=lock_item.layer,
                            project_layer_path=project_paths.get(
                                (port, name), ""
                            ),
                        )
                    )
                else:
                    canonical_violations.append(
                        CanonicalViolation(
                            port=port,
                            name=name,
                            locked_at_layer=lock_item.layer,
                            violating_layer=item.layer,
                        )
                    )
            if lock_item.has_body:
                resolved.append(
                    Resolved(
                        port=port,
                        name=name,
                        winning_layer=lock_item.layer,
                        canonical=True,
                    )
                )
            else:
                # Canonical declaration with no body: must be supplied by
                # a layer at-or-deeper-than the lock. But canonical bars
                # deeper layers from supplying — so a body-less canonical
                # is a gap by construction.
                required_gaps.append(
                    RequiredGap(
                        port=port,
                        name=name,
                        declared_by_layer=lock_item.layer,
                    )
                )
            continue

        # No canonical declaration. Pick the deepest body-bearing
        # declaration; record any shadowed body-bearing decls as
        # `conflicts` for the audit log.
        body_decls = [
            (depth, item) for depth, item in declarations if item.has_body
        ]
        if not body_decls:
            # Only `required` declarations exist — gap.
            declaring = declarations[0][1]
            required_gaps.append(
                RequiredGap(
                    port=port,
                    name=name,
                    declared_by_layer=declaring.layer,
                )
            )
            continue

        winning_depth, winner = body_decls[-1]
        overridden = tuple(
            item.layer
            for depth, item in body_decls
            if depth < winning_depth
        )
        if overridden:
            conflicts.append(
                Conflict(
                    port=port,
                    name=name,
                    overridden_layers=overridden,
                )
            )
        resolved.append(
            Resolved(
                port=port,
                name=name,
                winning_layer=winner.layer,
                canonical=False,
            )
        )

    return CascadeReport(
        resolved=tuple(resolved),
        unreachable=tuple(unreachable),
        canonical_violations=tuple(canonical_violations),
        required_gaps=tuple(required_gaps),
        conflicts=tuple(conflicts),
    )
