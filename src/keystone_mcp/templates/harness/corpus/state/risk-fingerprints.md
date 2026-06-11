# Risk fingerprints

Areas of this codebase that warrant extra care — high churn, low test
coverage, security surfaces, external integrations, gnarly history.
Filled by `keystone_bootstrap` and refreshed by `keystone_audit`.

## High-risk areas

- **<path/module>** — <why: low coverage / high churn / external
  surface / regulated / etc.>

## Avoid-touching-without-explicit-acceptance

- **<path/file>** — <reason: load-bearing, complex invariants, prior
  outage history.>

## Recent incidents

- <YYYY-MM-DD>: <one-line summary, link to postmortem or commit>
