import { CATEGORIES, type Category } from "../types";
import { CategoryIcon } from "./StatusBadge";

export function StatusStrip({ counts, total }: { counts: Partial<Record<Category, number>>; total: number }) {
  return (
    <div className="status-strip" role="group" aria-label="Nodes per category">
      {CATEGORIES.map((c) => (
        <div key={c} className={`strip-item cat-${c.toLowerCase()}`}>
          <CategoryIcon category={c} size={18} />
          <span className="strip-count">{counts[c] ?? 0}</span>
          <span className="strip-label">{c}</span>
        </div>
      ))}
      <div className="strip-total">{total} nodes</div>
    </div>
  );
}
