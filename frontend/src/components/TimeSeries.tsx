import { useMemo } from "react";
import type { Category, SeriesPoint } from "../types";

interface Props {
  points: SeriesPoint[];
  field: "flow" | "pressure" | "turbidity" | "tds";
  label: string;
  unit: string;
  log?: boolean;
}

const W = 640;
const H = 150;
const PAD = { l: 48, r: 10, t: 10, b: 22 };

// Anomaly shading: consecutive non-Normal steps (gaps up to GAP steps bridged) form one band. The band takes the
// most severe category present (Combined > the most frequent of Infrastructure/Quality). Each category has its own texture.
const GAP = 6;

function runs(points: SeriesPoint[]): { a: number; b: number; cat: Category }[] {
  const out: { a: number; b: number; counts: Record<string, number> }[] = [];
  points.forEach((p, i) => {
    if (p.category === "Normal") return;
    const last = out[out.length - 1];
    if (last && i - last.b <= GAP + 1) {
      last.b = i;
      last.counts[p.category] = (last.counts[p.category] ?? 0) + 1;
    } else out.push({ a: i, b: i, counts: { [p.category]: 1 } });
  });
  return out.map((r) => {
    const c = r.counts;
    const cat: Category = c.Combined ? "Combined" : (c.Infrastructure ?? 0) >= (c.Quality ?? 0) ? "Infrastructure" : "Quality";
    return { a: r.a, b: r.b, cat };
  });
}

export function TimeSeries({ points, field, label, unit, log = false }: Props) {
  const geo = useMemo(() => {
    const vals = points.map((p) => p[field]).filter((v): v is number => v !== null && Number.isFinite(v));
    if (vals.length < 2) return null;
    const f = (v: number) => (log ? Math.log10(Math.max(v, 0.01)) : v);
    let lo = Math.min(...vals.map(f));
    let hi = Math.max(...vals.map(f));
    if (hi - lo < 1e-9) {
      lo -= 1;
      hi += 1;
    }
    const pad = (hi - lo) * 0.08;
    lo -= pad;
    hi += pad;
    const n = points.length;
    const x = (i: number) => PAD.l + (i / Math.max(n - 1, 1)) * (W - PAD.l - PAD.r);
    const y = (v: number) => PAD.t + (1 - (f(v) - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
    let d = "";
    let pen = false;
    points.forEach((p, i) => {
      const v = p[field];
      if (v === null || !Number.isFinite(v)) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
      pen = true;
    });
    const unlog = (v: number) => (log ? Math.pow(10, v) : v);
    return { d, x, lo: unlog(lo + pad), hi: unlog(hi - pad), last: vals[vals.length - 1] };
  }, [points, field, log]);

  const shade = useMemo(() => runs(points), [points]);
  const fmt = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2));

  if (!geo) {
    return (
      <figure className="chart">
        <figcaption>{label}</figcaption>
        <p className="state empty">Waiting for data…</p>
      </figure>
    );
  }
  const first = points[0].ts.slice(5, 16).replace("T", " ");
  const lastTs = points[points.length - 1].ts.slice(5, 16).replace("T", " ");
  return (
    <figure className="chart">
      <figcaption>
        <span>{label}</span>
        <span className="chart-last">
          {fmt(geo.last)} {unit}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label} over the last ${points.length} steps, latest ${fmt(geo.last)} ${unit}. Shaded bands mark anomalies.`}>
        <defs>
          <pattern id="hatch-infra" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="var(--c-infra)" fillOpacity="0.16" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--c-infra)" strokeWidth="1.4" strokeOpacity="0.55" />
          </pattern>
          <pattern id="dots-quality" width="6" height="6" patternUnits="userSpaceOnUse">
            <rect width="6" height="6" fill="var(--c-quality)" fillOpacity="0.16" />
            <circle cx="3" cy="3" r="1.2" fill="var(--c-quality)" fillOpacity="0.6" />
          </pattern>
          <pattern id="cross-combined" width="7" height="7" patternUnits="userSpaceOnUse">
            <rect width="7" height="7" fill="var(--c-combined)" fillOpacity="0.2" />
            <path d="M0 0L7 7M7 0L0 7" stroke="var(--c-combined)" strokeWidth="1" strokeOpacity="0.55" />
          </pattern>
        </defs>
        {shade.map((r, i) => (
          <rect
            key={i}
            x={geo.x(r.a)}
            y={PAD.t}
            width={Math.max(geo.x(r.b) - geo.x(r.a), 2)}
            height={H - PAD.t - PAD.b}
            fill={r.cat === "Infrastructure" ? "url(#hatch-infra)" : r.cat === "Quality" ? "url(#dots-quality)" : "url(#cross-combined)"}
          >
            <title>{r.cat} anomaly</title>
          </rect>
        ))}
        <line x1={PAD.l} y1={H - PAD.b} x2={W - PAD.r} y2={H - PAD.b} className="axis" />
        <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={H - PAD.b} className="axis" />
        <path d={geo.d} className="series-line" fill="none" />
        <text x={PAD.l - 6} y={PAD.t + 8} textAnchor="end" className="tick">{fmt(geo.hi)}</text>
        <text x={PAD.l - 6} y={H - PAD.b} textAnchor="end" className="tick">{fmt(geo.lo)}</text>
        <text x={PAD.l} y={H - 5} className="tick">{first}</text>
        <text x={W - PAD.r} y={H - 5} textAnchor="end" className="tick">{lastTs}</text>
      </svg>
    </figure>
  );
}
