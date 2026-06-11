# Action: Verify

**Run every applicable sensor; surface failures.**

## When to use

Sixth step of the `task` playbook. After `implement` and `check-drift`,
before `review`.

## Inputs

- The diff produced by `implement`.
- `keystone://harness/status` to enumerate sensors.
- Each sensor's invocation file (script under `scripts/` or prompt
  under `prompts/`).

## Activities

1. For each sensor in `sensors/`, determine its mode from the matching
   implementation file (script vs prompt).
2. Run computational sensors via Bash; exit 0 = pass, non-zero = fail.
3. Run inferential sensors by reading the prompt and performing the
   reasoning task; report PASS or FAIL with cited findings.
4. Halt on any failure. Surface the failure to the user and propose a
   fix. Do not proceed to `review`.

## Output

A unified verification report: which sensors ran, which passed, which
failed, what the failure said.

## Iron laws

- **No completion claims without fresh verification evidence.** Sensors
  must run this turn.
- **No proceeding past a failed sensor.**
- **No `--no-verify` ever.**
