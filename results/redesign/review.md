# Round 9 redesign: finish review record

The impeccable finish reviewer is an independent agent with no access to the build conversation. It judged the built dashboard against the direction contract (`.impeccable/surfaces/frontend-src-app-tsx.md`, direction "Tank Band", seed:83d4855761145007) from screenshots at 1440x900, 390 px, 1920x1080 and 1280x720, in both themes. The user allowed this agent and the documenter for Round 9. Code-led build: there is no approved comp, and the decision sketch `.impeccable/mocks/decision/assigned.html` was the critique reference.

| Round | Disposition | Summary |
|---|---|---|
| 1 | fix | 8 material fixes: the map did not keep all nodes in view; "Alerts: dry run" was below the fold; map tile colours competed with the state paint; charts did not share one time axis; status bands were not in the right column (and the count came after the word); the replay strip sat between title and explanation on the node page; closed rows were not struck in the Alerts table; Unicode arrows were used instead of drawn ones. Also four ceiling notes. |
| 1b | recapture | The evidence failed, not the build: map tiles were captured mid-fade or before loading, and the alert state differed from round 1. The capture now waits for every tile and for the review scenario (node-2 Infrastructure and node-5 Quality alerts both open, replay paused). |
| 2 | fix | 6 of 8 resolved. Map fit partial (a label covered another plate on phones). New regression A: ghosted tiles at 1440, caused by Leaflet's tile fade during capture and by the tile filters. Finding C (chart hatching) was raised. |
| 3 (final verdict) | fix | A resolved (tile fade off, half-step zoom, filters retuned). C withdrawn by the reviewer: shading follows each step's assessed category. Contract text resolved. B partial: on phones, markers with no free side for a label showed only the painted, numbered plate, with no state icon and word. |

**After the final verdict (not re-reviewed; two review rounds is the unattended budget).** Claude fixed B because it broke a binding rule (colour + icon + text for every status). A marker without room for its label now shows its state icon and word under the numbered plate, and label placement keeps that space free. Evidence: `.impeccable/review/mobile.png`. 45 Playwright tests (including the WCAG 2.1 AA scan, 320 px reflow and projector sizes) and 17 Vitest tests pass, and `impeccable detect` on `frontend/src` reports nothing. The reviewer has not scored this last change. Final recorded disposition: fix, with the one open item addressed after the review.

**Kept deliberately (the reviewer's keep list):** one painted, stencil-numbered band repeated across the map, the reversed most-urgent plate, the node page tile and the register; hatch, dot and cross patterns that carry state for colour-blind readers; the #f1f3ef and #0d1826 grounds.

**Known behaviour, unchanged by the redesign:** an alert stays open until its closing rule fires, while markers show the latest assessment. A marker can therefore read Normal next to an open alert.
