# Action: Implement

**Make the smallest changes that satisfy the accepted plan.**

## When to use

Third step of the `task` playbook. After `orient` (with an accepted
plan).

## Inputs

- The accepted spec + plan.
- Loaded rules (golden rules + iron laws from `guides/`).

## Activities

1. Make the changes inside the loaded idioms.
2. Stop at the smallest unit that produces a verifiable result.
3. If the plan turns out to be wrong, halt and re-run `orient` rather
   than improvising.

## Output

A diff that maps directly onto the accepted plan.

## Iron laws

- **Surgical edits only — touch what the plan requires.**
- **No silent scope expansion.** New scope re-enters `spec`.
- **No partial commits with failing sensors.**
