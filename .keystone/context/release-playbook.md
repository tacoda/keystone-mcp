# Release Playbook

## Rules

- MUST update CHANGELOG.md before tagging.
- MUST run full test suite green.
- SHOULD announce the release in the team channel.

## Procedures

### Cut a patch release

1. Confirm `main` is green on CI.
2. Bump the patch version in `pyproject.toml`.
3. Update `CHANGELOG.md` with a dated entry.
4. Commit, tag `vX.Y.Z`, push tag.
5. Watch the release workflow in CI.

### Roll back a bad release

1. Identify the last good tag.
2. Revert the offending commits on `main` (or hotfix branch).
3. Cut a new patch release following the procedure above.
4. Yank the broken version from the registry if already published.

## Commands

### tag-release

```
git tag -a v$(uv run python -c "import tomllib,sys;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])") -m "release"
git push origin --tags
```

Run after the patch-release procedure to tag and push the release commit.

### check-ci

```
gh run list --branch main --limit 5
```

List recent CI runs on `main` to confirm the release commit is green before tagging.
