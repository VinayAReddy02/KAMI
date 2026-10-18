# Dashboard audit before the live demo (Round 8, P1)

Audited 2026-10-18 on the built dashboard served by the locked test server (`scripts/e2e_server.py`, fallback mode, dry run), following the impeccable `audit` playbook and the make-interfaces-feel-better checklist. Standard: **WCAG 2.1 AA** (PRODUCT.md). Evidence came from: axe-core 4.x with the tags `wcag2a, wcag2aa, wcag21a, wcag21aa` on 5 pages x 2 themes (Chromium, Playwright); a 45-step Tab walk of the Overview; scroll width at 320 px on every page; interactive-element sizes at 390 px; screenshots at 1920x1080 and 1280x720 (both themes); contrast ratios computed from the theme tokens; the impeccable detector on `frontend/src`; a real Enter key on a focused map marker (built-in browser). Touch gestures on a physical device were not tested.

## Audit Health Score

| # | Dimension | Score | Key Finding |
|---|-----------|-------|-------------|
| 1 | Accessibility | 3 | Map markers can be focused but not operated by keyboard (2.1.1, level A) |
| 2 | Performance | 3 | -- (lean bundle, no layout animation; nothing material) |
| 3 | Theming | 3 | Two status colours hard-coded outside the tokens (`#ff6b6b`, `#b42318`) |
| 4 | Responsive Design | 2 | Every page is 367 px wide at 320 px (1.4.10 Reflow) |
| 5 | Implementation Integrity | 3 | One decorative side-tab border (detector); otherwise one coherent system |
| **Total** | | **14/20** | **Good (address weak dimensions)** |

## Implementation Integrity Verdict
**Pass.** The dashboard expresses one product-specific system: one token set per theme, the Okabe-Ito status palette always paired with a shape and a word, one label formatter for node names, data-provenance labels on every page. The detector found one item (a decorative left accent bar on the Method page). No drift between components, no placeholder or decorative content presented as data.

## Executive Summary
- Audit Health Score: **14/20** (Good).
- Issues: **P0 0, P1 2, P2 4, P3 2**.
- axe with the WCAG 2.1 A/AA rules: **0 violations** on all 10 scans; items left for manual review were checked by hand (below).
- Text contrast passes AA everywhere: lowest pair 4.75:1 (light theme, Normal green on the page background); dark theme 5.33:1 or more.
- Top issues: keyboard users cannot open a node from the map (F01); the page does not reflow at 320 px (F02); chart tick labels are too small to read on a projector or phone (F04); control boundaries are hard to see on a projector (F05).

## Detailed Findings by Severity

### [P1] F01 Map markers cannot be operated by keyboard
- **Location:** `frontend/src/components/NodeMap.tsx` (sensor and ticket markers)
- **Category:** Accessibility
- **Impact:** The 8 sensor markers and the report marker are focusable (Leaflet gives them `role="button"`, `tabindex="0"` and the full numbered label as title), but Enter only opens a Leaflet popup, and KAMI has none: nothing happens. A keyboard-only operator cannot open the page of a node that has no alert (the only other ways in are alert links). Verified with a real Enter key on the focused "Bagayam Booster" marker: the URL did not change.
- **WCAG/Standard:** 2.1.1 Keyboard (A)
- **Recommendation:** handle Enter and Space on the markers and call the same `onSelect` / complaint handler as a click.
- **Suggested command:** /impeccable harden
- **Status:** fixed: Enter and Space on a focused marker act like a click (`NodeMap.tsx`, `onKey`); test: `frontend/e2e/demo_polish.spec.ts` "F01" (failed on the old code, passes now).

### [P1] F02 No reflow at 320 px: the top navigation forces 367 px
- **Location:** `frontend/src/theme.css` `.topbar nav` (flex row without wrapping, 351 px wide)
- **Category:** Responsive / Accessibility
- **Impact:** At 320 px (or 1280 px at 400 % zoom) every page scrolls sideways; the "Method" link sits off-screen.
- **WCAG/Standard:** 1.4.10 Reflow (AA)
- **Recommendation:** let the navigation wrap (and tighten its padding on narrow screens) so no page is wider than 320 px. Data tables keep their own horizontal scroll (allowed by 1.4.10 for two-dimensional tables).
- **Suggested command:** /impeccable adapt
- **Status:** fixed: the navigation wraps, tighter link padding at 400 px or less (`theme.css`); test: `frontend/e2e/demo_polish.spec.ts` "F02" (every page at most 320 px wide).

### [P2] F03 `aria-label` on a paragraph
- **Location:** `frontend/src/pages/NodeDetail.tsx:66` (`<p className="legend" aria-label="Shading legend">`)
- **Category:** Accessibility
- **Impact:** ARIA does not allow a name on a generic paragraph; screen readers ignore it (axe: aria-prohibited-attr, needs review, both themes). The visible text already says "Shading: ...".
- **WCAG/Standard:** 4.1.2 Name, Role, Value (best practice level)
- **Recommendation:** drop the attribute; the visible "Shading:" text is the label.
- **Suggested command:** /impeccable harden
- **Status:** fixed: attribute removed (`NodeDetail.tsx`); test: `frontend/e2e/demo_polish.spec.ts` "F03, F04, F08" and the AA scan in `frontend/e2e/a11y.spec.ts`.

