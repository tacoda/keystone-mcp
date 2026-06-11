---
kind: build
---

# Sensor: build

Project build / compile / packaging step. Blocking.

- **Run** — `.keystone/harness/scripts/build.sh` (shell)
- **Trigger** — verification phase gate; release flow.
- **Inputs** — source tree.
- **Exit condition** — pass = exit 0; fail = non-zero.
- **Output** — pass/fail.
- **State writes** — build artifacts under the project's standard
  output dir (not under `.keystone/`).
