import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type DiskPathDetail = {
  label?: string;
  path?: string;
  dir_bytes?: number | null;
  dir_files?: number | null;
  exists?: boolean;
  error?: string | null;
};

export type DiskPathUsage = {
  path: string;
  paths?: string[];
  exists: boolean;
  total: number;
  used: number;
  free: number;
  used_pct: number | null;
  dir_bytes: number | null;
  dir_files: number | null;
  total_label?: string;
  used_label?: string;
  free_label?: string;
  dir_label?: string;
  error: string | null;
  details?: DiskPathDetail[];
};

export type DiskDbUsage = {
  ok: boolean;
  bytes: number;
  label?: string;
  error: string | null;
};

export type DiskCleanupConfig = {
  enabled: boolean;
  db_retention_days: number;
  image_retention_days: number;
  run_hour: number;
  last_run_time: string;
  last_run_status: string;
  last_run_message: string;
  last_run_result: Record<string, unknown>;
};

export type DiskCleanupStatus = {
  success: boolean;
  data: {
    config: DiskCleanupConfig;
    capacity: {
      paths: {
        raw_csv: DiskPathUsage;
        meta: DiskPathUsage;
        images: DiskPathUsage;
      };
      databases: {
        raw: DiskDbUsage;
        dwh: DiskDbUsage;
        defect: DiskDbUsage;
      };
    };
  };
};

export const getDiskCleanup = () => {
  return http.request<DiskCleanupStatus>("get", `${API_PREFIX}/system/disk-cleanup`);
};

export const saveDiskCleanup = (data: Partial<DiskCleanupConfig>) => {
  return http.request<{ success: boolean; data: { config: DiskCleanupConfig } }>(
    "put",
    `${API_PREFIX}/system/disk-cleanup`,
    { data }
  );
};

export const runDiskCleanup = () => {
  return http.request<{
    success: boolean;
    data: {
      accepted: boolean;
      job_id: number;
      message: string;
      status: string;
    };
  }>("post", `${API_PREFIX}/system/disk-cleanup/run`);
};
