import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type SfcConfig = {
  sso_login_url: string;
  sfc_base_url: string;
  sfc_logon_path: string;
  sfc_data_path: string;
  line_option: string;
  section_option: string;
  crawl_interval: number;
  retry: number;
  is_active: boolean;
  is_running: boolean;
  last_run_time: string;
  last_run_status: string;
};

export type SfcAccount = {
  id: number;
  name: string;
  username: string;
  sort_order: number;
  enabled: boolean;
  password_set: boolean;
  total_use_count: number;
  success_count: number;
  failed_count: number;
  last_use_time: string;
  last_use_status: string;
  last_error: string;
};

export type SfcProjectRow = {
  project_id: string;
  display_name: string;
  enabled: boolean;
  sfc_code: string;
  btype: string;
  prefix: string;
  last_crawl_time: string;
  last_crawl_status: string;
  last_crawl_rows: number;
};

export type SfcJob = {
  id: number;
  job_type: string;
  status: "queued" | "running" | "success" | "failed" | "cancelled" | string;
  payload: Record<string, unknown>;
  message: string;
  result: Record<string, unknown>;
  created_at: string;
  started_at: string;
  ended_at: string;
};

export type SfcEnqueueResult = {
  accepted: boolean;
  job_id: number;
  message?: string;
  status?: string;
};

export const sfcOverview = () => {
  return http.request("get", `${API_PREFIX}/sfc/overview`);
};

export const getSfcJob = (jobId: number) => {
  return http.request<{ success: boolean; data: SfcJob }>(
    "get",
    `${API_PREFIX}/sfc/jobs/${jobId}`
  );
};

/** 轮询任务直到终态；默认最多约 10 分钟。 */
export async function waitForSfcJob(
  jobId: number,
  options?: { intervalMs?: number; maxAttempts?: number }
): Promise<SfcJob> {
  const intervalMs = options?.intervalMs ?? 1000;
  const maxAttempts = options?.maxAttempts ?? 600;
  for (let i = 0; i < maxAttempts; i++) {
    const res = await getSfcJob(jobId);
    const job = res?.data;
    if (!job) throw new Error("任务不存在");
    if (
      job.status === "success" ||
      job.status === "failed" ||
      job.status === "cancelled"
    ) {
      return job;
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }
  throw new Error("等待 Worker 超时，请确认已启动 python -m collector.worker");
}

export const saveSfcConfig = (data: Partial<SfcConfig>) => {
  return http.request("put", `${API_PREFIX}/sfc/config`, { data });
};

export const createSfcAccount = (data: {
  name: string;
  username: string;
  password: string;
  sort_order: number;
  enabled: boolean;
}) => {
  return http.request("post", `${API_PREFIX}/sfc/accounts`, { data });
};

export const updateSfcAccount = (
  id: number,
  data: Partial<{
    name: string;
    username: string;
    password: string;
    sort_order: number;
    enabled: boolean;
  }>
) => {
  return http.request("put", `${API_PREFIX}/sfc/accounts/${id}`, { data });
};

export const deleteSfcAccount = (id: number) => {
  return http.request("delete", `${API_PREFIX}/sfc/accounts/${id}`);
};

export const runSfcNow = () => {
  return http.request<{ success: boolean; data: SfcEnqueueResult }>(
    "post",
    `${API_PREFIX}/sfc/run`
  );
};

export const clearSfcLogs = (force = false) => {
  return http.request<{ success: boolean; data: { deleted: number; forced?: boolean } }>(
    "delete",
    `${API_PREFIX}/sfc/logs`,
    { params: force ? { force: true } : undefined }
  );
};

export const uploadSfcCsv = (projectId: string, file: File) => {
  const data = new FormData();
  data.append("project_id", projectId);
  data.append("file", file);
  // 仅投递入队，短超时即可；真正入库由 Worker 完成
  return http.request<{ success: boolean; data: SfcEnqueueResult }>(
    "post",
    `${API_PREFIX}/sfc/upload`,
    {
      data,
      timeout: 60000
    }
  );
};
