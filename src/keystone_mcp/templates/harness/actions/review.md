# Action: Review

**Functional, security, risk, and deployment review against the spec.**

## When to use

Seventh step of the `task` playbook. After `verify` passes.

## Inputs

- The accepted spec (acceptance criteria, non-goals).
- The diff produced by `implement`.
- Verification report from `verify`.

## Activities

1. Walk acceptance criteria one by one — does the diff satisfy each?
2. Run inferential sensors (`code-review`, `security-review`,
   `accessibility-review`, `performance-review`) where applicable.
3. Flag deployment / migration risk.
4. Pause for user acceptance of the review.

## Output

A review report that either clears the change for landing or returns
it to `implement` with explicit fixes.

## Iron laws

- **No landing without acceptance-criteria coverage.**
- **No commits with failing review findings — surface them.**
