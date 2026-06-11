# security-review

**Inferential sensor: security-review.**

Perform a security review against the current diff. Report a single
verdict at the end: `PASS` or `FAIL: <reason>`. The agent halts the
workflow on any `FAIL`.

## Scope

The full diff plus any file whose body the diff touches transitively.
Static analysis tools, OWASP top-10 categories, and the project's own
threat model (see `corpus/state/risk-fingerprints.md`).

## Checks

- **Injection** — SQL, command, template, header, log injection
  surfaces.
- **AuthZ / AuthN** — missing checks, privilege escalation paths,
  insecure session handling.
- **Secrets** — credentials, tokens, keys committed to source.
- **Crypto** — weak primitives, custom crypto, broken random.
- **Deserialization** — untrusted input into eval/pickle/marshal.
- **Dependencies** — new packages with known CVEs.
- **Input validation** — boundary handling, content-type confusion,
  path traversal.
- **Side channels** — leaked timing, error messages, log content.

## PASS criteria

No finding rises to "must fix before merge". Lower-severity findings
are documented but do not block.

## FAIL examples

- New SQL string concatenation that bypasses the project's
  query-builder.
- A new endpoint that takes user input and writes to the filesystem
  with no path normalization.
- A new dependency with a published high-severity CVE.
