import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useMemo, useState } from "react";
import { MapContainer, Marker, TileLayer, useMap } from "react-leaflet";
import { nodeLabel, nodeNumber, nodeShort } from "../labels";
import type { Assessment, Category, Complaint, Network } from "../types";

/** Leaflet makes markers focusable buttons, but Enter only opens a popup (KAMI has none): act on Enter and Space like a click. */
function onKey(act: () => void) {
  return (e: L.LeafletEvent) => {
    const k = (e as L.LeafletKeyboardEvent).originalEvent;
    if (k.key === "Enter" || k.key === " ") {
      k.preventDefault();
      act();
    }
  };
}

const GLYPH: Record<Category, string> = {
  Normal: '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="2"/>',
  Infrastructure: '<path d="M8 1.5 15 14H1z" fill="currentColor"/>',
  Quality: '<path d="M8 1 15 8 8 15 1 8z" fill="currentColor"/>',
  Combined: '<path d="M5 1h6l4 4v6l-4 4H5l-4-4V5z" fill="currentColor"/><path d="M8 4.5v4M8 10.2v1.3" stroke="#000" stroke-width="1.6"/>',
};

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}

/** `name` is the short numbered label ("4 · Bagayam"); the full label goes into the marker title. */
/** `side`: where the label sits (left or right of the plate, or no label when neither side is free). */
export function markerIcon(name: string, category: Category, priority?: string, num?: string, side: "right" | "left" | "bare" = "right"): L.DivIcon {
  const flip = side === "left";
  const cat = category.toLowerCase();
  return L.divIcon({
    className: `node-marker-wrap${flip ? " flip" : ""}${side === "bare" ? " bare" : ""}`,
    iconSize: [170, 40],
    iconAnchor: flip ? [153, 14] : [17, 14],
    html: `<div class="node-marker cat-${cat}"><span class="pin" aria-hidden="true">${esc(num ?? "")}</span><span class="pin-state"><svg viewBox="0 0 16 16" width="10" height="10" aria-hidden="true">${GLYPH[category]}</svg>${category === "Infrastructure" ? "Infra" : category}</span><span class="pin-label"><b>${esc(name)}</b><small><svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true">${GLYPH[category]}</svg>${category}${priority && category !== "Normal" ? " · " + priority : ""}</small></span></div>`,
  });
}

/** A citizen report: a square marker with a camera glyph and the ticket number (shape and text, not colour, tell it apart). */
export function ticketIcon(id: number): L.DivIcon {
  return L.divIcon({
    className: "node-marker-wrap",
    iconSize: [110, 30],
    iconAnchor: [13, 13],
    html: `<div class="ticket-marker"><span class="pin"><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M2 5h3l1-1.500h4L11 5h3v8H2z" fill="none" stroke="currentColor" stroke-width="1.500"/><circle cx="8" cy="9" r="2.200" fill="currentColor"/></svg></span><span class="pin-label"><b>Report #${id}</b></span></div>`,
  });
}

