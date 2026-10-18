---
version: 1
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: ["frontend/src/pages/Overview.tsx","frontend/src/pages/NodeDetail.tsx","frontend/src/pages/Alerts.tsx","frontend/src/pages/Complaints.tsx","frontend/src/pages/Method.tsx"]
---

# KAMI dashboard (all routes)

**Scope and mode:** the operator dashboard, every route (Overview, Node detail, Alerts, Complaints, Method), shared header, replay controls and footer. Mode: Operate. Code-led (no image generation in this harness).

**Audience and job:** a water-utility control-room operator on shift: which node, what kind of problem (infrastructure, quality, both), how urgent, why. Also shown live at the viva on a laptop and a projector.

**Constraints:** every status as colour + icon + text; the map is a core view; light/dark toggle; WCAG 2.1 AA; data-provenance labels always visible; behaviour, roles and accessible names unchanged; no new features. Must not look generic.

**Chosen direction:** Tank Band (assigned by the roll; the user was away and had asked Claude to proceed, so the decision page closed without a choice; alternates kept in `.impeccable/mocks/decision/`).

## Direction contract
THESIS: Every sensor point is a municipal overhead tank: its number stencilled on a painted band whose colour and pattern are its state, the same band on the map, the node page and the alert register. Refuses the category default of neon status dots on a dark console beside a grid of white cards.

OWN-WORLD: Limewash ground (cool off-white, never cream) with municipal-blue enamel for the shell header; stencil-black ink; Big Shoulders Stencil only for node numbers and the wordmark (counts in Hind: the stencil 0 reads as "()"; amended after the finish review); Hind for every word (Devanagari-ready). State paint: green Normal (solid), ochre Infrastructure (hatched), blue Quality (dotted), plum Combined (crossed), each with its shape icon and its word. Night theme: the same bands on deep tank-blue.

STORY: The operator reads the network as a row of painted tanks, sees the one band that changed, opens it, and reads why in plain words; closed alerts stay in the register, struck through.

FIRST VIEWPORT: Municipal-blue header (KAMI stencil wordmark, tabs, provenance pill, live state, theme toggle); replay strip below; the map fills the left two thirds with band markers (stencil number + locality + state); right column: four status bands with stencilled counts, the single most urgent alert on a reversed plate, then the alert register; provenance footer.

FORM: candidate 5 of 7 grounded worlds (painted municipal overhead water tanks); seed:83d4855761145007. Raises: poster-scale node number on its page (Metro Tiles); rank by weight, case and reversal, only the top alert reversed (Timetable Slide Rack); closed alerts struck, never removed (Ticket Wallet); charts share one time axis and onset mark (Botanical Folio); one subject owns the node page (Vertical Feed).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
