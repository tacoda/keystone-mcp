# Playbook: Install

**Wire up a new external source.**

## Goal

Add a working `sources:` and (usually) `topics:` declaration in
`.keystone/context.yaml` so the harness can pull from a new
third-party system — a shared standards repo, the team's Notion
handbook, a Slack channel, etc.

## Phases

1. **Source installer.** Invoke the `keystone-source-installer`
   skill. It walks the user through type, identifier, auth, classify
   selectors, and canonical/required.
2. **Apply the YAML diff.** Surface the exact block that will land,
   pause for user acceptance, then write
   `.keystone/context.yaml`.
3. **Verify.** Read `keystone://harness/verify`. Surface any new
   canonical conflicts or required gaps.
4. **Topic binding (optional).** If the user wants the new source
   exposed under one or more topics, add the binding(s) and re-verify.

## Iron laws

- **No secrets in YAML.** Use `env:VAR` references.
- **No canonical declarations without user acceptance.** A canonical
  lock changes what files the agent reaches; surface the impact first.

## Output

An updated `.keystone/context.yaml` and a passing cascade verify.
