import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type StorePing = {
  ok: boolean;
  latency_ms?: number | null;
  error?: string | null;
};

export type WorkerHeart = {
  alive: boolean;
  last_seen: string;
  age_seconds: number | null;
  pid?: number | null;
  stale_after_seconds?: number;
};

export type JobLatest = {
  id: number;
  job_type: string;
  status: string;
  message: string;
  created_at: string;
  started_at: string;
  ended_at: string;
};

export type JobSummary = {
  latest: JobLatest | null;
  active: boolean;
  ok: boolean;
};

export type SchedulerStatus = {
  is_active?: boolean;
  enabled?: boolean;
  blocked_by_workshop?: boolean;
  last_run_time: string;
  last_run_status: string;
  last_run_message?: string;
  job: JobSummary;
};

export type RuntimeStatus = {
  status: "ok" | "degraded" | string;
  workshop: {
    offline: boolean;
    env_forced?: boolean;
  };
  stores: {
    meta: StorePing;
    raw: StorePing;
    dwh: StorePing;
    defect: StorePing;
  };
  workers: {
    collector: WorkerHeart;
    agg: WorkerHeart;
  };
  schedulers: {
    sfc: SchedulerStatus;
    etl: SchedulerStatus;
    agg: SchedulerStatus;
    disk_cleanup: SchedulerStatus;
  };
};

export const getRuntimeStatus = (signal?: AbortSignal) => {
  return http.request<{ success: boolean; data: RuntimeStatus }>(
    "get",
    `${API_PREFIX}/system/runtime-status`,
    { signal }
  );
};
