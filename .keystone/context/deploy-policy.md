# Deploy Policy

## Rules

- MUST run full CI green before any production deploy.
- MUST get two reviewer approvals on the PR.
- SHOULD prefer Tuesday/Wednesday morning deploys; never deploy Friday afternoon.
- MAY skip the staging step for docs-only changes.

## Background

The team adopted the two-approval rule after a 2025-09 incident where a single-approver
deploy shipped a regression to billing. Deploys are concentrated mid-week so on-call
has uninterrupted bandwidth if rollback is needed.
