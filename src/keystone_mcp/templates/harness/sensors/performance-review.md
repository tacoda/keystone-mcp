---
kind: custom
---

# Sensor: performance-review

Inferential performance review of the current diff. Blocking when
the diff touches hot paths.

- **Run** — `.keystone/harness/prompts/performance-review.md` (agent reads + reasons)
- **Trigger** — review phase gate when performance-sensitive files are touched.
- **Inputs** — current diff scoped to hot paths.
- **Exit condition** — pass = agent reports PASS; fail = agent reports FAIL.
- **Output** — PASS or FAIL with cited findings.
- **State writes** — none.
