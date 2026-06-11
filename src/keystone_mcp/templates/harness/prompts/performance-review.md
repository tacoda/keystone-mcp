# performance-review

**Inferential sensor: performance-review.**

Perform a performance review against the current diff. Report a single
verdict at the end: `PASS` or `FAIL: <reason>`.

## Scope

Hot paths the diff touches — request handlers, query layers, render
loops, batch jobs. Reference `corpus/state/traffic-topology.md` to
identify hot paths.

## Checks

- **N+1 queries** — new loops over collections that re-fetch per item.
- **Synchronous I/O in hot paths** — blocking calls in async or
  request handling.
- **Allocations** — new per-request large allocations.
- **Loops** — quadratic complexity on data structures that grow.
- **Caching** — caches invalidated correctly or unnecessarily skipped.
- **Index coverage** — new query patterns matched by existing indexes.

## PASS criteria

The diff's hot-path impact is acceptable for the expected traffic
profile. No obvious regression vs. the surrounding code.

## FAIL examples

- New ORM query inside a loop over a request-time collection.
- New synchronous network call in an async request handler.
- New full-table scan against a growing table with no matching index.
