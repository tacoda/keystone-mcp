---
kind: drift
---

# Sensor: drift

Detect whether the codebase has drifted from `CODEBASE_STATE.md` —
new top-level dirs, removed entry points, changed build commands.
Blocking when fired during audit / release; informational otherwise.

- **Run** — `.keystone/harness/scripts/drift.sh` (shell)
- **Trigger** — audit playbook; release pre-flight.
- **Inputs** — repo tree + `corpus/state/CODEBASE_STATE.md`.
- **Exit condition** — pass = no drift; fail = drift detected.
- **Output** — drift summary on stdout.
- **State writes** — none directly (the audit playbook may update
  `CODEBASE_STATE.md` after reviewing the drift report).
