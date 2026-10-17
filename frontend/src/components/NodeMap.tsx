import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { MapContainer, Marker, TileLayer } from "react-leaflet";
import { nodeLabel, nodeShort } from "../labels";
import type { Assessment, Category, Complaint, Network } from "../types";

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
export function markerIcon(name: string, category: Category, priority?: string): L.DivIcon {
  const cat = category.toLowerCase();
  return L.divIcon({
    className: "node-marker-wrap",
    iconSize: [150, 44],
    iconAnchor: [14, 14],
    html: `<div class="node-marker cat-${cat}"><span class="pin"><svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">${GLYPH[category]}</svg></span><span class="pin-label"><b>${esc(name)}</b><small>${category}${priority && category !== "Normal" ? " · " + priority : ""}</small></span></div>`,
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

interface Props {
  network: Network;
  latest: Record<string, Assessment>;
  onSelect: (id: string) => void;
  complaints?: Complaint[];
  onComplaint?: () => void;
}

export function NodeMap({ network, latest, onSelect, complaints = [], onComplaint }: Props) {
  return (
    <div className="map-shell">
      <MapContainer center={network.center} zoom={network.zoom} className="map" scrollWheelZoom aria-label="Map of demo network nodes">
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {network.nodes.map((n) => {
          const a = latest[n.id] ?? n.latest;
          const cat: Category = a?.category ?? "Normal";
          return (
            <Marker
              key={n.id}
              position={[n.lat, n.lon]}
              icon={markerIcon(nodeShort(n), cat, a?.priority)}
              title={`${nodeLabel(n)}: ${cat}${a && cat !== "Normal" ? ", " + a.priority + " priority" : ""}`}
              eventHandlers={{ click: () => onSelect(n.id) }}
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
            eventHandlers={{ click: () => onComplaint?.() }}
          />
        ))}
      </MapContainer>
      <div className="map-label" role="note">{network.label}</div>
    </div>
  );
}
