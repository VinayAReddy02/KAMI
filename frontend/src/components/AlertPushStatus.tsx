import { useEffect, useState } from "react";
import { api } from "../api";
import type { NotifyStatus } from "../types";

/** Footer line: where alert messages go (dry-run log or WhatsApp). Text plus icon, never colour alone. */
export function AlertPushStatus() {
  const [s, setS] = useState<NotifyStatus | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let alive = true;
    const tick = () =>
      api
        .notifications()
        .then((v) => {
          if (alive) {
            setS(v);
            setError(false);
          }
        })
        .catch(() => alive && setError(true));
    tick();
    const id = window.setInterval(tick, 10000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);
  if (error && !s) return <span role="status">Alerts: status unavailable</span>;
  if (!s) return <span role="status">Alerts: loading…</span>;
  const on = s.mode === "twilio";
  return (
    <span role="status" title={on ? "High and Critical alerts are sent to WhatsApp" : "Alert messages are only written to a local log; nothing is sent"}>
      <span aria-hidden="true">{on ? "✉ " : "○ "}</span>
      <strong>Alerts: {on ? "WhatsApp on" : "dry run"}</strong> · {s.sent} sent, {s.suppressed} held back, {s.failed} failed
      {on && s.budget_remaining !== null ? ` · ${s.budget_remaining} left in budget` : ""}
    </span>
  );
}
