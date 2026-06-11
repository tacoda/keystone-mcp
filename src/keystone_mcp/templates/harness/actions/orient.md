# Action: Orient

**Read the harness, read the touched region, sketch a plan.**

## When to use

Second step of the `task` playbook. After `spec`, before `implement`.

## Inputs

- The accepted spec from `spec`.
- `keystone://harness/status` for harness layout.
- `corpus/state/` ledgers: `CODEBASE_STATE.md`, `code-debt.md`,
  `risk-fingerprints.md`.
- The files the diff is likely to touch.

## Activities

1. Identify the idioms in the touched region.
2. Sketch a plan: ordered steps, intermediate verifications, the
   smallest change that satisfies the spec.
3. Surface risks: what could go wrong? What's load-bearing nearby?
4. Pause for explicit user acceptance of the plan.

## Output

A plan the rest of the task executes against. Includes intermediate
gates so the agent doesn't drift.

## Iron laws

- **No execution without an accepted plan.**
- **No invented context.** Cite real files, real lines, real ledgers.
