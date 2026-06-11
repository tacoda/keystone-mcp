---
description: Walk the user through declaring a new external source in .keystone/context.yaml.
---

# keystone-source-installer

**Adds a new external source binding so the harness can pull rules,
reasoning, skills, or commands from a third-party system (markdown
folder, github, confluence, notion, jira, linear, slack, repo).**

## When to use

The user wants to wire up a new source — a shared standards repo, the
team's Notion handbook, a Jira project, a Slack channel — that the
harness should pull context from at session time.

## Activities

1. **Identify the source type.** Confirm one of the supported types:
   `markdown`, `folder`, `repo`, `github`, `confluence`, `notion`,
   `jira`, `linear`, `slack`, `harness`. If the user names something
   else, surface the supported list and stop.

2. **Gather identifiers + auth.**
   - `markdown` / `folder` — local path (absolute or relative to the
     project root).
   - `repo` — `owner/repo` and a `version` (tag, sha, or branch).
   - `github` / `confluence` / `notion` / `jira` / `linear` / `slack` —
     base URL, auth token reference (`env:VAR`, never a literal).

3. **Choose classify selectors.** Ask: which fields from the source map
   to which payload kind? Defaults exist for most types; surface them
   and let the user override.

4. **Decide canonical / required.** Per port (`guides`, `actions`,
   `playbooks`, `sensors`, `skills`, `corpus`):
   - `canonical: [...]` — items the source owns exclusively. No
     project file may override.
   - `required: [...]` — items the source references but does not
     ship. A project file (or a deeper source) must supply the body.

5. **Surface the proposed YAML diff.** Show the user the exact block
   that will land in `.keystone/context.yaml`. Pause for explicit
   acceptance.

6. **Write the YAML.** Edit `.keystone/context.yaml` (or create it if
   missing). NEVER write a secret directly — every credential goes
   through `env:VAR`.

7. **Run verify.** Read `keystone://harness/verify` to confirm the
   cascade looks correct. Surface any new canonical conflicts or
   required gaps for the user to resolve.

## Output

An updated `.keystone/context.yaml` with the new source declared, plus
a verify report.

## Iron laws

- **No secrets in YAML.** Always use `env:VAR` references.
- **No silent canonical locks.** Surface the cascade impact (what
  becomes unreachable, what becomes a violation) before writing.
- **No invented auth.** If the user can't supply a token, stop and ask.
