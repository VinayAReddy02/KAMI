import { type NodeLike, nodeLabel, nodeShort } from "../labels";

/** A node name where space is tight (table cells): the full numbered label, and on narrow screens (600 px or less) the
 * short "4 · Bagayam" instead. The full label stays readable for screen readers at every width. */
export function NodeName({ node, id }: { node?: NodeLike | null; id: string }) {
  return (
    <>
      <span className="node-name-full">{nodeLabel(node, id)}</span>
      <span className="node-name-short" aria-hidden="true">{nodeShort(node, id)}</span>
    </>
  );
}
