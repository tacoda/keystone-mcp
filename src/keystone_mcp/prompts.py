"""Lifecycle prompt templates — Phase 14b.

FastMCP prompts seed multi-step agent workflows. Each function in this
module renders the body of one prompt; `server.py` wires them in via
`@mcp.prompt` decorators.

Four canonical workflows:

  - bootstrap : one-time analysis of the codebase. Agent fills in state
                ledgers (CODEBASE_STATE.md, code-debt, risk fingerprint).
  - task      : end-to-end unit of work: spec → orient → implement →
                check-drift → verify → review (+ optional learn).
  - audit     : dual-flywheel audit. Learning (capture from review) +
                pruning (retire stale guides).
  - learn     : capture a single finding into learning/inbox/.

Prompts deliberately reference MCP tools and resources by name so the agent
knows what to call as it walks the phases. They do NOT inline the full
content of guides / skills / sensors — that content lives in the harness and
should be retrieved at execution time.
"""

from __future__ import annotations


def render_bootstrap() -> str:
    return """\
# Bootstrap workflow

You are bootstrapping the project harness at `.keystone/harness/`. This
prompt seeds the workflow; the actual step-by-step procedure lives in
the shipped bootstrap playbook.

## Walk the playbook

1. Run `keystone_harness_bootstrap()` if `.keystone/harness/` does not
   exist yet. The default materializes the shipped template tree
   (state-ledger templates, default sensors, default actions, default
   playbooks). Existing files are never overwritten.
2. Read `.keystone/harness/playbooks/bootstrap.md` and follow it phase
   by phase. The playbook covers:
   - scaffold (the call above)
   - read existing context (`keystone://harness/status`,
     `keystone://context/list`, per-topic envelopes)
   - codebase scan (languages, frameworks, build/test/lint commands,
     architecture, hotspots)
   - fill state ledgers (`corpus/state/CODEBASE_STATE.md`,
     `code-debt.md`, `risk-fingerprints.md`, `quality-radar.md`,
     `traffic-topology.md`)
   - iron-law guides (use `keystone_new_guide(name, tier="iron-law")`)
   - skills (use `keystone_new_skill(name, description=...)`)
   - report and pause for user acceptance

3. Install the agent menu file with `keystone_target_add(agent)`. The
   overlay preserves any existing user content above and below the
   delimited Keystone block.

## Iron laws for bootstrap

- **No silent overwrites.** Propose every state-file diff before
  applying it. Use `force=True` on scaffold tools only after explicit
  user acceptance.
- **No invented facts.** If you can't verify a claim from the
  codebase, mark it as `<unknown>` in the state file rather than
  guessing.
- **No secrets.** Never write secrets, tokens, credentials, or
  environment-variable values into `.keystone/`. Reference via
  `env:VAR` in `.keystone/context.yaml` instead.
"""


def render_task(description: str) -> str:
    return f"""\
# Task workflow

You are running the task workflow on:

> {description}

This is the canonical unit of work. Walk every phase below in order. After
each phase, **pause for explicit user acceptance** before moving on.

## Phases

1. **spec.** Restate intent. List acceptance criteria. List non-goals.
   Flag uncertainty. Save the spec inline in this conversation. Iron law:
   **No proceeding without explicit acceptance criteria.**

2. **orient.** Read `keystone://harness/status` and the relevant
   `.keystone/harness/corpus/state/` ledgers (CODEBASE_STATE,
   code-debt, risk-fingerprints). Identify the idioms in the touched
   region. Sketch a plan. **Gate:** explicit user acceptance of the plan.

3. **load rules.** Read `keystone://context/{{topic}}` for every topic
   relevant to the change (or `keystone://context/list` if you need to
   discover). Note any rules with severity `must` that apply.

4. **implement.** Make the changes inside the loaded idioms. Iron law:
   **Surgical edits only — touch what the spec requires.**

5. **check-drift.** Fast diff-vs-guides comparison before running
   heavyweight sensors. Read sensors via `context://` if the harness has
   them configured.

6. **verify.** Sensors are **blocking rules** — they MUST pass for this
   phase to clear. Read `keystone://context/{{topic}}` for any topic
   backed by the harness adapter `sensors` query (or read
   `keystone://harness/status` to enumerate), then for each sensor look
   at its `invocation` field:
   - Ends in `.sh` → **computational sensor.** Run via Bash. Exit 0 =
     pass; non-zero = fail.
   - Ends in `.md` → **inferential sensor.** Read the prompt with the
     Read tool, perform the reasoning task it describes, and report
     PASS or FAIL.
   - Empty → descriptive-only sensor; skip with a note.

   **Halt** if any sensor fails (non-zero exit or FAIL verdict). Surface
   the failure to the user and propose a fix; do not proceed to review
   or claim completion. Iron law: **no proceeding past a failed sensor.**

   Iron law: **No completion claims without fresh verification evidence —
   sensors must run this turn.**

7. **review.** Functional, security, risk, and deployment review against
   the acceptance criteria from phase 1.

8. **learn (conditional).** If something surprising came up, invoke the
   `learn` prompt to capture it into `learning/inbox/`.

## Iron laws (across every phase)

- No proceeding without explicit acceptance criteria.
- No completion claims without fresh verification evidence.
- No commits with failing sensors. Never `--no-verify`.
- No AI attribution in commits, PRs, or tracker comments.
- No silent overwrites of state files.

## Pacing

If `.keystone/harness/guides/process/modes.md` exists, read it to learn the
current pacing mode (paired / solo / autopilot). In `paired`, confirm
before non-trivial edits inside implementation; in `solo`, proceed and ask
only at genuine forks; in `autopilot`, execute end-to-end and pause only on
iron-law violations or destructive actions.
"""


