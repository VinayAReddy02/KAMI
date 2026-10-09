# Decisions log

Decided decisions are not to be re-opened. Add new ones at the bottom with: what, why, alternatives. Items under "Proposed" are ideas for the user; do not build them.

## Decided by the user (2026-10-10)
1. **Direction:** Track A only: sensor anomaly intelligence (flow, pressure, turbidity, TDS). The senior's chatbot (Water Access Navigator) is a reference for related work only and is not rebuilt. Not a single line of his code is reused.
2. **Team:** solo project. The second name on the report is a teammate on paper only.
3. **No hardware.** All data is public datasets, with a virtual sensor node replaying it over MQTT.
4. **Datasets:** alternatives are allowed when an original is unobtainable; log each substitution and add "revisit original dataset" to *Needs user* in PROGRESS.md.
5. **Fusion design:** Claude Code chooses by validation performance (see PLAN.md Step 5).
6. **Frontend:** React + TypeScript, dark operations-console theme with a light toggle.
7. **Map:** fictional network of about 8 nodes on real map tiles near Vellore, labelled as demo coordinates.
8. **Permissions:** allow-list in `.claude/settings.json` plus auto-approved file edits. Pushing and recursive deletes are denied.
9. **Docker:** unsure if installed. Check at Step 1; fall back to SQLite and an in-process bus if absent.
10. **Missing Node.js:** install via `winget install OpenJS.NodeJS.LTS`. Docker is never installed automatically.
11. **Downloads:** no cap (keep at least 5 GB disk free).
12. **Stop point:** after Step 7. The paper (ACM template, structure following the NeuroChat sample) is written with the user afterwards.

## Context
- The faculty feedback asks for originality and for avoiding already-implemented benchmark techniques. Baselines are used only for comparison; the contribution is the staged contextual fusion and its ablations.
- The first-phase report says combined fusion should be tested on synchronised data. With no hardware, fusion is tested on **semi-synthetic scenarios** (events injected into real background series). This must be stated everywhere results are shown.

## Proposed (not approved; do not build)
- (none yet)

## Log of decisions made during the build
(append here)

### Step 0 (2026-10-10)
- **Infrastructure data = BattLeDIM (simulated L-Town, 5-min).** Why: reachable, CC-BY, exact leak labels. Alternatives: LeakDB, BATADAL (reachable, not needed); Babela (not confirmed). Labelled `semi_synthetic` everywhere because README states it is generated from a hydraulic model.
- **Quality data = USGS NWIS stations 01654000, 01646305, 01654500, 2021-2022, 15-min.** Why: real, public domain, long, gap-light. They are streams, not distribution networks, and unlabelled; caveat stated in docs.
- **BattLeDIM leaks overlap continuously** (2019: an active leak in every row), so Step 2 must label event windows from each leak's start time (and peak/end), not "any leak flow > 0". Proposal for Step 2: label an event while that leak's flow exceeds a small detectable fraction of its peak.
- Only 2 flow-sensor-years of 3 sensors exist, so flow is sparse vs 33 pressure sensors; node assignment (Step 1) must document this.
- Git repo and `.venv` created in Step 0 (needed to run the check script); pandas installed there.

### Step 1 (2026-10-10)
- Tool versions: Python 3.12.6, Node 24.14.1, npm 11.11.0, git 2.54.0, Docker absent -> fallback profile (SQLite + in-process bus). Why in-process bus forces a single-process stack; alternatives (a local TCP broker) rejected as out of scope.
- Node assignment: pressure = 8 evenly spaced BattLeDIM 2018 sensors; flow = 3 BattLeDIM flow sensors reused (i mod 3); turbidity/TDS = USGS station (i mod 3) with per-node time offset, TDS = 0.64 x conductance. Node series are `semi_synthetic`.
- Readings keep BattLeDIM 2018 timestamps (replayed), 5-min step; speed 600 = 0.5 s per step.
