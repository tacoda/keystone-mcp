# Playbook: Bootstrap

**One-time codebase analysis + state-ledger fill.**

## Goal

Stand up `.keystone/harness/` for a previously-unmanaged repo:
materialize the default tree, then analyze the codebase end-to-end so
future sessions have ground truth to work from.

## Phases

1. **scaffold.** Call `keystone_harness_bootstrap()`. Idempotent — safe
   if the skeleton already exists. Materializes the shipped default
   tree (this file, the state ledgers, the default sensors and
   actions, the example skills).
2. **read existing context.** `keystone://harness/status` for layout,
   `keystone://context/list` for already-configured topics, and the
   envelope for each existing topic. Don't start from zero if the
   repo already has Keystone wiring.
3. **codebase scan.** Walk the repo. Identify languages, frameworks,
   build/test/lint commands, top-level architecture, hotspots, risk
   areas.
4. **fill state ledgers.** Write findings into `corpus/state/`:
   `CODEBASE_STATE.md`, `code-debt.md`, `risk-fingerprints.md`,
   `quality-radar.md`, `traffic-topology.md`. Use Edit/Write — these
   files are free-form.
5. **iron-law guides.** Find existing constraints (CI config,
   CODEOWNERS, deploy scripts, READMEs). For each, scaffold a guide
   with `keystone_new_guide(name, tier="iron-law")` and fill the
   body.
6. **skills.** For well-defined operations (release, rollback,
   migration), scaffold with `keystone_new_skill(name)`.
7. **report.** Summarize: ledgers written, guides created, skills
   scaffolded. Pause for user acceptance before any further changes.

## Iron laws

- **No silent overwrites.** Propose every state-file diff before
  applying it. Use `force=True` on scaffold tools only after explicit
  user acceptance.
- **No invented facts.** If you can't verify a claim from the
  codebase, mark it `<unknown>` in the state file.
- **No secrets.** Reference env vars via `env:VAR` in
  `.keystone/context.yaml` instead.

## Output

A populated `.keystone/harness/` tree the next session can rely on.
