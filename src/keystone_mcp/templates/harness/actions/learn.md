# Action: Learn

**Capture a finding into `learning/inbox/` for batched audit-time
classification.**

## When to use

Anytime during a task. Triggered explicitly via the `keystone_learn`
prompt or implicitly when something surprising surfaces.

## Inputs

- The finding (free-form text from the user or agent).
- Evidence: real diff lines, real sensor output, real PR links — never
  invented.

## Activities

1. Classify the finding (iron law / golden / rules / skill / reasoning
   / defer).
2. Write `.keystone/harness/learning/inbox/<short-slug>.md` containing:
   - **Finding** — one paragraph.
   - **Evidence** — real artifacts.
   - **Proposed classification.**
   - **Proposed home** — exact path the promotion would land at.
3. Do NOT promote on the spot. Audit decides in batch.

## Output

A new file under `learning/inbox/`.

## Iron laws

- **No invented evidence.**
- **No secrets in inbox entries.** Reference env vars via `env:VAR`.
