import type { Alert, DemoStatus, Network, NodeState } from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path);
  if (!r.ok) {
    let detail = "";
    try {
      detail = (await r.json()).detail ?? "";
    } catch {
      /* body was not JSON */
    }
    throw new Error(`${r.status} ${r.statusText}${detail ? `: ${detail}` : ""}`);
  }
  return r.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = "";
    try {
      detail = JSON.stringify((await r.json()).detail ?? "");
    } catch {
      /* ignore */
    }
    throw new Error(`${r.status} ${detail}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  network: () => getJson<Network>("/network"),
  alerts: (q = "") => getJson<Alert[]>(`/alerts${q}`),
  nodeState: (id: string, limit = 288) => getJson<NodeState>(`/nodes/${id}/state?limit=${limit}`),
  status: () => getJson<DemoStatus>("/demo/status"),
  inject: (type: string, node: string) => postJson<unknown>("/demo/inject", { type, node }),
  control: (b: { speed?: number; paused?: boolean }) => postJson<DemoStatus>("/demo/control", b),
};

export function wsUrl(): string {
  if (BASE) return BASE.replace(/^http/, "ws") + "/ws";
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws`;
}
