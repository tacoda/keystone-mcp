# Changelog

All notable changes to `keystone-mcp` are documented here. Versions group
into pre-1.0 minors per the Keystone Harness Manager plan in
[`FEATURE_PARITY_PLAN.md`](./FEATURE_PARITY_PLAN.md).

## Unreleased — 0.2.0 (in flight)

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
