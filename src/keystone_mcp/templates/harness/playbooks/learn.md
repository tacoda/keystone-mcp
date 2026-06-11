# Playbook: Learn

**Learning flywheel — capture a finding into `learning/inbox/` for
batched audit-time classification.**

## Goal

Capture something the agent or user just noticed (a recurring
mistake, a new convention, a constraint that wasn't documented) so
the next audit pass can decide whether to promote it to a guide,
skill, action, or playbook. Promotion does NOT happen on the spot —
the audit playbook batches decisions to keep individual sessions
focused.

## Phases

1. **Confirm the inbox exists.** Read `keystone://harness/status`.
   If `learning/inbox/` is missing, run `keystone_harness_bootstrap()`
   first.
2. **Classify (proposed).** Pick one — the audit can override later:
   - **Iron law** — a constraint that must always hold. Promotes to
     `keystone_new_guide(name, tier="iron-law")` later.
   - **Golden rule** — preferred-path rule; deviation needs reasoning.
     Promotes to `tier="golden"`.
   - **Rule** — a normal rule. Promotes to `tier="rules"`.
   - **Skill** — a procedural how-to. Promotes to
     `keystone_new_skill(name)`.
   - **Reasoning** — background fact or ADR. Goes in `corpus/`, not
     inbox.
   - **Defer** — interesting but not actionable yet. Park.
3. **Write the inbox entry.** A free-form markdown file at
   `.keystone/harness/learning/inbox/<short-slug>.md` containing:
   - **Finding** — one-paragraph statement.
   - **Evidence** — real diff lines, real sensor output, real PR
     links. No invented evidence.
   - **Proposed classification.**
   - **Proposed home** — exact path the promotion would land at.
4. **Emit a reload notice (optional).** Use the
   `keystone-reload-notice` skill if the finding will become a guide
   that the next session needs to see at startup.

## Iron laws

- **No invented evidence.** Cite real artifacts.
- **No secrets in inbox entries.** Reference env vars via `env:VAR`.
- **No on-the-spot promotion.** Promotion happens in audit.

## Output

A new markdown file under `learning/inbox/`. Nothing else changes.
