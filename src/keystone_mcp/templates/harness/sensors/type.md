---
kind: type
---

# Sensor: type

Static type checking across the codebase. Blocking.

- **Run** — `.keystone/harness/scripts/type.sh` (shell)
- **Trigger** — verification phase gate.
- **Inputs** — source tree.
- **Exit condition** — pass = exit 0; fail = non-zero.
- **Output** — pass/fail with type errors on stderr.
- **State writes** — none.
