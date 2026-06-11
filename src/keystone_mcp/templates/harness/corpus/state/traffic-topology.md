# Traffic topology

How data and control flow through this system: entry points,
dependencies between modules, external calls. Filled by
`keystone_bootstrap` and refreshed by `keystone_audit`.

## Entry points

- **<path>** — <type: HTTP route, CLI command, scheduled job, message
  consumer, library export>.

## Internal dependencies

<Brief sketch of which modules call which. Reference architecture
diagrams if they exist (link, don't redraw in markdown).>

## External calls

- **<service>** — <endpoint(s), auth method, criticality>.

## Failure-domain notes

<Boundaries that, when crossed, change the failure characteristics of
the system (retry semantics, idempotency, transactionality).>
