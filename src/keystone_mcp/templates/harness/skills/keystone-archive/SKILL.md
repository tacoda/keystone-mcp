---
description: Retire a harness file by moving it to archive/ with reasoning frontmatter — never delete.
---

# keystone-archive

**Move a retired file to `archive/<port>/<name>.md` with reasoning so
the audit log explains why content is gone.**

The pruning flywheel never deletes content. Anything retired moves to
`archive/` where it's still version-controlled and searchable. This
skill performs the move + writes the reasoning frontmatter.

## When to use

- A guide is stale (names a removed API, contradicts a newer guide,
  no longer followed).
- A corpus entry is obsolete (the design it documents has moved on).
- A skill / action / playbook is empty or unused.

## Activities

1. Identify the file to retire (port + name + path).
2. Compose retirement reasoning:
   - **Why retired** — one sentence with a concrete cause.
   - **Last referenced** — git commit / PR / date.
   - **Replacement (if any)** — path of the file that supersedes it.
3. Prepend YAML frontmatter to the file body:

       ---
       retired_on: <YYYY-MM-DD>
       retired_by: <agent or user>
       reason: <one sentence>
       replaced_by: <path or "none">
       ---

4. Move the file to `archive/<port>/<original-name>.md`. Use the
   existing port name as a subdir under `archive/`.
5. Emit a reload notice via the `keystone-reload-notice` skill if a
   `guides/` file was archived.

## Output

A file moved from `<port>/` to `archive/<port>/` with reasoning
frontmatter. The original file's content is preserved verbatim below
the frontmatter.

## Iron laws

- **Never delete.** Archive only.
- **Never archive without reasoning.** Every retirement carries a
  why.
- **Never archive a file that's still referenced.** Check
  `keystone://harness/status` and the cascade verify report first.
