# KAMI Round 8: demo polish (WCAG 2.1 AA audit + polish pass)

Decided by the user 2026-10-18 ("Demo polish"). Same rules as CLAUDE.md (single agent, one task at a time, PROGRESS.md after each task).

**Why.** The next real use of the dashboard is the live demo / viva (PRODUCT.md). WCAG 2.1 AA is now the binding standard; until now axe ran only with its default rules (no serious or critical finding), and details (focus, small status text contrast, number widths, radii, motion, projector sizes) were never reviewed together.

**Out of scope.** Hindi in the dashboard (its own round), models, results, frozen files, API semantics, the Telegram message, the citizen bot, new features, new dependencies. Data labels stay as they are.

## Tasks
- **P0. Scope + housekeeping:** this file, `scripts/check_round8.py` first, `.gitignore` for the locally installed skill files.
- **P1. Audit (no UI edits):** axe with WCAG 2.1 A/AA tags on 5 pages x 2 themes, the impeccable detector, contrast of every status colour, keyboard-only walk, sizes 1440x900 / 1920x1080 / 1280x720 / 390x844 and 320 px reflow, reduced motion, detail checklist (tabular numbers, radii, shadows vs borders, transitions, hit areas, icons). Output `results/demo_polish/audit.md`, findings P0-P3.
- **P2. Fix (presentation layer only):** every AA failure and the demo-relevant details, each with a test where testable; Playwright a11y spec on the WCAG 2.1 AA tag set with zero violations.
- **P3. Verify:** build, Vitest, Playwright, detector again, visual check at the four sizes, regenerate the 16 screenshots and the axe report.
- **P4. Close:** PROGRESS.md, decisions.md, CLAUDE.md history, commit `round 8: demo polish (WCAG 2.1 AA, details)`, push per CLAUDE.md rule 6. STOP.

## check_round8.py exits 0 only if
audit file exists and every P0/P1 finding is marked fixed with a test; the WCAG 2.1 AA axe scan is clean on all pages in both themes; build and tests pass; no backend or results file outside `results/screens`, `results/a11y`, `results/demo_polish` changed; earlier quick checks pass.
