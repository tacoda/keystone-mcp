---
description: Run every applicable sensor and produce a unified PASS/FAIL report.
---

# keystone-sensor-runner

**Single entry point for the verify phase: enumerate sensors, run each
in its correct mode, report aggregate PASS/FAIL.**

Sensors live in two ports:
  * `sensors/<name>.md` declares each sensor (kind, intent, blocking
    status).
  * `scripts/<name>.sh` implements **computational** sensors. Exit 0 =
    pass.
  * `prompts/<name>.md` implements **inferential** sensors. Agent
    reads the prompt and reports PASS or FAIL with cited findings.

Convention: a sensor named `<x>` is computational if and only if
`scripts/<x>.sh` exists. If `prompts/<x>.md` exists instead, the
sensor is inferential. Both → ambiguous (warn + prefer the script).

## When to use

The verify phase of the `task` playbook (or any other flow that gates
on sensor outcomes — release, doctor, audit).

## Activities

1. **Enumerate.** Read `keystone://harness/status` to list everything
   under `sensors/`. For each, decide mode by checking which
   implementation file exists.
2. **Run computational sensors.** Each `scripts/<name>.sh` runs via
   Bash. Exit 0 = pass; non-zero = fail. Capture stdout + stderr.
3. **Run inferential sensors.** For each `prompts/<name>.md`:
   - Read the prompt body.
   - Perform the reasoning task it describes against the current
     diff (or scoped region).
   - Report PASS or FAIL with cited findings (file:line refs, no
     invented evidence).
4. **Aggregate.** Build one report:
       Sensor       Mode            Status   Cause (on fail)
       --------     -------------   ------   ---------------
       lint         computational   PASS
       code-review  inferential     FAIL     "...specific finding..."
5. **Halt on any FAIL.** Surface to the user. Do not advance the
   playbook past verify.

## Output

A unified PASS/FAIL report. The runner does not modify the diff or
the harness; it only observes and reports.

## Iron laws

- **Sensors are blocking.** A FAIL halts the workflow.
- **No `--no-verify`** to bypass a sensor.
- **No invented evidence** in inferential findings — cite real
  diff/file lines.
- **No completion claims without a fresh run.** Stale verification
  evidence is not evidence.
