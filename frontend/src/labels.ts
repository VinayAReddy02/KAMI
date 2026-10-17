// Node labels for every place the dashboard names a node (Round 7). The only source of these strings in the frontend;
// they are built from the fields the API adds (number, ward, ward_name) and match src/kami/live/labels.py:
//   nodeLabel -> "Bagayam Booster (node-4 · Ward 4)"   nodeShort -> "4 · Bagayam"
export const SEP = " · ";

export interface NodeLike {
  id: string;
  name?: string | null;
  number?: number | null;
  ward?: number | null;
  ward_name?: string | null;
}

export function nodeLabel(n: NodeLike | undefined | null, fallbackId = ""): string {
  if (!n) return fallbackId;
  if (!n.name) return n.id;
  return n.ward != null ? `${n.name} (${n.id}${SEP}Ward ${n.ward})` : `${n.name} (${n.id})`;
}

export function nodeShort(n: NodeLike | undefined | null, fallbackId = ""): string {
  if (!n) return fallbackId;
  const place = n.ward_name ?? n.name ?? n.id;
  return n.number != null ? `${n.number}${SEP}${place}` : place;
}

/** id -> node, for places that only have a node id (alerts). */
export function nodeIndex(nodes: NodeLike[] | undefined): Record<string, NodeLike> {
  return Object.fromEntries((nodes ?? []).map((n) => [n.id, n]));
}

/** Full labels by node id (unknown ids stay as they are). */
export function labelsById(nodes: NodeLike[] | undefined): Record<string, string> {
  return Object.fromEntries((nodes ?? []).map((n) => [n.id, nodeLabel(n)]));
}