def render_audit() -> str:
    return """\
# Audit workflow

You are running the dual-flywheel audit on the project harness. Two
parallel passes:

## Learning flywheel

1. Walk `.keystone/harness/learning/inbox/`. For each entry, decide
   whether to promote it to a guide (`keystone_new_guide`) or skill
   (`keystone_new_skill`), park it for more evidence, or discard.
2. Read recent commits. Surface patterns that should become guides.
3. Append new findings to the inbox via the `keystone_learn` prompt for
   the next audit pass.

## Pruning flywheel

Walk the harness and propose retirements. Categories:

1. **Stale rules** — guides not referenced or updated in N months.
2. **Dead idioms** — corpus entries whose stack is no longer in
   `CODEBASE_STATE.md`.
3. **Placeholders** — bootstrap `<...>` markers left unfilled.
4. **Failing sensors** — sensors recorded as available that error on
   invocation.
5. **Empty shells** — scaffolded dirs with no real content.
6. **Drifted state** — `CODEBASE_STATE.md` stale `last_reconciled`,
   stack-drift findings.

Then update the empirical state files in `corpus/state/`:

7. Risk fingerprint — re-read the codebase, refresh
   `risk-fingerprints.md`.
8. Traffic topology — re-trace entry points, refresh
   `traffic-topology.md`.

## Output

A single audit report with two sections (Learn / Prune), each listing
concrete proposed harness edits. **Propose every state-file diff before
applying it; do not silently overwrite.** Read `keystone://harness/status`
to ground claims about what currently exists.
"""


def render_learn(finding: str) -> str:
    return f"""\
# Learn — capture a finding

Capture this finding into `.keystone/harness/learning/inbox/` so the next
audit pass can decide whether to promote it to a guide or skill:

> {finding}

## Steps

1. Read `keystone://harness/status` to confirm the inbox exists. If not,
   run `keystone_harness_bootstrap` first.

2. Classify the finding:
   - **Iron law** — a constraint that must always hold. Use
     `keystone_new_guide(name, tier="iron-law")` later.
   - **Rule / golden rule** — a normal or aspirational rule. Use
     `keystone_new_guide(name, tier="rules")` or `tier="golden"` later.
   - **Skill** — a procedural how-to. Use `keystone_new_skill(name)` later.
   - **Reasoning** — background fact / ADR. Goes in corpus, not inbox.
   - **Defer** — interesting but not actionable yet.

3. Write a brief markdown note (use Write / Edit tools, not a scaffold
   tool — inbox entries are free-form) at
   `.keystone/harness/learning/inbox/<short-slug>.md` containing:
   - **Finding** — one-paragraph statement.
   - **Evidence** — diff lines, file paths, sensor output, or PR links.
   - **Proposed classification** — from step 2.
   - **Proposed home** — exact path the promotion would land at.

4. Do NOT promote on the spot. The audit workflow makes promotion
   decisions in batch.

## Iron laws

- No invented evidence. Cite real diffs, real sensor output, real PRs.
- No secrets in inbox entries. Reference env vars via `env:VAR`.
"""
