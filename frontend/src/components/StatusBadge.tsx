import type { Category, Priority } from "../types";

// Status is never colour alone: every category has its own shape, a colour and a text label.
const SHAPES: Record<Category, JSX.Element> = {
  Normal: <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="2" />,
  Infrastructure: <path d="M8 1.5 15 14H1z" fill="currentColor" />,
  Quality: <path d="M8 1 15 8 8 15 1 8z" fill="currentColor" />,
  Combined: <path d="M5 1h6l4 4v6l-4 4H5l-4-4V5z M8 4.5v4 M8 10.2v1.3" fill="currentColor" stroke="var(--on-status)" strokeWidth="1.6" />,
};

export function CategoryIcon({ category, size = 16 }: { category: Category; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      {SHAPES[category]}
    </svg>
  );
}

export function StatusBadge({ category, priority, compact = false }: { category: Category; priority?: Priority; compact?: boolean }) {
  const label = priority && category !== "Normal" ? `${category}, ${priority} priority` : category;
  return (
    <span className={`badge cat-${category.toLowerCase()}${compact ? " compact" : ""}`} role="status" aria-label={label}>
      <CategoryIcon category={category} size={compact ? 12 : 14} />
      <span className="badge-text">{category}</span>
      {priority && category !== "Normal" && <PriorityTag priority={priority} />}
    </span>
  );
}

const LEVEL: Record<Priority, number> = { Low: 1, Medium: 2, High: 3, Critical: 4 };

export function PriorityTag({ priority }: { priority: Priority }) {
  return (
    <span className={`prio prio-${priority.toLowerCase()}`} title={`${priority} priority`}>
      <span className="prio-bars" aria-hidden="true">
        {[1, 2, 3, 4].map((i) => (
          <i key={i} className={i <= LEVEL[priority] ? "on" : ""} />
        ))}
      </span>
      <span>{priority}</span>
    </span>
  );
}
