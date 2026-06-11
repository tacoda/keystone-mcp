# Quality radar

Snapshot of test coverage gaps, lint deltas, type-check holes, and
other quality signals. Filled by `keystone_bootstrap`, refreshed by
`keystone_audit`.

## Test coverage

- **Overall** — `<percent>` (`<tool / command used>`).
- **Untested modules** — `<list paths with no test coverage>`.
- **Critical paths without integration tests** — `<list>`.

## Lint / format

- **Tool** — `<black/ruff/eslint/...>`.
- **Standing violations** — `<count + bucket summary>`.

## Type-check

- **Tool** — `<mypy/pyright/tsc/...>`.
- **Standing errors** — `<count + bucket summary>`.

## Notes

<Patterns or workflows that drift quality (e.g. "tests added only to
new code; legacy modules accumulate uncovered branches").>
