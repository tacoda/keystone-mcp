# Playbook: Task

**Canonical six-phase lifecycle for a unit of work.**

## Goal

End-to-end execution of one task: from intent → accepted change. The
agent walks every phase in order and pauses for explicit user
acceptance between phases.

## Phases

1. **spec.** Restate intent, list acceptance criteria, list non-goals,
   flag uncertainty. Gate: explicit acceptance of the spec.
2. **orient.** Read harness + state ledgers, identify idioms, sketch a
   plan. Gate: explicit acceptance of the plan.
3. **load rules.** Read `keystone://context/{topic}` for every topic
   the change touches. Note all `must`-severity rules that apply.
4. **implement.** Make the smallest change that satisfies the plan.
5. **check-drift.** Fast diff-vs-guides comparison before running
   heavyweight sensors.
6. **verify.** Run every applicable sensor. Halt on any failure.
7. **review.** Functional, security, risk, deployment review against
   acceptance criteria.
8. **learn (conditional).** If something surprising surfaced, invoke
   the `learn` action to capture it into `learning/inbox/`.

## Iron laws

- No proceeding without explicit acceptance criteria.
- No completion claims without fresh verification evidence.
- No commits with failing sensors. Never `--no-verify`.
- No AI attribution in commits, PRs, or tracker comments.
- No silent overwrites of state files.

## Output

A landed change that satisfies the accepted spec, plus a verification
record that survives review.
