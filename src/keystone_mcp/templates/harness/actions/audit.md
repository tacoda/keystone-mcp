# Action: Audit

**Walk the harness, propose retirements + promotions.**

## When to use

Driven by the `audit` playbook. Schedule per project cadence (weekly,
monthly, end-of-release).

## Inputs

- The full `.keystone/harness/` tree.
- Recent commits since the last audit.
- The `learning/inbox/` queue.

## Activities

1. Pruning sweep — stale rules, dead idioms, placeholders, failing
   sensors, empty shells, drifted state.
2. Learning sweep — inbox entries to promote, recent commits that
   should surface guides.
3. Move retirements to `archive/<port>/<name>.md` with reasoning.
4. Emit a reload notice if `guides/` was touched.

## Output

An audit report listing concrete proposed harness edits, plus the
actual file moves applied (with reasoning).

## Iron laws

- **Never delete guide content** — archive with reasoning instead.
- **No silent overwrites of state files.** Propose every diff before
  applying it.
