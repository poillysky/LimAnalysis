import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type A2bPresence = "online" | "offline" | "never";

export type A2bHeartbeatSlot = {
  slot_key: string;
  mode: "mold" | "appearance" | string;
  registered: boolean;
  project_id: string;
  project_name: string;
  machine: string;
  station: string;
  title: string;
  presence: A2bPresence;
  online: boolean;
  age_seconds: number | null;
  last_seen_at: string;
  client_id: string;
  client_status: string;
  paused: boolean;
  ok_count: number;
  fail_count: number;
  total_runs: number;
  last_sync: string;
  source: string;
  target: string;
  host_name: string;
  client_version: string;
  mode_label?: string;
};

export type A2bHeartbeatStatus = {
  mode: string;
  stale_seconds: number;
  summary: {
    online: number;
    offline: number;
    never: number;
    unregistered: number;
    total_slots: number;
  };
  slots: A2bHeartbeatSlot[];
  unregistered: A2bHeartbeatSlot[];
};

export type A2bHeartbeatStatusResult = {
  success: boolean;
  data: A2bHeartbeatStatus;
  message?: string;
};

export const getA2bHeartbeatStatus = (mode: "mold" | "appearance") => {
  return http.request<A2bHeartbeatStatusResult>(
    "get",
    `${API_PREFIX}/system/a2b-heartbeat/status`,
    { params: { mode } }
  );
};
