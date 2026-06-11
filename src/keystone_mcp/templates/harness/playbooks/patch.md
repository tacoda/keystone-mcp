# Playbook: Patch

**Apply shipped patches to the project harness.**

## Goal

When `keystone-mcp` ships an update that needs corresponding changes
in the consumer harness (a new state-ledger field, a renamed
heading, a fresh sensor body), the patch playbook applies them
forward-only and surfaces conflicts the user must resolve.

## Phases

1. **Check pending.** Read `keystone://harness/patch/pending`. If
   nothing is pending, stop.
2. **Inspect.** For each pending patch, summarize: target file(s),
   what changes, whether the user has modified the target file since
   the last shipped version.
3. **Surface conflicts.** Files modified by the user since the last
   shipped version are flagged. The applier refuses to overwrite
   them; the user resolves manually.
4. **Apply non-conflicting patches.** Run `keystone_apply_patches()`.
   Files unchanged since the last shipped version are updated in
   place; conflicting files are skipped and reported.
5. **Report.** List patches applied, patches skipped due to
   conflicts, suggested fixes for each conflict.

## Iron laws

- **Forward-only.** Patches never roll back. Use git to revert if
  needed.
- **No silent overwrites.** Modified files are skipped, not
  rewritten.
- **No partial commits.** Either the whole patch lands or none of
  it. Atomicity is the applier's responsibility.

## Output

A patch report. The user reviews, runs follow-up fixes for any
conflicts, then re-runs the playbook if needed.
