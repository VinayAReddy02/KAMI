---
name: KAMI
description: Anomaly intelligence for a water network, drawn as a row of painted municipal overhead tanks.
colors:
  limewash-ground: "#f1f3ef"
  limewash-strip: "#e4e8e1"
  limewash-panel: "#fbfcfa"
  limewash-rule: "#c8cec4"
  stencil-ink: "#16191d"
  stencil-ink-soft: "#485059"
  municipal-enamel: "#183a63"
  on-enamel: "#f1f3ef"
  on-enamel-soft: "#c9d6e6"
  link-blue: "#1c4f8c"
  focus-amber: "#b45309"
  control-border: "#6c7785"
  paint-normal: "#00785a"
  paint-infrastructure: "#9a5a00"
  paint-quality: "#0a6ea8"
  paint-combined: "#9b3f73"
  paint-critical: "#b42318"
  paint-closed: "#5f656e"
  night-ground: "#0d1826"
  night-strip: "#12213a"
  night-panel: "#152741"
  night-rule: "#2a3e5a"
  night-ink: "#e8edf3"
  night-ink-soft: "#a7b4c4"
  night-enamel: "#1f4878"
  night-link: "#8cc4f2"
  night-focus: "#ffd166"
  night-control-border: "#7690b2"
  night-text-normal: "#3fd0a5"
  night-text-infrastructure: "#f0a83a"
  night-text-quality: "#5ec0f2"
  night-text-combined: "#e08bbb"
  night-text-critical: "#ff7b72"
  night-button-primary: "#3a6ea8"
typography:
  node-poster:
    fontFamily: "Big Shoulders Stencil Display, Hind, system-ui, sans-serif"
    fontSize: "7.5rem"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "0.02em"
    fontFeature: "\"tnum\""
  wordmark:
    fontFamily: "Big Shoulders Stencil Display, Hind, system-ui, sans-serif"
    fontSize: "1.85rem"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "0.06em"
  plate-numeral:
    fontFamily: "Big Shoulders Stencil Display, Hind, system-ui, sans-serif"
    fontSize: "1.35rem"
    fontWeight: 800
    lineHeight: 1.15
    letterSpacing: "0.02em"
    fontFeature: "\"tnum\""
  headline:
    fontFamily: "Hind, Segoe UI, system-ui, sans-serif"
    fontSize: "1.45rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.005em"
  count:
    fontFamily: "Hind, Segoe UI, system-ui, sans-serif"
    fontSize: "1.7rem"
    fontWeight: 700
    lineHeight: 1
    fontFeature: "\"tnum\""
  body:
    fontFamily: "Hind, Segoe UI, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  section-label:
    fontFamily: "Hind, Segoe UI, system-ui, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 700
    lineHeight: 1.5
    letterSpacing: "0.08em"
  label:
    fontFamily: "Hind, Segoe UI, system-ui, sans-serif"
    fontSize: "0.88rem"
    fontWeight: 500
    lineHeight: 1.5
rounded:
  pattern: "2px"
  plate: "4px"
  marker: "5px"
  control: "6px"
  container: "8px"
  pill: "999px"
spacing:
  hairline: "0.3rem"
  tight: "0.45rem"
  row: "0.75rem"
  block: "0.9rem"
  column: "1.1rem"
  gutter: "1.25rem"
