# Playbook: Doctor

**Full audit: cascade verification, path conformance, ambient-load
budget.**

## Goal

Surface every problem the manager can detect statically: misaligned
cascade declarations (canonical violations, required gaps,
unreachable project files), missing bootstrap dirs, unexpectedly
large ambient-load cost. Run periodically (weekly, end-of-release) or
ad-hoc after a big change.

## Phases

1. **Cascade verify.** Read `keystone://harness/verify`. Surface every
   non-empty finding bucket:
   - `unreachable` — project files shadowed by a canonical lock
     upstream. Propose a rename or relocation; the file currently
     costs zero tokens but creates user confusion.
   - `canonical_violations` — a deeper layer attempted to override a
     canonical declaration. Fail the doctor pass and propose a fix.
   - `required_gaps` — items declared `required` upstream but not
     supplied. Surface as work to do; do not fail.
   - `conflicts` — non-canonical project overrides of upstream
     content. Inform the user; the project wins by default.
2. **Path conformance.** Read `keystone://harness/doctor`'s
   `path_conformance` block. Every directory in `BOOTSTRAP_DIRS`
   should exist; surface any missing ones and propose
   `keystone_harness_bootstrap()`.
3. **Budget proxy.** Read the `budget_proxy` block. Compare against
   prior runs (Phase 27 will land a tokenizer-backed counter; today
   the proxy is a word count). Flag any port whose word total grew
   substantially without a known reason.
4. **Report.** Single markdown report with each finding bucket as a
   section. Pause for user acceptance of any proposed fix.

## Iron laws

- **Read-only.** Doctor never edits the harness. Fixes are proposed
  to the user; the user runs them.
- **Do not silently pass over required gaps.** A required gap is work
  to do, not noise.

## Output

A doctor report. The user takes the actions; the doctor doesn't
change state.
