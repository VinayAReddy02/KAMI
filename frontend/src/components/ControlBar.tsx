import { useState } from "react";
import { api } from "../api";
import { nodeShort } from "../labels";
import { useLive } from "../live";

const SPEEDS = [60, 300, 600, 1200, 3000, 6000];
const LABELS: Record<string, string> = {
  infra_leak: "Leak (gradual)",
  infra_burst: "Burst (sudden)",
  quality_turbidity_surge: "Turbidity surge",
  quality_tds_shift: "TDS shift",
  combined: "Combined",
};

export function ControlBar({ defaultNode }: { defaultNode?: string }) {
  const { network, status, conn, refresh } = useLive();
  const [type, setType] = useState("combined");
  const [node, setNode] = useState(defaultNode ?? "");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const target = node || defaultNode || network?.nodes[0]?.id || "";

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      setMsg(ok);
      refresh();
    } catch (e) {
      setMsg(`Failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
      setTimeout(() => setMsg(null), 4000);
    }
  };

  return (
    <section className="controls" aria-label="Replay controls">
      <div className="ctl-group">
        <button type="button" className="btn" disabled={!status || busy} onClick={() => run(() => api.control({ paused: !status?.paused }), status?.paused ? "Resumed" : "Paused")}>
          {status?.paused ? "▶ Resume" : "❚❚ Pause"}
        </button>
        <label>
          Speed
          <select value={status?.speed ?? 600} disabled={!status} onChange={(e) => run(() => api.control({ speed: Number(e.target.value) }), `Speed ×${e.target.value}`)}>
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                ×{s}
              </option>
            ))}
          </select>
        </label>
        <span className="sim-time" title="Simulated time of the replayed data">
          Replay time {status?.ts ? status.ts.replace("T", " ").slice(0, 16) : "–"}
        </span>
      </div>
      <div className="ctl-group">
        <label>
          Event
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {(network?.event_types ?? Object.keys(LABELS)).map((t) => (
              <option key={t} value={t}>
                {LABELS[t] ?? t}
              </option>
            ))}
          </select>
        </label>
        <label>
          Node
          <select value={target} onChange={(e) => setNode(e.target.value)}>
            {network?.nodes.map((n) => (
              <option key={n.id} value={n.id}>
                {nodeShort(n)}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn primary" disabled={!target || busy || conn !== "live"} onClick={() => run(() => api.inject(type, target), `Injected ${LABELS[type] ?? type} at ${nodeShort(network?.nodes.find((n) => n.id === target), target)}`)}>
          Inject event
        </button>
        <span className="sr-only" role="status" aria-live="polite">{msg}</span>
        {msg && <span className="toast" aria-hidden="true">{msg}</span>}
      </div>
    </section>
  );
}
