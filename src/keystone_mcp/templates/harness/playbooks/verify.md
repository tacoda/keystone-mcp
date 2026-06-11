# Playbook: Verify

**Run every applicable sensor; produce a unified verification report.**

## Goal

Surface drift, regressions, and policy violations before the agent
claims completion or before a release goes out.

## Phases

1. **Discover sensors.** Read `keystone://harness/status` to enumerate
   `sensors/`. Pair each with its implementation file
   (`scripts/<name>.sh` or `prompts/<name>.md`).
2. **Run computational sensors.** Each `scripts/<name>.sh` runs via
   Bash. Exit 0 = pass; non-zero = fail.
3. **Run inferential sensors.** For each `prompts/<name>.md`, read the
   prompt, perform the reasoning task it describes, report PASS or
   FAIL with cited findings.
4. **Aggregate.** Build a single PASS/FAIL report per sensor, with the
   cause on FAIL.

## Iron laws

- **No `--no-verify` ever.**
- **No completion claims without fresh evidence from this turn's run.**

## Output

A verification report: which sensors ran, which passed, which failed,
what the failure said.
