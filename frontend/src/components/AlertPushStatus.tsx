import { useEffect, useState } from "react";
import { api } from "../api";
import type { NotifyStatus } from "../types";

/** Footer line: where alert messages go (dry-run log or the Telegram bot). Colour plus icon plus text. */
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
  if (error && !s)
    return (
      <span role="status" className="push push-error">
        <span className="push-icon" aria-hidden="true">!</span>
        <strong>Alerts: status unavailable</strong>
      </span>
    );
  if (!s) return <span role="status" className="push">Alerts: loading…</span>;
  const on = s.mode === "telegram";
  return (
    <span
      role="status"
      className={`push ${on ? "push-on" : "push-dry"}`}
      title={on ? "High and Critical alerts are sent to the Telegram bot" : "Alert messages are only written to a local log; nothing is sent"}
    >
      <span className="push-icon" aria-hidden="true">{on ? "✈" : "○"}</span>
      <strong>Alerts: {on ? "Telegram on" : "dry run"}</strong> · {s.sent} sent, {s.suppressed} held back, {s.failed} failed
    </span>
  );
}