components:
  button:
    backgroundColor: "{colors.limewash-panel}"
    textColor: "{colors.stencil-ink}"
    rounded: "{rounded.control}"
    padding: "0.32rem 0.75rem"
    height: "2.1rem"
  button-hover:
    backgroundColor: "{colors.limewash-strip}"
  button-primary:
    backgroundColor: "{colors.municipal-enamel}"
    textColor: "{colors.on-enamel}"
    rounded: "{rounded.control}"
    padding: "0.32rem 0.75rem"
    height: "2.1rem"
  button-primary-night:
    backgroundColor: "{colors.night-button-primary}"
    textColor: "{colors.on-enamel}"
  select:
    backgroundColor: "{colors.limewash-panel}"
    textColor: "{colors.stencil-ink}"
    rounded: "{rounded.control}"
    padding: "0.32rem 0.75rem"
    height: "2.1rem"
  nav-tab:
    textColor: "{colors.on-enamel-soft}"
    rounded: "{rounded.control}"
    padding: "0.4rem 0.85rem"
  nav-tab-current:
    backgroundColor: "{colors.on-enamel}"
    textColor: "{colors.municipal-enamel}"
  provenance-pill:
    textColor: "{colors.on-enamel-soft}"
    rounded: "{rounded.pill}"
    padding: "0.1rem 0.65rem"
  plate-normal:
    backgroundColor: "{colors.paint-normal}"
    textColor: "#ffffff"
    typography: "{typography.plate-numeral}"
    rounded: "{rounded.plate}"
    padding: "0 0.3em"
  plate-infrastructure:
    backgroundColor: "{colors.paint-infrastructure}"
    textColor: "#ffffff"
    typography: "{typography.plate-numeral}"
    rounded: "{rounded.plate}"
  plate-quality:
    backgroundColor: "{colors.paint-quality}"
    textColor: "#ffffff"
    typography: "{typography.plate-numeral}"
    rounded: "{rounded.plate}"
  plate-combined:
    backgroundColor: "{colors.paint-combined}"
    textColor: "#ffffff"
    typography: "{typography.plate-numeral}"
    rounded: "{rounded.plate}"
  plate-closed:
    backgroundColor: "{colors.paint-closed}"
    textColor: "#ffffff"
    typography: "{typography.plate-numeral}"
    rounded: "{rounded.plate}"
  status-band:
    backgroundColor: "{colors.paint-normal}"
    textColor: "#ffffff"
    rounded: "{rounded.control}"
    padding: "0.3rem 0.75rem"
  status-badge:
    backgroundColor: "{colors.limewash-panel}"
    textColor: "{colors.stencil-ink}"
    rounded: "{rounded.pill}"
    padding: "0.1rem 0.6rem"
  urgent-plate:
    backgroundColor: "{colors.stencil-ink}"
    textColor: "{colors.limewash-ground}"
    rounded: "{rounded.container}"
    padding: "0.85rem 0.95rem"
  card:
    backgroundColor: "{colors.limewash-panel}"
    rounded: "{rounded.container}"
    padding: "0.95rem 1.1rem"
---

# Design System: KAMI

## Overview

**Creative North Star: "The Tank Band"**

Every sensor point is a municipal overhead water tank: its number stencilled in white on a painted band whose colour and pattern are its state. The same band appears on the map marker, on the node page as a poster-sized tile, in the status bands, on the most-urgent alert and at the head of every row of the alert register. An operator learns one object and reads it everywhere.

The ground is limewash (a cool off-white, never cream), the shell header is municipal-blue enamel, the ink is stencil black. The default theme is light, built for a daytime control room and a classroom projector; the night theme lays the same paints on deep tank-blue and draws a pale keyline round each painted band so it holds its edge on the dark ground. The density is that of an operations tool: full-width, tight vertical rhythm, every figure in tabular numerals. The world rejects the category default of neon status dots on a dark console beside a grid of white cards.

Hue is rationed. The map tiles are greyscale, the chrome is neutral or enamel blue, and the paint is the only colour that means anything. Because colour alone is never enough, every state also has a shape, a pattern and a word.

**Key Characteristics:**
- One painted, stencil-numbered band repeated on the map, the node page, the status bands, the urgent plate and the register.
- State is carried four times: paint colour, fill pattern (solid, hatched, dotted, crossed), shape icon (circle, triangle, diamond, octagon with an exclamation mark) and the word.
- Light limewash by default, deep tank-blue at night; the paints stay the same in both themes.
- Stencil type only for node numbers and the wordmark; Hind for every word and every count.
- Data provenance is always visible: "Demo network · fictional layout" in the header pill and on the map, "Alerts: dry run" in the header, "Simulated data" in the footer.

