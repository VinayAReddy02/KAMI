interface Props {
  pInfra: number;
  pQuality: number;
}

function Bar({ label, value, kind }: { label: string; value: number; kind: "infra" | "quality" }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="ev-row">
      <div className="ev-label">
        <span>{label}</span>
        <strong>{value.toFixed(2)}</strong>
      </div>
      <div className={`ev-track ev-${kind}`} role="meter" aria-label={`${label} probability`} aria-valuemin={0} aria-valuemax={1} aria-valuenow={Number(value.toFixed(2))}>
        <div className="ev-fill" style={{ width: `${pct}%` }} />
        <div className="ev-mark" style={{ left: "50%" }} title="reference level 0.5" />
      </div>
    </div>
  );
}

export function EvidenceBars({ pInfra, pQuality }: Props) {
  return (
    <div className="evidence">
      <Bar label="Infrastructure evidence p_infra" value={pInfra} kind="infra" />
      <Bar label="Quality evidence p_quality" value={pQuality} kind="quality" />
    </div>
  );
}
