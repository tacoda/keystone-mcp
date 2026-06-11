# code-review

**Inferential sensor: code-review.**

Perform a code review against the current diff. Report a single
verdict at the end: `PASS` or `FAIL: <reason>`.

## Scope

Functional correctness, simplicity, idiomatic fit with the surrounding
code, test coverage of the new behavior.

## Checks

- **Correctness** — does the diff do what its spec / commit message
  says? Are edge cases handled?
- **Simplicity** — is anything over-engineered? Could 50 lines replace
  200?
- **Idiomatic fit** — does the diff match the conventions in the
  touched module? Naming, error handling, structure?
- **Tests** — does new behavior have tests? Do tests cover the failure
  modes, not just the happy path?
- **Scope creep** — does the diff change code unrelated to the spec?

## PASS criteria

The change reads as a reasonable solution to its stated problem, has
test coverage for the new behavior, and does not drag along
unsolicited refactoring.

## FAIL examples

- Feature added without any tests.
- Diff modifies unrelated files "while I was in there".
- Premature abstraction that complicates a one-call-site path.
