import { useMemo, useState } from "react";
import { fmtTs } from "../components/AlertList";
import { StatusBadge } from "../components/StatusBadge";
import { NodeName } from "../components/NodeName";
import { nodeIndex, nodeShort } from "../labels";
import { useLive } from "../live";
import { CATEGORIES, PRIORITIES } from "../types";

export function Alerts() {
  const { alerts, network, loading, networkError } = useLive();
  const [cat, setCat] = useState("");
  const [pri, setPri] = useState("");
  const [node, setNode] = useState("");
  const [status, setStatus] = useState("");
  const index = useMemo(() => nodeIndex(network?.nodes), [network]);
  const rows = alerts.filter(
    (a) => (!cat || a.category === cat) && (!pri || a.priority === pri) && (!node || a.node_id === node) && (!status || a.status === status),
  );
  return (
    <div className="alerts-page">
      <h1>Alerts</h1>
      <form className="filters" aria-label="Alert filters" onSubmit={(e) => e.preventDefault()}>
        <label>Category
          <select value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="">All</option>
            {CATEGORIES.filter((c) => c !== "Normal").map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label>Priority
          <select value={pri} onChange={(e) => setPri(e.target.value)}>
            <option value="">All</option>
            {PRIORITIES.map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        <label>Node
          <select value={node} onChange={(e) => setNode(e.target.value)}>
            <option value="">All</option>
            {network?.nodes.map((n) => <option key={n.id} value={n.id}>{nodeShort(n)}</option>)}
          </select>
        </label>
        <label>Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            <option value="active">Active</option>
            <option value="closed">Closed</option>
          </select>
        </label>
        <span className="count" role="status">{rows.length} of {alerts.length} alerts</span>
      </form>
      {loading && <p className="state" role="status">Loading alerts…</p>}
      {networkError && <p className="state error" role="alert">Could not load alerts: {networkError}</p>}
      {!loading && !networkError && rows.length === 0 && (
        <p className="state empty" role="status">No alerts match these filters.</p>
      )}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Status</th><th>Category / priority</th><th>Node</th><th>Started</th><th>Last update</th><th>Confidence</th><th>Explanation</th></tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td><span className={`alert-status ${a.status}`}>{a.status === "active" ? "Active" : "Closed"}</span></td>
                  <td><StatusBadge category={a.category} priority={a.priority} compact /></td>
                  <td><a className="link" href={`#/node/${a.node_id}`}><NodeName node={index[a.node_id]} id={a.node_id} /></a></td>
                  <td>{fmtTs(a.start_ts)}</td>
                  <td>{fmtTs(a.status === "active" ? a.last_ts : a.end_ts)}</td>
                  <td>{a.confidence == null ? "–" : a.confidence.toFixed(2)}</td>
                  <td className="expl">{a.explanation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
