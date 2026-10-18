import { useMemo } from "react";
import { AlertList, fmtTs, numberOf } from "../components/AlertList";
import { ArrowIcon } from "../components/Icons";
import { StatusBadge } from "../components/StatusBadge";
import { NodeMap } from "../components/NodeMap";
import { StatusStrip } from "../components/StatusStrip";
import { useComplaints } from "../complaints";
import { labelsById } from "../labels";
import { useLive } from "../live";
import { CATEGORIES, type Alert, type Category, type Priority } from "../types";

const RANK: Record<Priority, number> = { Critical: 4, High: 3, Medium: 2, Low: 1 };

/** The single most urgent open alert: highest priority, then the most recent. */
function mostUrgent(alerts: Alert[]): Alert | undefined {
  return alerts.filter((a) => a.status === "active").sort((a, b) => RANK[b.priority] - RANK[a.priority] || b.last_ts.localeCompare(a.last_ts))[0];
}

export function Overview() {
  const { network, networkError, loading, latest, alerts, refresh } = useLive();
  const { complaints } = useComplaints();
  const names = useMemo(() => labelsById(network?.nodes), [network]);
  const counts = useMemo(() => {
    const c: Partial<Record<Category, number>> = {};
    CATEGORIES.forEach((k) => (c[k] = 0));
    (network?.nodes ?? []).forEach((n) => {
      const a = latest[n.id] ?? n.latest;
      const k: Category = a?.category ?? "Normal";
      c[k] = (c[k] ?? 0) + 1;
    });
    return c;
  }, [network, latest]);
  const urgent = useMemo(() => mostUrgent(alerts), [alerts]);
  const go = (id: string) => {
    window.location.hash = `#/node/${id}`;
  };

  if (loading) return <p className="state page-state" role="status">Connecting to the KAMI service…</p>;
  if (networkError || !network)
    return (
      <div className="state error page-state" role="alert">
        <p>Could not reach the KAMI service: {networkError ?? "no data"}.</p>
        <button type="button" className="btn" onClick={refresh}>Retry</button>
      </div>
    );
  return (
    <div className="overview">
      <h1 className="sr-only">Network overview</h1>
      <div className="overview-map">
        <NodeMap network={network} latest={latest} onSelect={go} complaints={complaints.filter((c) => c.status === "open")}
          onComplaint={() => (window.location.hash = "#/complaints")} />
      </div>
      <aside className="overview-feed" aria-label="Alerts">
        <StatusStrip counts={counts} total={network.nodes.length} />
        {urgent && (
          <section aria-label="Most urgent alert">
            <h2>Most urgent</h2>
            <a className="urgent" href={`#/node/${urgent.node_id}`}>
              <span className={`plate cat-${urgent.category.toLowerCase()}`} aria-hidden="true">{numberOf(urgent)}</span>
              <span>
                <span className="u-node">{names[urgent.node_id] ?? urgent.node_id}</span>
                <span className="u-meta">
                  <StatusBadge category={urgent.category} priority={urgent.priority} compact /> · since {fmtTs(urgent.start_ts).slice(11)}
                  {urgent.confidence != null && <> · confidence {urgent.confidence.toFixed(2)}</>}
                </span>
                <span className="u-text">{urgent.explanation}</span>
              </span>
            </a>
          </section>
        )}
        <h2>Live alert feed</h2>
        <AlertList alerts={alerts} nodeNames={names} onSelect={go} limit={14} />
        <a className="link" href="#/alerts">All alerts <ArrowIcon /></a>
      </aside>
    </div>
  );
}
