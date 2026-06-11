---
kind: custom
---

# Sensor: accessibility-review

Inferential accessibility review of the current diff. Blocking when
the project touches user-facing UI.

- **Run** — `.keystone/harness/prompts/accessibility-review.md` (agent reads + reasons)
- **Trigger** — review phase gate when UI files are touched.
- **Inputs** — current diff scoped to UI files.
- **Exit condition** — pass = agent reports PASS; fail = agent reports FAIL.
- **Output** — PASS or FAIL with cited findings.
- **State writes** — none.
