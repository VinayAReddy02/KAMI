import { StatusBadge } from "../components/StatusBadge";
import { useComplaints } from "../complaints";
import type { Complaint } from "../types";

function when(c: Complaint): string {
  return c.created_utc.replace("T", " ").slice(0, 16) + " UTC";
}

function sensorState(c: Complaint) {
  if (!c.in_demo_area) return <span className="muted">not linked (outside the demo area)</span>;
  if (!c.node_category) return <span className="muted">not available</span>;
  return <StatusBadge category={c.node_category} priority={c.node_priority ?? undefined} compact />;
}

export function Complaints() {
  const { complaints, loading, error } = useComplaints();
  return (
    <div className="complaints">
      <h1>Complaints</h1>
      <p className="note" role="note">
        Pipe-damage reports sent by citizens to the Telegram bot: a photo and a location. Each report is linked to the nearest sensor point. The photos are
        stored for staff; <strong>nothing analyses them automatically</strong>. Demo system with a fictional network layout.
      </p>
      {loading && <p className="state" role="status">Loading complaints…</p>}
      {error && complaints.length === 0 && <p className="state error" role="alert">Could not load complaints: {error}</p>}
      {!loading && !error && complaints.length === 0 && (
        <p className="state empty" role="status">No complaints yet. A citizen can send a photo and a location to the bot.</p>
      )}
      {complaints.length > 0 && (
        <>
          <p className="count" role="status">{complaints.length} {complaints.length === 1 ? "report" : "reports"}</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Photo</th><th>Ticket</th><th>Reported</th><th>Nearest sensor point</th><th>Sensors at the time of the report</th><th>Status</th></tr>
              </thead>
              <tbody>
                {complaints.map((c) => (
                  <tr key={c.id}>
                    <td><img className="thumb" src={c.thumb_url} alt={`Photo sent with report ${c.id}`} loading="lazy" width={96} height={72} /></td>
                    <td><strong>#{c.id}</strong>{c.source === "test" && <span className="tag">test data</span>}</td>
                    <td>{when(c)}{c.replay_ts && <small className="muted"> · replay {c.replay_ts.replace("T", " ").slice(0, 16)}</small>}</td>
                    <td>
                      {c.node_id ? <a className="link" href={`#/node/${c.node_id}`}>{c.node_name}</a> : <span>{c.nearest_node_name}</span>}
                      <small className="muted"> · {c.distance_km} km</small>
                    </td>
                    <td>{sensorState(c)}</td>
                    <td><span className={`alert-status ${c.status === "open" ? "active" : "closed"}`}>{c.status === "open" ? "Open" : "Closed"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
