# Project harness

This directory is the Keystone harness for this project. It is the
**single source of truth** for project context — rules the agent must
follow, reasoning the agent should reference, sensors the agent must
run, and procedures the agent walks. The Keystone Harness Manager
(`keystone-mcp`) reads, scaffolds, and audits this tree; the MCP
resources at `keystone://` are projections of these files.

Edit any markdown file by hand in your editor, or scaffold new ones
with the `keystone_new_*` MCP tools. Both paths converge on identical
files.

## Layout

- `guides/` — rules the agent obeys. Tiered iron-law / golden / rules.
- `corpus/` — reasoning, background, ADRs.
- `corpus/state/` — ledgers maintained by the bootstrap and audit
  playbooks: `CODEBASE_STATE.md`, `risk-fingerprints.md`,
  `quality-radar.md`, `traffic-topology.md`, `code-debt.md`.
- `sensors/` — blocking checks (lint, type, test, build, drift,
  coverage, plus inferential reviews).
- `scripts/` — shell bodies for computational sensors.
- `prompts/` — markdown bodies for inferential sensors.
- `actions/` — focused operations the agent walks (`spec`, `orient`,
  `implement`, `verify`, `review`, `learn`, `audit`, `release`).
- `playbooks/` — ordered phase flows (`task`, `bootstrap`, `audit`,
  `install`, `verify`, `doctor`, `patch`, `release`).
- `skills/` — FastMCP-native `skill://` how-to entries. Manager-authored
  skills are prefixed `keystone-`.
- `adapters/` — per-agent activation bindings (claude-code, codex,
  cursor, …).
- `learning/inbox/` — captured findings awaiting audit-time
  classification.
- `archive/` — content retired by the pruning flywheel. Never deleted.

## Iron law

**Never put secrets in this tree.** It is version-controlled and
team-shared. Reference environment variables via `env:VAR` in
`.keystone/context.yaml` instead.