/** Keeps every node in view: fits the map to the nodes' bounds (labels extend to the right of each pin) and refits on resize. */
function FitNodes({ points }: { points: [number, number][] }) {
  const map = useMap();
  const key = points.map((p) => p.join(",")).join("|");
  useEffect(() => {
    if (points.length === 0) return;
    const bounds = L.latLngBounds(points);
    const fit = () => {
      const w = map.getSize().x; // room on the right for the labels, in proportion to the map (narrow maps would crowd the pins)
      map.fitBounds(bounds, { paddingTopLeft: [40, 30], paddingBottomRight: [Math.round(Math.min(150, Math.max(40, w * 0.1))), 40], maxZoom: 14, animate: false });
    };
    fit();
    map.on("resize", fit);
    return () => {
      map.off("resize", fit);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key]);
  return null;
}

type Side = "right" | "left" | "bare";

/** Places each node's label greedily (top to bottom): right of the plate, else left, else none ("bare": only the
 * numbered, painted plate; the full label stays in the marker's title). A label may not cover any plate, another
 * placed label or leave the map, so every plate number stays readable. Rerun after every move. */
function LabelSides({ ids, points, labels, onChange }: { ids: string[]; points: [number, number][]; labels: string[]; onChange: (f: Record<string, Side>) => void }) {
  const map = useMap();
  const key = points.map((p) => p.join(",")).join("|") + labels.join("|");
  useEffect(() => {
    const run = () => {
      const width = map.getSize().x;
      const px = points.map((p) => map.latLngToContainerPoint(p));
      const plate = (i: number) => ({ l: px[i].x - 30, r: px[i].x + 30, t: px[i].y - 15, b: px[i].y + 38 }); // plate plus room for a state word under it
      const hit = (u: { l: number; r: number; t: number; b: number }, v: { l: number; r: number; t: number; b: number }) => u.l < v.r && v.l < u.r && u.t < v.b && v.t < u.b;
      const placed: { l: number; r: number; t: number; b: number }[] = [];
      const out: Record<string, Side> = {};
      const order = px.map((_, i) => i).sort((i, j) => px[i].y - px[j].y || px[i].x - px[j].x);
      for (const i of order) {
        const w = Math.min(160, Math.max(90, labels[i].length * 7.2 + 26)); // the label's width: name plus padding
        const right = { l: px[i].x + 17, r: px[i].x + 17 + w, t: px[i].y - 15, b: px[i].y + 23 };
        const left = { l: px[i].x - 17 - w, r: px[i].x - 17, t: px[i].y - 15, b: px[i].y + 23 };
        const free = (box: typeof right) => box.l >= 0 && box.r <= width && !placed.some((q) => hit(box, q)) && !px.some((_, j) => j !== i && hit(box, plate(j)));
        const side: Side = free(right) ? "right" : free(left) ? "left" : "bare";
        if (side !== "bare") placed.push(side === "right" ? right : left);
        out[ids[i]] = side;
      }
      onChange(out);
    };
    run();
    map.on("zoomend moveend resize", run);
    return () => {
      map.off("zoomend moveend resize", run);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key]);
  return null;
}

interface Props {
  network: Network;
  latest: Record<string, Assessment>;
  onSelect: (id: string) => void;
  complaints?: Complaint[];
  onComplaint?: () => void;
}

export function NodeMap({ network, latest, onSelect, complaints = [], onComplaint }: Props) {
  const points = useMemo(() => network.nodes.map((n) => [n.lat, n.lon] as [number, number]), [network]);
  const ids = useMemo(() => network.nodes.map((n) => n.id), [network]);
  const shorts = useMemo(() => network.nodes.map((n) => nodeShort(n)), [network]);
  const [sides, setSides] = useState<Record<string, Side>>({});
  const onSides = (f: Record<string, Side>) => setSides((old) => (JSON.stringify(old) === JSON.stringify(f) ? old : f));
  return (
    <div className="map-shell">
      <MapContainer center={network.center} zoom={network.zoom} zoomSnap={0.5} zoomDelta={0.5} fadeAnimation={false} className="map" scrollWheelZoom aria-label="Map of demo network nodes">
        <FitNodes points={points} />
        <LabelSides ids={ids} points={points} labels={shorts} onChange={onSides} />
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {network.nodes.map((n) => {
          const a = latest[n.id] ?? n.latest;
          const cat: Category = a?.category ?? "Normal";
          return (
            <Marker
              key={n.id}
              position={[n.lat, n.lon]}
              icon={markerIcon(nodeShort(n), cat, a?.priority, nodeNumber(n), sides[n.id] ?? "right")}
              title={`${nodeLabel(n)}: ${cat}${a && cat !== "Normal" ? ", " + a.priority + " priority" : ""}`}
              eventHandlers={{ click: () => onSelect(n.id), keydown: onKey(() => onSelect(n.id)) }}
            />
          );
        })}
        {complaints.map((c) => (
          <Marker
            key={`ticket-${c.id}`}
            position={[c.lat, c.lon]}
            icon={ticketIcon(c.id)}
            zIndexOffset={600}
            title={`Citizen report ${c.id}, ${c.status}${c.node_id ? ", nearest sensor point " + nodeLabel({ id: c.nearest_node_id, name: c.nearest_node_name, number: c.node_number, ward: c.ward }) : ""}`}
            eventHandlers={{ click: () => onComplaint?.(), keydown: onKey(() => onComplaint?.()) }}
          />
        ))}
      </MapContainer>
      <div className="map-label" role="note">{network.label}</div>
    </div>
  );
}
