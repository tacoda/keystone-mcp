---
description: Report the ambient-load token cost of the project harness, sorted by hot file.
---

# keystone-budget-reporter

**Read `keystone://harness/budget` and surface a digestible summary so
the user knows how many tokens their harness costs at session start.**

The agent's ambient context includes every file it auto-loads at
session start — typically `guides/`, the menu file overlay, and the
project's iron-law + golden-rule sections. As the harness grows, this
cost grows. The budget reporter makes the growth visible.

## When to use

- Periodic check (weekly, monthly).
- After a big learning sweep (audit promoted many findings to
  guides).
- When the user reports "the agent feels slow at session start".

## Activities

1. **Fetch the report.** Read `keystone://harness/budget`.
2. **Summarize totals.**

       Harness ambient-load budget
       ───────────────────────────
       Total: <N files>, <W words>, ~<T tokens>
       Tokenizer: word_count (Phase 27 proxy)

3. **List hot files.** Top 10 by word count, with port and approximate
   token cost:

       Port          File                       Words    ~Tokens
       ----------    --------------------       ------   -------
       playbooks     task.md                    410      547
       sensors       security-review.md         330      440
       ...

4. **Per-port totals.** Sorted by descending word count.

5. **Cascade-excluded count (if non-zero).** Project files shadowed by
   an upstream canonical lock — present on disk but never loaded.
   Propose deleting or relocating to recover the space.

## Output

A markdown summary the user can paste into a discussion or attach to
the next audit report. No state writes.

## Iron laws

- **Word-count is a proxy, not a tokenizer.** Don't claim absolute
  token counts; surface the proxy explicitly.
- **Don't suggest deleting hot files.** Surface the cost; let the user
  decide which entries to prune.
