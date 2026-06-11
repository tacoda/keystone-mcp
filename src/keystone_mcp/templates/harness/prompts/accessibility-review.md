# accessibility-review

**Inferential sensor: accessibility-review.**

Perform an accessibility review against the current diff. Report a
single verdict at the end: `PASS` or `FAIL: <reason>`.

## Scope

UI files touched by the diff (templates, components, styles). Skip
when the diff touches no UI.

## Checks

- **Semantic HTML** — correct elements (`button`, `a`, `nav`,
  `main`, headings).
- **Labels** — form controls have labels (`<label>`, `aria-label`,
  `aria-labelledby`).
- **Focus** — interactive elements are reachable + visible on focus.
- **Color contrast** — text vs. background meets WCAG AA at least.
- **Keyboard** — every action invocable without a mouse.
- **Alt text** — meaningful images carry `alt`; decorative ones carry
  `alt=""`.
- **ARIA** — used to fix actual gaps, not papered over a poor HTML
  structure.

## PASS criteria

No regression vs. the surrounding code's standard. New patterns meet
WCAG AA or have a documented exception.

## FAIL examples

- New click handler attached to a `<div>` with no keyboard handling.
- New icon-only button with no accessible name.
- Form field added with no associated `<label>`.
