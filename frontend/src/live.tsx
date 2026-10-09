import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, wsUrl } from "./api";
import type { Alert, Assessment, DemoStatus, Network } from "./types";

export type Conn = "connecting" | "live" | "reconnecting";

interface LiveState {
  network: Network | null;
  networkError: string | null;
  loading: boolean;
  latest: Record<string, Assessment>;
  alerts: Alert[];
  status: DemoStatus | null;
  conn: Conn;
  refresh: () => void;
}

const Ctx = createContext<LiveState | null>(null);

export function useLive(): LiveState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLive outside LiveProvider");
  return v;
}

function upsertAlert(list: Alert[], a: Alert): Alert[] {
  const i = list.findIndex((x) => x.id === a.id);
  if (i === -1) return [a, ...list].slice(0, 500);
  const next = list.slice();
  next[i] = a;
  return next;
}

export function LiveProvider({ children }: { children: ReactNode }) {
  const [network, setNetwork] = useState<Network | null>(null);
  const [networkError, setNetworkError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [latest, setLatest] = useState<Record<string, Assessment>>({});
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [status, setStatus] = useState<DemoStatus | null>(null);
  const [conn, setConn] = useState<Conn>("connecting");
  const pending = useRef<Record<string, Assessment>>({});

  const load = useCallback(() => {
    Promise.all([api.network(), api.alerts("?limit=300")])
      .then(([n, a]) => {
        setNetwork(n);
        setNetworkError(null);
        setAlerts(a);
        const l: Record<string, Assessment> = {};
        n.nodes.forEach((x) => x.latest && (l[x.id] = x.latest));
        setLatest((old) => ({ ...l, ...old }));
      })
      .catch((e: Error) => setNetworkError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  // demo status poll
  useEffect(() => {
    let alive = true;
    const tick = () => api.status().then((s) => alive && setStatus(s)).catch(() => undefined);
    tick();
    const t = setInterval(tick, 2000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  // WebSocket with exponential back-off reconnect; assessments are batched every 300 ms
  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 500;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const flush = setInterval(() => {
      const p = pending.current;
      if (Object.keys(p).length) {
        pending.current = {};
        setLatest((old) => ({ ...old, ...p }));
      }
    }, 300);
    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        retry = 500;
        setConn("live");
        load();
      };
      ws.onmessage = (ev) => {
        try {
          const m = JSON.parse(ev.data as string);
          if (m.type === "assessment") pending.current[m.data.node_id] = m.data as Assessment;
          else if (m.type === "alert") setAlerts((l) => upsertAlert(l, m.data as Alert));
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        if (closed) return;
        setConn("reconnecting");
        timer = setTimeout(connect, retry);
        retry = Math.min(retry * 2, 8000);
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => {
      closed = true;
      clearInterval(flush);
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, [load]);

  const value = useMemo(
    () => ({ network, networkError, loading, latest, alerts, status, conn, refresh: load }),
    [network, networkError, loading, latest, alerts, status, conn, load],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
