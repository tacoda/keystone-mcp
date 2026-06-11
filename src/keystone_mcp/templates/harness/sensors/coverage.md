---
kind: coverage
---

# Sensor: coverage

Test-coverage threshold check. Blocking when the project sets a
coverage floor; informational otherwise.

- **Run** — `.keystone/harness/scripts/coverage.sh` (shell)
- **Trigger** — verification phase gate; release flow.
- **Inputs** — coverage report from the test sensor.
- **Exit condition** — pass = coverage ≥ floor; fail = below floor or
  no report.
- **Output** — total coverage + uncovered hotspots.
- **State writes** — `corpus/state/quality-radar.md` (coverage row,
  via the audit playbook — not from this sensor directly).
