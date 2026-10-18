import { CATEGORIES, type Category } from "../types";
import { CategoryIcon } from "./StatusBadge";

/** The network at a glance: one painted band per state with its count stencilled; a state with no node stays unpainted. */
export function StatusStrip({ counts, total }: { counts: Partial<Record<Category, number>>; total: number }) {
  return (
    <div className="status-strip" role="group" aria-label="Nodes per category">
      {CATEGORIES.map((c) => {
        const n = counts[c] ?? 0;
        return (
          <div key={c} className={`strip-item cat-${c.toLowerCase()}${n === 0 ? " empty" : ""}`}>
            <span className="strip-count">{n}</span>
            <CategoryIcon category={c} size={16} />
            <span className="strip-label">{c}</span>
          </div>
        );
      })}
      <div className="strip-total">{total} nodes</div>
    </div>
  );
}
