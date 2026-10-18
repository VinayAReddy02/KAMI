import { useEffect, useState } from "react";
import { api } from "../api";
import { AlertList } from "../components/AlertList";
import { EvidenceBars } from "../components/EvidenceBars";
import { ArrowIcon } from "../components/Icons";
import { StatusBadge } from "../components/StatusBadge";
import { TimeSeries } from "../components/TimeSeries";
import { nodeLabel, nodeNumber } from "../labels";
import { useLive } from "../live";
import type { NodeState } from "../types";

export function NodeDetail({ id }: { id: string }) {
  const { network, latest } = useLive();
  const [state, setState] = useState<NodeState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const info = network?.nodes.find((n) => n.id === id);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const pull = () =>
      api
        .nodeState(id)
        .then((s) => alive && (setState(s), setError(null)))
        .catch((e: Error) => alive && setError(e.message))
        .finally(() => alive && setLoading(false));
    pull();
    const t = setInterval(pull, 2000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [id]);

  const a = latest[id] ?? state?.latest;
  return (
    <div className="detail">
      <p><a className="link back" href="#/"><ArrowIcon dir="left" /> Overview</a></p>
      <header className="detail-head">
        <span className={`plate cat-${(a?.category ?? "Normal").toLowerCase()}`} aria-hidden="true">{nodeNumber(info, id)}</span>
        <h1>{nodeLabel(info, id)}</h1>
        <div className="detail-state">
          {a && <StatusBadge category={a.category} priority={a.priority} />}
          {a?.confidence != null && <span className="conf">Confidence <b>{a.confidence.toFixed(2)}</b></span>}
        </div>
      </header>
      {loading && !state && <p className="state" role="status">Loading node state…</p>}
      {error && !state && (
        <p className="state error" role="alert">
          No state for this node yet ({error}). It may still be warming up.
        </p>
      )}
      {a && (
        <section className="card explain" aria-label="Explanation">
          <h2>Why</h2>
          <p>{a.explanation}</p>
          <EvidenceBars pInfra={a.p_infra} pQuality={a.p_quality} />
          <p className="meta">Assessment time {a.ts.replace("T", " ").slice(0, 16)} · data are semi-synthetic replay</p>
        </section>
      )}
      {state && (
        <section className="charts" aria-label="Signals">
          <TimeSeries points={state.series} field="flow" label="Flow" unit="m³/h" timeAxis={false} />
          <TimeSeries points={state.series} field="pressure" label="Pressure" unit="m" timeAxis={false} />
          <TimeSeries points={state.series} field="turbidity" label="Turbidity" unit="FNU" log timeAxis={false} />
          <TimeSeries points={state.series} field="tds" label="TDS" unit="mg/L" log />
          <p className="legend">
            Shading: <span className="lg infra">hatched = Infrastructure</span> <span className="lg quality">dotted = Quality</span>
            <span className="lg combined">crossed = Combined</span> <span>Turbidity and TDS are on a log scale.</span>
          </p>
        </section>
      )}
      <section aria-label="Alerts for this node">
        <h2>Alerts for this node</h2>
        <AlertList alerts={state?.alerts ?? []} nodeNames={{ [id]: nodeLabel(info, id) }} limit={8} />
      </section>
    </div>
  );
}
