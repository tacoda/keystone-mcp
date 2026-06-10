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

You are bootstrapping the project harness at `.keystone/harness/`. Goal:
analyze this codebase end-to-end and fill the project's state ledgers so
future sessions have ground truth to work from.

## Phases

1. **Scaffold (if needed).** Call `harness_bootstrap`. Idempotent — safe
   if the skeleton already exists.

2. **Read existing context.** Read these resources:
   - `harness://status` — what files already exist.
   - `context://list` — which topics are configured.
   - For each existing topic that is harness-backed, read
     `context://{topic}` so you start from current state, not zero.

3. **Codebase scan.** Walk the repository. Identify:
   - Languages, frameworks, libraries (from manifests + entry points).
   - Build / test / lint / type-check commands.
   - Top-level architecture (services, packages, layers).
   - Hotspots: largest files, most-edited files, files with TODOs.
   - Risk fingerprint: areas with little test coverage / high churn /
     external integrations.

4. **Fill state ledgers.** Write findings into
   `.keystone/harness/corpus/state/`:
   - `CODEBASE_STATE.md` — language, frameworks, build/test commands,
     architecture summary.
   - `code-debt.md` — known debt categorized.
   - `risk-fingerprints.md` — areas to handle carefully.
   - `quality-radar.md` — coverage gaps, lint deltas, type-check holes.
   - `traffic-topology.md` — entry points, dependencies, external calls.

   Use plain markdown writes (Edit / Write tools) for these state files —
   they are not template-shaped and `harness_new_*` does not cover them.

5. **Iron-law guides.** Identify deploy / security / data-handling
   constraints that already exist (CI config, CODEOWNERS, deploy scripts,
   inline comments, README sections). For each, call
   `harness_new_guide(name, tier="iron-law")` and fill in the body.

6. **Skills.** If the codebase has well-defined operations (release,
   rollback, migration steps), scaffold them with
   `harness_new_skill(name, description=...)`. Body = the procedure.

7. **Report.** Summarize: ledgers written, guides created, skills
   scaffolded. Pause for user acceptance before any further changes.

## Iron laws for bootstrap

- **No silent overwrites.** Propose every state-file diff before applying
  it. Use `force=True` on scaffold tools only after explicit user
  acceptance.
- **No invented facts.** If you can't verify a claim from the codebase,
  mark it as `<unknown>` in the state file rather than guessing.
- **No secrets.** Never write secrets, tokens, credentials, or
  environment-variable values into `.keystone/`. Reference via `env:VAR` in
  `.keystone/context.yaml` instead.
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

2. **orient.** Read `harness://status` and the relevant
   `.keystone/harness/corpus/state/` ledgers (CODEBASE_STATE,
   code-debt, risk-fingerprints). Identify the idioms in the touched
   region. Sketch a plan. **Gate:** explicit user acceptance of the plan.

3. **load rules.** Read `context://{{topic}}` for every topic relevant to
   the change (or `context://list` if you need to discover). Note any
   rules with severity `must` that apply.

4. **implement.** Make the changes inside the loaded idioms. Iron law:
   **Surgical edits only — touch what the spec requires.**

5. **check-drift.** Fast diff-vs-guides comparison before running
   heavyweight sensors. Read sensors via `context://` if the harness has
   them configured.

6. **verify.** Sensors are **blocking rules** — they MUST pass for this
   phase to clear. Read `context://{{topic}}` for any topic backed by the
   harness adapter `sensors` query (or read `harness://status` to
   enumerate), then for each sensor:
   - Invoke its `invocation` field (the shell script under
     `.keystone/harness/scripts/`) via the Bash tool.
   - Capture exit code + stdout/stderr.
   - **Halt** if any sensor exits non-zero. Surface the failure to the
     user and propose a fix; do not proceed to review or claim
     completion. Iron law: **no proceeding past a failed sensor.**

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
   whether to promote it to a guide (`harness_new_guide`) or skill
   (`harness_new_skill`), park it for more evidence, or discard.
2. Read recent commits. Surface patterns that should become guides.
3. Append new findings to the inbox via the `learn` prompt for the next
   audit pass.

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
applying it; do not silently overwrite.** Read `harness://status` to
ground claims about what currently exists.
"""


def render_learn(finding: str) -> str:
    return f"""\
# Learn — capture a finding

Capture this finding into `.keystone/harness/learning/inbox/` so the next
audit pass can decide whether to promote it to a guide or skill:

> {finding}

## Steps

1. Read `harness://status` to confirm the inbox exists. If not, run
   `harness_bootstrap` first.

2. Classify the finding:
   - **Iron law** — a constraint that must always hold. Use
     `harness_new_guide(name, tier="iron-law")` later.
   - **Rule / golden rule** — a normal or aspirational rule. Use
     `harness_new_guide(name, tier="rules")` or `tier="golden"` later.
   - **Skill** — a procedural how-to. Use `harness_new_skill(name)` later.
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
