---
kind: lint
---

# Sensor: lint

Format / style enforcement across the codebase. This is a **blocking**
rule — the agent must run it and it must pass for the workflow to
continue.

- **Run** — `.keystone/harness/scripts/lint.sh` (shell)
- **Trigger** — verification phase gate (and pre-commit).
- **Inputs** — files in the working tree (staged in pre-commit mode).
- **Exit condition** — pass = exit 0; fail = non-zero.
- **Output** — pass/fail; on fail, stdout/stderr surface the cause.
- **State writes** — none.
