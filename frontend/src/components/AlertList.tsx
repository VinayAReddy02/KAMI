import type { Alert } from "../types";
import { StatusBadge } from "./StatusBadge";

export function fmtTs(ts: string | null | undefined): string {
  if (!ts) return "–";
  return ts.replace("T", " ").slice(0, 16);
}

interface Props {
  alerts: Alert[];
  nodeNames?: Record<string, string>;
  loading?: boolean;
  error?: string | null;
  limit?: number;
  onSelect?: (nodeId: string) => void;
}

export function AlertList({ alerts, nodeNames = {}, loading = false, error = null, limit = 12, onSelect }: Props) {
  if (loading) return <p className="state" role="status">Loading alerts…</p>;
  if (error) return <p className="state error" role="alert">Could not load alerts: {error}</p>;
  if (alerts.length === 0) {
    return (
      <p className="state empty" role="status">
        No alerts yet. Everything is within normal behaviour. Use “Inject event” to simulate one.
      </p>
    );
  }
  return (
    <ul className="alert-list" aria-label="Live alert feed">
      {alerts.slice(0, limit).map((a) => (
        <li key={a.id} className={`alert-item cat-${a.category.toLowerCase()}`}>
          <button type="button" onClick={() => onSelect?.(a.node_id)} aria-label={`Open ${nodeNames[a.node_id] ?? a.node_id}`}>
            <div className="alert-head">
              <StatusBadge category={a.category} priority={a.priority} compact />
              <span className="alert-node">{nodeNames[a.node_id] ?? a.node_id}</span>
              <span className={`alert-status ${a.status}`}>{a.status === "active" ? "Active" : "Closed"}</span>
            </div>
            <div className="alert-time">
              {fmtTs(a.start_ts)} → {a.status === "active" ? "ongoing" : fmtTs(a.end_ts)}
            </div>
            <div className="alert-text">{a.explanation}</div>
          </button>
        </li>
      ))}
    </ul>
  );
}
