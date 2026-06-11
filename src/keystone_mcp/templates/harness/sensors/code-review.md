---
kind: custom
---

# Sensor: code-review

Inferential code review of the current diff. Blocking.

- **Run** — `.keystone/harness/prompts/code-review.md` (agent reads + reasons)
- **Trigger** — review phase gate.
- **Inputs** — current diff, touched files.
- **Exit condition** — pass = agent reports PASS; fail = agent reports FAIL.
- **Output** — PASS or FAIL with cited findings.
- **State writes** — none.
