# Playbook: Release

**Cut a release: verify, package, publish, notify.**

## Goal

Get a new version out the door with full verification, no surprises,
and explicit user acceptance at each gate.

## Phases

1. **Pre-flight.** Working tree clean, on the release branch, all
   `corpus/state/` ledgers reconciled.
2. **Verify.** Invoke the `verify` playbook. Must be green.
3. **Changelog.** Confirm `CHANGELOG.md` has an entry for this
   release. Pause for user acceptance of the entry.
4. **Bump.** Bump the version per the project scheme (semver, dates,
   etc.).
5. **Tag + build.** Tag the commit and build the artifact(s).
6. **Publish.** Push the tag, publish to the package registry, send
   announcements — project-specific.
7. **Smoke.** Pull the published artifact in a clean environment and
   verify it works.

## Iron laws

- **No release with failing sensors.**
- **No release without a changelog entry.**
- **No publishing without explicit user acceptance.**
- **No AI attribution in release notes / commits / tags.**

## Output

A released artifact + a tag in git + a record in `CHANGELOG.md`.
