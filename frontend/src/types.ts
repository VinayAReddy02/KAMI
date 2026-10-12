export type Category = "Normal" | "Infrastructure" | "Quality" | "Combined";
export type Priority = "Low" | "Medium" | "High" | "Critical";

export const CATEGORIES: Category[] = ["Normal", "Infrastructure", "Quality", "Combined"];
export const PRIORITIES: Priority[] = ["Low", "Medium", "High", "Critical"];

export interface Assessment {
  node_id: string;
  ts: string;
  category: Category;
  priority: Priority;
  confidence: number | null;
  explanation: string;
  status: "ok" | "warming_up";
  p_infra: number;
  p_quality: number;
  temporal: Record<string, number>;
}

export interface NodeInfo {
  id: string;
  name: string;
  lat: number;
  lon: number;
  latest: Assessment | null;
}

export interface Network {
  label: string;
  center: [number, number];
  zoom: number;
  nodes: NodeInfo[];
  counts: Partial<Record<Category, number>>;
  event_types: string[];
}

export interface Alert {
  id: number;
  node_id: string;
  category: Category;
  priority: Priority;
  max_priority: Priority;
  start_ts: string;
  last_ts: string;
  end_ts: string | null;
  status: "active" | "closed";
  confidence: number | null;
  explanation: string;
}

export interface SeriesPoint {
  ts: string;
  flow: number | null;
  pressure: number | null;
  turbidity: number | null;
  tds: number | null;
  p_infra: number;
  p_quality: number;
  category: Category;
  priority: Priority;
}

export interface NodeState {
  node_id: string;
  latest: Assessment;
  series: SeriesPoint[];
  alerts: Alert[];
}

export interface DemoStatus {
  speed: number;
  paused: boolean;
  step: number;
  ts: string | null;
  done: boolean;
  mode: string;
  data_kind: string;
  injections: { id: string; node_id: string; type: string; start_ts: string | null }[];
  method?: { label: string; design: string; params: Record<string, number>; frozen_commit: string; source: string };
}

export interface Complaint {
  id: number;
  created_utc: string;
  replay_ts: string | null;
  lat: number;
  lon: number;
  node_id: string | null;
  node_name: string | null;
  nearest_node_name: string;
  distance_km: number;
  in_demo_area: boolean;
  node_category: Category | null;
  node_priority: Priority | null;
  status: string;
  source: string;
  thumb_url: string;
}

export interface NotifyStatus {
  mode: "dry_run" | "telegram";
  sent: number;
  suppressed: number;
  failed: number;
  last_send_utc: string | null;
  detail?: string;
}