## Colors

A neutral limewash-and-enamel shell that holds back so that five state paints carry all of the meaning.

### Primary
- **Municipal-Blue Enamel** (municipal-enamel): the shell header band, the current tab's text, the primary "Inject event" button, the stencilled step numbers on the Method page and text selection. At night it lightens to the night enamel, and the primary button to its own lighter blue.

### Secondary
- **State Paints** (paint-normal green, paint-infrastructure ochre, paint-quality blue, paint-combined plum): fills for plates, map pins, status bands, evidence bars and legend swatches. Each carries white stencil numerals at 5.4:1 or more and stands off the limewash ground at 4.9:1 or more. The paints are identical in both themes.
- **Critical Red** (paint-critical): the Critical priority word and its bars. It is a priority, not a category, so it never paints a band.
- **Closed Grey** (paint-closed): the plate of a closed alert. Closed plates lose their pattern.

### Tertiary
- **State Text Colours**: on the light ground the state colour in text and icons equals its paint; at night each lifts to a brighter tone (night-text-normal, night-text-infrastructure, night-text-quality, night-text-combined, night-text-critical), all 5.9:1 or more on the night panel.
- **Focus Amber** (focus-amber, night-focus): the 3 px focus outline, and nothing else.

### Neutral
- **Limewash Ground** (limewash-ground): the page.
- **Limewash Strip** (limewash-strip): the replay strip, the footer, table headers, hover fills, empty tracks.
- **Limewash Panel** (limewash-panel): cards, charts, tables, controls, marker labels, badges.
- **Limewash Rule** (limewash-rule): decorative hairlines and dividers only, never the edge of a control.
- **Stencil Ink** (stencil-ink) and **Soft Ink** (stencil-ink-soft, 6.6:1 or more on every light ground): text and secondary text. The ink also fills the reversed urgent plate.
- **Control Border** (control-border): the 1 px edge of buttons and selects only, 3.6:1 or more on panel and strip.
- **Link Blue** (link-blue): underlined links.

### Named Rules
**The Paint Carries the Hue Rule.** Map tiles are filtered to greyscale (tinted tank-blue at night) so that on the map only the state paint has colour. No decorative colour enters the map or the status surfaces.

**The Four Carriers Rule.** Every status is shown as colour plus shape icon plus word, and a painted fill also carries its pattern: Normal solid with a circle, Infrastructure hatched with a triangle, Quality dotted with a diamond, Combined crossed with an octagon. A marker too crowded for its label still shows its state icon and word under the plate.

**The Measured Pair Rule.** A new foreground/background pair ships only with its contrast measured: 4.5:1 for text, 3:1 for control edges and non-text state, white numerals on paint at 5.4:1 or more.

## Typography

**Display Font:** Big Shoulders Stencil Display 800 (with Hind, system-ui)
**Body Font:** Hind 400 to 700 (with Segoe UI, system-ui), self-hosted, Devanagari-ready

**Character:** A municipal stencil for the painted numbers, a plain, sturdy Indic-ready sans for every word. The stencil is signage, never prose.

### Hierarchy
- **Node Poster** (stencil 800, 7.5rem, 3.8rem under 520 px): the node number on its own page; one subject owns the page.
- **Wordmark** (stencil 800, 1.85rem, 0.06em tracking): "KAMI" in the shell header.
- **Plate Numeral** (stencil 800, 1rem to 2.3rem by context): node numbers on plates, pins and register rows; tabular.
- **Headline** (Hind 700, 1.45rem; 2rem for the node name, 1.8rem on Method; line-height 1.2): page titles, balanced wrapping.
- **Count** (Hind 700, 1.7rem, tabular): the numbers in the status bands.
- **Body** (Hind 400, 15px/1.5): explanations, table cells (0.88rem), Method prose limited to 68ch.
- **Section Label** (Hind 700, 0.8rem, 0.08em tracking, uppercase, soft ink): the h2 that names a panel ("Most urgent", "Live alert feed", "Why"), chart captions and table headers (0.74rem). It is the panel's heading itself, never a tag placed above another heading.
- **Label** (Hind 500, 0.88rem): control labels, replay time, counts beside filters.

