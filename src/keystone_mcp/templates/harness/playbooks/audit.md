# Playbook: Audit

**Dual-flywheel audit: learning (additive) + pruning (subtractive).**

## Goal

Periodically reconcile the harness with the codebase. Catch stale
rules before they mislead the agent. Promote inbox findings to guides
or skills.

## Phases

1. **Learning sweep.** Walk `learning/inbox/`. For each entry, decide:
   promote to a guide (`keystone_new_guide`), promote to a skill
   (`keystone_new_skill`), park (more evidence needed), or discard.
2. **Recent commits scan.** Read commits since the last audit. Surface
   patterns that should become guides.
3. **Pruning sweep — guides.** For each guide: stale (no recent
   reference, no longer followed), contradicting a newer guide, or
   referencing removed code → candidate for archive.
4. **Pruning sweep — corpus.** Rare. Only when the team's design has
   moved on.
5. **State drift.** Re-read the codebase, refresh
   `risk-fingerprints.md`, `traffic-topology.md`, `quality-radar.md`.
6. **Archive moves.** Move retirements to `archive/<port>/<name>.md`
   with reasoning in YAML frontmatter (`retired_on`, `reason`).
7. **Reload notice.** If `guides/` was touched, emit a reload notice
   — the current session's ambient context is stale.

## Iron laws

- **Never delete guide content.** Archive with reasoning instead.
- **Propose every state-file diff before applying it.**
- **Read `keystone://harness/status`** to ground claims about what
  currently exists.

## Output

An audit report listing concrete proposed harness edits, plus the
actual file moves applied.
