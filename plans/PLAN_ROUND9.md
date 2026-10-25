# KAMI Round 9: full redesign of the dashboard

Decided by the user 2026-10-18: a full redesign of the dashboard with the impeccable plugin (new-work flow) and the make-interfaces-feel-better skill. The pinned look is released; still binding: colour + icon + text on every status, the map as a core view, a light/dark toggle, WCAG 2.1 AA, the data-provenance labels. Scope: the whole dashboard (5 pages, header, replay controls, footer). Must not look generic. The impeccable finish-reviewer and documenter agents are allowed for this round. Mode: Operate; code-led (no image generation in this harness).

Out of scope: backend, API, models, data, results other than screenshots and the accessibility report, the Telegram bot, Hindi, new features. Behaviour stays identical.

## Tasks
- **R0** scope record, `scripts/check_round9.py`, released brief in CLAUDE.md and PRODUCT.md.
- **R1** direction round: mechanism, scene, rut, seven grounded worlds, `impeccable concept-seed --scope direction --mode operate`, challenger verdicts, decision page for the user; direction contract in the surface brief. (The user was away when the round opened and told Claude to proceed: the assigned direction is built unless the user picks another on the decision page.)
- **R2** build, code-led, full commitment: tokens, type, icons, every component and page in the new world; behaviour, roles and names kept.
- **R3** inspect (1440, 390, 1920/1280, 320; both themes; all states), detector, finish reviewer (max two fix rounds), documenter writes DESIGN.md and `.impeccable/design.json`.
- **R4** build, Vitest, all Playwright specs (AA scan zero), screenshots regenerated, check_round9, decisions/PROGRESS/CLAUDE, commit, push per rule 6. STOP.