### Named Rules
**The Stencil Is for Numbers Rule.** Big Shoulders Stencil is used only for node numbers and the wordmark. Counts and every other figure are set in Hind: the stencil 0 reads as "()".

**The Tabular Figures Rule.** Every number that can change or align (counts, times, confidence, chart ticks, table numbers) uses tabular numerals.

## Layout

Full-width on every route: the header, the replay strip, the main area and the footer share a 1.25rem side gutter so their edges line up. The Overview is a two-column grid, the map taking the remaining width and a 380 px right column holding the four status bands (2 x 2, one column under 420 px), the reversed most-urgent alert, then the alert register, which scrolls within the viewport height. Under 960 px the columns stack and the map is capped at min(62vh, 460px).

The node page puts one subject first: the poster plate beside the node name and state, a "Why" card that splits explanation and evidence bars into two columns (one under 760 px), then the four signal charts as full-width rows on one shared time axis (the axis labels on the last row only), with onset shading patterned by assessed category, then the node's alerts. Tables sit in a bordered, horizontally scrolling wrapper with sticky headers. The layout reflows to 320 px; under 600 px node names shorten to their number form.

Rhythm runs on small rem steps (0.3, 0.45, 0.75, 0.9, 1.1 and 1.25rem); the vertical rhythm is tight, as suits an operations screen.

## Elevation & Depth

Mostly flat and tonal: the page, strip and panel are three close limewash tones divided by 1 px rules. One soft two-layer ambient shadow lifts only the things that sit on the map or must be found first: the map frame, map markers and their labels, the map provenance label and the urgent plate. At night the shadow deepens and painted bands gain a pale inset keyline instead of more shadow.

### Shadow Vocabulary
- **Map lift** (`0 1px 2px rgba(22,25,29,0.12), 0 4px 14px rgba(22,25,29,0.08)`; night `0 1px 2px rgba(0,0,0,0.4), 0 6px 18px rgba(0,0,0,0.3)`): map frame, markers, map labels, urgent plate.
- **Plate keyline** (`inset 0 0 0 1px`, transparent by day, `rgba(241,243,239,0.7)` at night): every painted band.

### Named Rules
**The Only Lift Is on the Map Rule.** Cards, charts and tables do not cast shadows; they are bordered panels. Shadow is reserved for objects laid over the map and for the urgent plate.

## Shapes

Gently squared. Plates and small tags use 4 px corners, map pins 5 px, controls and status bands 6 px, cards, charts, tables and the map frame 8 px; the node poster plate 8 px. The provenance pills and status badges are full pills (999 px) edged in 1 to 1.5 px of their colour. Patterns are small tiled SVGs in white at 30 to 38 % opacity: 8 px diagonal hatch, 8 px dot grid, 9 px cross. Complaint tickets on the map use a 2 px dashed ink outline to read as a different kind of object from a sensor plate.

## Components

### Buttons
Standard controls in the world's type: plain, legible, enamel only when primary.
- **Shape:** gently squared (6 px), minimum height 2.1rem, 1 px control border.
- **Default:** panel fill, ink text, Hind 600, optional 16 px drawn icon before the word.
- **Primary:** enamel fill and border, limewash text; at night the lighter night primary blue.
- **Hover / Focus:** hover shifts to the strip tone (primary to a lighter enamel); focus is a 3 px amber outline offset 2 px. Transitions are 0.15 s ease-out on colour only. Disabled at 55 % opacity.
- **In the header:** transparent with a translucent limewash border.

