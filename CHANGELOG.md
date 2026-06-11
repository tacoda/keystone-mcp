# Changelog

All notable changes to `keystone-mcp` are documented here. Versions group
into pre-1.0 minors per the Keystone Harness Manager plan in
[`FEATURE_PARITY_PLAN.md`](./FEATURE_PARITY_PLAN.md).

## Unreleased — 0.2.0 (in flight)

### Phase 20 — cascade engine + canonical / required semantics

**New.** Cross-layer resolution for harness items.

- New module `keystone_mcp/cascade.py` — pure resolver that takes an
  ordered list of layers and produces a `CascadeReport` with
  `resolved`, `unreachable`, `canonical_violations`, `required_gaps`,
  and `conflicts` buckets. Specific beats broad; canonical declarations
  lock an item at the layer that declared it; required declarations
  surface gaps when no deeper layer supplies the body.
- `SourceConfig` gains `canonical` and `required` per-port dicts.
  `.keystone/context.yaml` parses new top-level keys per source:
  ```yaml
  sources:
    org-standards:
      type: repo
      canonical:
        guides: ["documentation", "todos"]
      required:
        actions: ["release-notes"]
  ```
- New module `keystone_mcp/verify.py` — builds cascade inputs from the
  configured sources plus a walk of the on-disk project layer, and
  produces the verify/doctor payloads.
- New MCP resources:
  - `keystone://harness/verify` — cascade report (read-only).
  - `keystone://harness/doctor` — cascade report + path conformance +
    ambient-load word-count proxy (read-only).
- Shipped `templates/harness/playbooks/doctor.md`.
- Tests: `tests/test_cascade.py` (engine), `tests/test_verify.py`
  (wiring), plus new cases in `tests/test_config.py` for
  canonical/required parsing.

A full repo-source manifest (`keystone-source.yaml` shipping its own
canonical/required) lands later; today the declarations live entirely
in `context.yaml`.

### Phase 19 — bootstrap playbook + menu overlay

**Behavioral.** The agent menu file (CLAUDE.md, AGENTS.md, etc.) now
overlays on top of any pre-existing content instead of replacing the
file.

- `Scaffold.target_add` writes only the region between
  `<!-- BEGIN KEYSTONE -->` and `<!-- END KEYSTONE -->`. Any user
  content above or below those sentinels is preserved verbatim across
  refreshes.
- File doesn't exist → wrote a fresh file containing only the
  Keystone block.
- File exists with the markers → refresh the block in place.
- File exists without markers → append the block after existing
  content; user content stays at the top of the file.
- Idempotent: re-running with unchanged inputs yields a byte-identical
  file.
- The `keystone_bootstrap` MCP prompt now points at the shipped
  bootstrap playbook (`playbooks/bootstrap.md`) instead of inlining
  the work, matching the new template-driven architecture.

Breaking for any consumer that relied on `target_add` overwriting the
entire menu file. Workaround: delete the file first, then call
`keystone_target_add`.

### Phase 18 — shipped template library + `actions` / `playbooks` ports restored

**Additive (mostly).** Templates move out of inline Python strings into a
shipped data tree.

- New `src/keystone_mcp/templates/` package shipped with the wheel.
  Mirrors the on-disk layout the consumer project gets at
  `.keystone/harness/`. Loaded via `importlib.resources`.
- Ships the default state-ledger templates (`CODEBASE_STATE`,
  `risk-fingerprints`, `quality-radar`, `traffic-topology`,
  `code-debt`), default computational sensors (lint / type / test /
  build / drift / coverage) with executable scripts, default
  inferential sensors (security-review / code-review /
  accessibility-review / performance-review) with prompt bodies,
  default actions (spec / orient / implement / verify / review /
  learn / audit / release), and default playbooks (task / bootstrap /
  audit / verify / release).
- `actions/` and `playbooks/` restored as first-class ports in
  `BOOTSTRAP_DIRS`. New `Scaffold.new_action`, `Scaffold.new_playbook`,
  `Scaffold.new_corpus` methods + matching `render_action`,
  `render_playbook`, `render_corpus`.
- New MCP tools: `keystone_new_action`, `keystone_new_playbook`,
  `keystone_new_corpus`.
- `Scaffold.bootstrap(materialize_templates=True)` materializes the
  shipped tree into the consumer harness. Existing files are never
  overwritten — the materialize pass writes only files that don't yet
  exist. The MCP tool `keystone_harness_bootstrap()` defaults to
  `True`; the Python-level `Scaffold.bootstrap()` defaults to `False`
  to keep test fixtures predictable.

### Phase 17 — tier vocabulary alignment

**Breaking.** Guide tiers renamed:

- `non-negotiable` → `iron-law` (heading `## IRON LAW`)
- `strong` → `golden` (heading `## GOLDEN RULES`)
- `rules` unchanged.

`render_guide` raises a `ScaffoldError` with a migration hint when called
with a legacy tier. `extract_tier_sections` keeps reading the legacy
heading names (`## NON-NEGOTIABLE`, `## STRONG`) for one release so
existing harnesses keep parsing; its return-value keys are now
`iron-law` / `golden`. `_format_inlined_rules` and `render_agent_menu`
also accept the legacy keys transitionally. `keystone://harness/options`
exposes the new vocabulary.

### Phase 16 — namespace `keystone` across every primitive

**Breaking.** Every MCP primitive now carries the `keystone` namespace.

- Tools renamed (`get_context` → `keystone_get_context`, `list_topics` →
  `keystone_list_topics`, `harness_bootstrap` →
  `keystone_harness_bootstrap`, `harness_new_*` → `keystone_new_*`,
  `harness_target_add` → `keystone_target_add`).
- Prompts renamed (`bootstrap` → `keystone_bootstrap`, `task` →
  `keystone_task`, `audit` → `keystone_audit`, `learn` →
  `keystone_learn`).
- Resource URIs renamed
  - `context://list` → `keystone://context/list`
  - `context://{topic}` → `keystone://context/{topic}`
  - `source://{name}/health` → `keystone://source/{name}/health`
  - `harness://status` → `keystone://harness/status`
  - `harness://options` → `keystone://harness/options`
- Skills authored by the manager itself are automatically prefixed
  `keystone-` (see `Scaffold.new_skill`). Project-authored skills are
  unaffected.
- `INSTRUCTIONS`, the menu template inlined into `CLAUDE.md`/`AGENTS.md`,
  the bootstrap / task / audit / learn prompt bodies, and the README MCP
  surface table all reflect the new names.
- `tests/test_namespace.py` asserts the four namespace invariants
  (tools, prompts, resources, manager-authored skills).

Consumers who pinned to specific tool/prompt/resource names must update
their callers. The package name on PyPI stays `keystone-mcp`.
