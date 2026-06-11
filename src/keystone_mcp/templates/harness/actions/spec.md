# Action: Spec

**Restate intent and pin acceptance criteria before any work begins.**

## When to use

First step of the `task` playbook. Run before `orient`. Never skip.

## Inputs

- The user request.
- The current state of `corpus/state/CODEBASE_STATE.md`.

## Activities

1. Restate the user's request in your own words.
2. List acceptance criteria — concrete, falsifiable statements of what
   "done" looks like.
3. List non-goals — what is explicitly out of scope.
4. Flag uncertainty — any place you'd guess instead of know.
5. Pause for explicit user acceptance of the spec.

## Output

A spec the rest of the task references. Saved inline in the
conversation; not written to disk (yet).

## Iron laws

- **No proceeding without explicit acceptance criteria.**
- **No invented requirements.** If the user didn't say it, surface it
  as a question.