### Chips
- **Provenance pill:** a 1 px translucent limewash outline pill on the enamel header ("Demo network · fictional layout", "Fallback: in-process bus + SQLite"). "Alerts: dry run" sits beside it with a drawn log icon. These are never hidden.

### Status Badge
- **Style:** a pill on the panel edged in 1.5 px of the state colour: shape icon, the state word in ink, then for non-Normal states the priority as four rising bars plus the priority word (Critical in red, High in ochre).

### Cards / Containers
- **Corner Style:** 8 px.
- **Background:** panel, 1 px rule border, no shadow.
- **Internal Padding:** 0.95rem 1.1rem.

### Inputs / Fields
- **Style:** native selects styled as the buttons: panel fill, 1 px control border, 6 px corners, 2.1rem high, label in soft ink to the left.
- **Focus:** the shared amber outline.

### Navigation
- **Style:** tabs in the enamel header, Hind 600 in soft on-enamel text, 6 px corners. Hover adds a 10 % limewash wash; the current page is a reversed limewash tab with enamel text. Padding tightens under 400 px.

### The Band (signature)
The painted plate with a white stencilled number. Category class sets paint and pattern; closed alerts turn it grey and patternless. Sizes: register row 1.25rem, table cell 1rem, urgent plate 2.3rem, node poster 7.5rem.

### Map Marker
A 34 px painted pin joined to a panel label holding the locality (Hind 600) and the state icon and word. Labels are placed greedily from top to bottom: right of the pin, else left, else "bare", where the pin stands alone with its state icon and word on a small panel tag beneath it. Tile fade is off so the map never ghosts.

### Status Bands
Four bands in the right column, each painted in its state with a Hind count, shape icon and word in white. A state with no nodes turns to an unpainted panel band with a small swatch of its paint at the end.

### Urgent Plate
The single most urgent alert, reversed: ink fill, limewash text, an 8 px corner, the map lift shadow and a 2.3rem band. Exactly one per screen; hover lifts it 1 px.

### Alert Register
Rows divided by rules: band, node name, an "Active" (reversed ink) or "Closed" (outlined) uppercase tag, time range, explanation. Closed alerts stay in the register with the name struck through (1.5 px) and a grey plate; nothing is removed. The Alerts table strikes closed rows the same way.

### Signal Charts
Four full-width rows in one bordered panel: uppercase caption with the latest value at right, a 1.7 px ink line, rule-coloured axes, 13 px Hind ticks, onset shading hatched, dotted or crossed by category, and a legend row that names the patterns.

### Drawn Icons
One 16-unit grid, 1.75 stroke, round caps and joins, currentColor, always beside a word.

## Do's and Don'ts

### Do:
- **Do** draw every status as paint colour plus pattern plus shape icon plus word, including on a crowded map.
- **Do** set node numbers in Big Shoulders Stencil 800 in white on paint, and every count and word in Hind.
- **Do** keep map tiles greyscale (tank-blue tinted at night) and tile fade off.
- **Do** give only the single most urgent alert the reversed ink plate.
- **Do** strike closed alerts through and keep them in the register and the table.
- **Do** keep the provenance labels ("Demo network · fictional layout", "Alerts: dry run", "Simulated data") visible on every route and in both themes.
- **Do** keep the control border on buttons and selects only, and measure every new colour pair to WCAG 2.1 AA.
- **Do** stack the signal charts as full-width rows on one shared time axis.

### Don't:
- **Don't** show a status by colour alone, or a painted plate without its state icon and word nearby.
- **Don't** set counts or prose in the stencil face.
- **Don't** add hue to the chrome, the map tiles or the panels; the paint is the only colour with meaning.
- **Don't** reverse more than one alert on a screen.
- **Don't** remove closed alerts from view.
- **Don't** fall back to neon status dots on a dark console beside a grid of white cards.
- **Don't** use typed Unicode arrows or glyphs as icons; use the drawn 16-unit icons.
