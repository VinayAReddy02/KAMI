import { useLive } from "../live";

export function Method() {
  const { status } = useLive();
  const m = status?.method;
  return (
    <article className="method">
      <h1>About KAMI · Method</h1>
      <p className="method-version" role="status">
        <strong>Method version:</strong>{" "}
        {m ? (
          <>
            {m.label} <span className="muted">({Object.entries(m.params).map(([k, v]) => `${k} ${v}`).join(", ")}; commit {m.frozen_commit})</span>
          </>
        ) : (
          "loading…"
        )}
      </p>
      <p>
        KAMI watches four signals per node (flow, pressure, turbidity, TDS) and separates <strong>infrastructure</strong> behaviour
        from <strong>water-quality</strong> behaviour before combining them.
      </p>
      <ol className="pipeline">
        <li><strong>Causal features.</strong> Rolling mean, spread, rate of change, slope and deviation from baseline, using past values only.</li>
        <li><strong>Two evidence streams.</strong> One calibrated model gives <code>p_infra</code> from flow and pressure, another gives <code>p_quality</code> from turbidity and TDS.</li>
        <li><strong>Temporal context.</strong> For each stream: suddenness (how fast evidence rose), persistence (how long it stayed up), recurrence (separate episodes in 7 days).</li>
        <li><strong>Fusion.</strong> Dempster–Shafer combination with reliability discounting: short transients count for less than persistent or recurring evidence.</li>
        <li><strong>Output.</strong> Category (Normal, Infrastructure, Quality, Combined), priority (rule-based escalation by persistence and intensity), confidence and a plain-language explanation.</li>
      </ol>
      <h2>What you are looking at</h2>
      <ul>
        <li>The map is a <strong>demo network with a fictional layout</strong> near Vellore. There is no physical hardware: virtual nodes replay public data (BattLeDIM hydraulic simulation and USGS river records) over a message bus.</li>
        <li>All node data are <strong>semi-synthetic</strong>. Injected events come from a scenario generator, not from real incidents.</li>
        <li>The live rule is the configuration frozen in Round 2 before the held-out evaluation. It scores a step only when both evidence streams are present. On the fresh test set it showed no detectable gain over simple threshold voting on event F1 and a better category accuracy (see the project summary).</li>
      </ul>
    </article>
  );
}
