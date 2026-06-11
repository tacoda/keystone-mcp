---
kind: test
---

# Sensor: test

Test-suite execution. Blocking.

- **Run** — `.keystone/harness/scripts/test.sh` (shell)
- **Trigger** — verification phase gate; release flow.
- **Inputs** — source tree + test tree.
- **Exit condition** — pass = exit 0; fail = non-zero.
- **Output** — pass/fail; failing tests on stdout.
- **State writes** — none.
