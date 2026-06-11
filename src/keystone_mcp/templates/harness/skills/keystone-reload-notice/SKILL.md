---
description: Surface a "reload the harness" notice to the user when guides changed mid-session.
---

# keystone-reload-notice

**Tell the user the current session's ambient context is stale.**

Guides under `.keystone/harness/guides/` are loaded at session start by
the agent runtime (via the menu file overlay or an equivalent
mechanism). When the audit or learn flow modifies a guide, the
current session keeps reading the pre-edit body until it reloads.
This skill emits the explicit reload notice.

## When to use

- A `guides/` file was created, edited, archived, or moved.
- A canonical declaration changed upstream and the cascade resolution
  reorders.
- A new sensor whose body needs to be picked up immediately landed
  during the session.

## Activities

1. List the files that changed (paths + one-line summary).
2. Surface the notice to the user:

       Harness reload needed
       ──────────────────────
       The following guides were updated this session:
         - <path>
         - <path>
       The current agent context is stale until the menu file is
       refreshed. Re-run `keystone_target_add(<agent>, force=True)` (or
       reload your IDE / agent session) before the next task.

3. Optionally re-run `keystone_target_add(agent, force=True)` to
   refresh the overlay block in the menu file. This still leaves the
   in-memory agent context stale; only a fresh session fully picks up
   the change.

## Output

A reload notice (free-form text). No file writes by default; the user
decides when to reload.

## Iron laws

- **Don't pretend the reload happened.** Until the agent session
  restarts, the in-memory context lags.
- **Don't suppress the notice.** Even if the user just acknowledged
  an earlier one, surface each subsequent guide change.