### [P2] F04 Chart tick labels too small for a projector or a phone
- **Location:** `frontend/src/theme.css` `.tick { font-size: 10px }` inside a scaled `viewBox="0 0 640 150"` (`TimeSeries.tsx`)
- **Category:** Accessibility / Responsive
- **Impact:** The labels shrink with the chart: about 8 px at 1280x720 and below 6 px on a phone; the axis values and times cannot be read from the back of a room. axe could not judge their contrast (17 items "needs review").
- **WCAG/Standard:** 1.4.4 Resize Text (text scales with zoom, so not a strict failure); legibility
- **Recommendation:** larger tick text in viewBox units, tabular figures.
- **Suggested command:** /impeccable typeset
- **Status:** fixed: tick text 13 viewBox units (about 13 px at the usual laptop and projector chart width; still only about 7 px on a 390 px phone, where the latest value above each chart stays readable), tabular figures; test: `frontend/e2e/demo_polish.spec.ts` "F03, F04, F08".

### [P2] F05 Control boundaries hard to see on a projector
- **Location:** `frontend/src/theme.css` `.btn, select` (border `--border` on `--panel`: 1.37:1 dark, 1.50:1 light)
- **Category:** Accessibility / Theming
- **Impact:** Speed, Event and Node selects and the Pause button are identified by their text, so this is not a 1.4.11 failure, but on a washed-out projector they read as loose text.
- **WCAG/Standard:** 1.4.11 Non-text Contrast (not failed; the text identifies the controls)
- **Recommendation:** a control-border token with at least 3:1 against the panel, used only for buttons and selects; decorative borders stay soft.
- **Suggested command:** /impeccable polish
- **Status:** fixed: new token `--control-border` (dark #66809f, at least 3.6:1; light #6f8199, at least 3.5:1) on buttons and selects only; test: `frontend/e2e/demo_polish.spec.ts` "F05, F06, F07" (both themes, measured 3:1 or more).

### [P2] F06 Status colours outside the token set
- **Location:** `frontend/src/theme.css` `.prio-critical { color: #ff6b6b }`, `[data-theme="light"] .prio-critical` and `.state.error` `#b42318`
- **Category:** Theming
- **Impact:** Critical priority and error text bypass the tokens (contrast is fine: 5.95:1 dark, 6.57:1 light), so a later theme change can miss them.
- **Recommendation:** `--c-critical` token per theme.
- **Suggested command:** /impeccable polish
- **Status:** fixed: token `--c-critical` per theme for critical priority and error text; test: `frontend/e2e/demo_polish.spec.ts` "F05, F06, F07".

### [P3] F07 Decorative side-tab border on the Method page
- **Location:** `frontend/src/theme.css:237` `.method-version { border-left: 3px solid var(--c-quality) }` (impeccable detector: side-tab)
- **Category:** Implementation Integrity
- **Impact:** A blue bar that looks like a Quality status mark on a note that has nothing to do with water quality.
- **Recommendation:** a neutral panel (background + border) instead of the coloured bar.
- **Suggested command:** /impeccable polish
- **Status:** fixed: neutral note (panel background, 1 px border); detector now reports nothing; test: `frontend/e2e/demo_polish.spec.ts` "F05, F06, F07".

### [P3] F08 Some changing numbers are not tabular
- **Location:** `.conf` (node page "Confidence 0.69"), the Confidence column of the Alerts table, chart ticks
- **Category:** Performance / polish (layout shift)
- **Impact:** Values jump sideways by a pixel or two as they update during the replay.
- **Recommendation:** `font-variant-numeric: tabular-nums` on those.
- **Suggested command:** /impeccable polish
- **Status:** fixed: tabular figures on the node confidence, the Alerts Confidence column (right-aligned) and the chart ticks; test: `frontend/e2e/demo_polish.spec.ts` "F03, F04, F08".

## Patterns & Systemic Issues
- The two P1s are both "works with a mouse at desktop width": the map and the header were never driven by keyboard only or at 320 px. The browser tests now need a keyboard path and a 320 px check so this cannot come back.
- Small, scaled text: tick labels in SVG are sized in viewBox units without a floor.

## Positive Findings
- Colour + shape + word on every status (map, strip, badges, feed, charts' hatched/dotted/crossed shading); colour-blind safe palette.
- Visible 3 px focus ring on every focusable element; skip link first in the Tab order; logical order (nav, theme, replay controls, map, markers, feed).
- Live regions: the replay toast is announced through a hidden `role="status"`; the connection state is text, not only a dot.
- Contrast: every text token passes AA in both themes; the reduced-motion rule removes animation while the connection state stays readable as text.
- Data provenance always visible ("Demo network · fictional layout", "Simulated data", "Alerts: dry run").
- Phone width (390 px) has no sideways scroll since Round 7; long node names collapse to "4 · Bagayam" in tables.

## Recommended Actions
1. **[P1] `/impeccable harden`**: keyboard operation of the map markers (F01), then the paragraph label (F03).
2. **[P1] `/impeccable adapt`**: reflow at 320 px (F02).
3. **[P2] `/impeccable typeset`**: chart tick labels (F04, with F08).
4. **[P2] `/impeccable polish`**: control boundaries, critical colour token, Method note, tabular numbers (F05-F08).

## After the fixes (Round 8, P2/P3)
- All 8 findings fixed, each with a browser test in `frontend/e2e/demo_polish.spec.ts`; the accessibility spec now fails on any WCAG 2.1 A/AA violation and also scans the Complaints page (10 scans, 0 violations).
- impeccable detector on `frontend/src`: no finding.
- Left as is (no WCAG or demo impact, recorded for later): Leaflet's attribution links are 14 px high (a target-size rule exists only from WCAG 2.2); the theme and replay buttons use Unicode glyphs (sun, triangle) beside their text rather than drawn icons; status strip and alert cards keep their coloured left edge, which is a status colour paired with an icon and a word, not decoration.
