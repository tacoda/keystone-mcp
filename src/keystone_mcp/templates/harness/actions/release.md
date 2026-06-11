# Action: Release

**Cut a release: tag, package, publish, notify.**

## When to use

Driven by the `release` playbook. After verify + review pass on the
release branch.

## Inputs

- Clean working tree on the release branch.
- `corpus/state/CODEBASE_STATE.md` reconciled.
- All sensors green.
- The changelog entry for this release.

## Activities

1. Verify clean tree + no uncommitted edits.
2. Bump the version per the project's scheme.
3. Tag, build artifacts, and publish (project-specific).
4. Surface the published artifact for the user's explicit acceptance.

## Output

A released artifact + a tag in git.

## Iron laws

- **No release with failing sensors.**
- **No release with no changelog entry.**
- **No publishing without explicit user acceptance.**
