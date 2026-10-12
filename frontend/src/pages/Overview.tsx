import { useMemo } from "react";
import { AlertList } from "../components/AlertList";
import { NodeMap } from "../components/NodeMap";
import { StatusStrip } from "../components/StatusStrip";
import { useComplaints } from "../complaints";
import { useLive } from "../live";
import { CATEGORIES, type Category } from "../types";

export function Overview() {
  const { network, networkError, loading, latest, alerts, refresh } = useLive();
  const { complaints } = useComplaints();
  const names = useMemo(() => Object.fromEntries((network?.nodes ?? []).map((n) => [n.id, n.name])), [network]);
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
        <StatusStrip counts={counts} total={network.nodes.length} />
        <NodeMap network={network} latest={latest} onSelect={go} complaints={complaints.filter((c) => c.status === "open")}
          onComplaint={() => (window.location.hash = "#/complaints")} />
      </div>
      <aside className="overview-feed" aria-label="Alerts">
        <h2>Live alert feed</h2>
        <AlertList alerts={alerts} nodeNames={names} onSelect={go} limit={14} />
        <a className="link" href="#/alerts">All alerts →</a>
      </aside>
    </div>
  );
}
