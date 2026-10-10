import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";
import type { EtlJob, FormulaGenerateResult, SourceColumn } from "@/api/modules/etl";

export type AggJob = EtlJob;

export type AggField = {
  id?: number;
  source_field: string;
  target_field: string;
  field_type: string;
  field_category: "dimension" | "measure" | "derived" | string;
  aggregate_func: string;
  derive_level: number;
  formula: string;
  sort_order: number;
  description: string;
};

export type AggModel = {
  id: number;
  project_id: string;
  display_name?: string;
  name: string;
  source_table: string;
  target_table: string;
  time_field: string;
  granularity: string;
  time_field_name: string;
  lookback_hours: number;
  backfill_hours: number;
  sql_path: string;
  is_enabled: boolean;
  is_draft: boolean;
  field_count: number;
  can_run: boolean;
  last_run_time: string;
  last_run_status: string;
  last_run_rows: number;
  last_run_message: string;
  fields?: AggField[];
  sql_preview?: string;
};

export type AggProjectRow = {
  project_id: string;
  display_name: string;
  enabled: boolean;
  prefix: string;
  source_table: string;
  target_table: string;
  model_id?: number;
  is_draft?: boolean;
  is_model_enabled?: boolean;
  can_run?: boolean;
  field_count?: number;
  lookback_hours?: number;
  granularity?: string;
  last_agg_time: string;
  last_agg_status: string;
  last_agg_rows: number;
  last_agg_message: string;
};

export type AggScheduler = {
  is_active: boolean;
  mode?: string;
  backfill_hours?: number;
  last_run_time: string;
  last_run_status: string;
  last_run_message: string;
};

export type AggEnqueueResult = {
  accepted: boolean;
  job_id: number;
  message?: string;
  status?: string;
};

export type AggPreview = {
  columns: string[];
  rows: Record<string, unknown>[];
  sql: string;
  hours: number;
  from_time?: string;
  to_time?: string;
  source: string;
  source_table: string;
};

export type AggLogLine = {
  time?: string;
  level?: string;
  message?: string;
};

export type AggRunLog = {
  id: number;
  started_at: string;
  ended_at: string;
  trigger: string;
  run_mode: string;
  status: string;
  message: string;
  rows_affected: number;
  duration: number;
  job_id: number;
  detail?: {
    lines?: AggLogLine[];
    projects?: Record<string, unknown>[];
  };
};

export const aggOverview = () => {
  return http.request<{
    success: boolean;
    data: {
      projects: AggProjectRow[];
      models: AggModel[];
      active_job: AggJob | null;
      scheduler?: AggScheduler;
    };
  }>("get", `${API_PREFIX}/agg/overview`);
};

export const listAggLogs = (limit = 50) => {
  return http.request<{ success: boolean; data: { logs: AggRunLog[] } }>(
    "get",
    `${API_PREFIX}/agg/logs`,
    { params: { limit } }
  );
};

export const clearAggLogs = () => {
  return http.request<{ success: boolean; data: { deleted: number } }>(
    "delete",
    `${API_PREFIX}/agg/logs`
  );
};

export const saveAggScheduler = (payload: { is_active?: boolean }) => {
  return http.request<{ success: boolean; data: AggScheduler }>(
    "put",
    `${API_PREFIX}/agg/scheduler`,
    { data: payload }
  );
};

export const ensureAggModel = (projectId: string) => {
  return http.request<{ success: boolean; data: AggModel }>(
    "post",
    `${API_PREFIX}/agg/models`,
    { data: { project_id: projectId } }
  );
};

export const getAggModel = (modelId: number) => {
  return http.request<{ success: boolean; data: AggModel }>(
    "get",
    `${API_PREFIX}/agg/models/${modelId}`
  );
};

export const updateAggModel = (
  modelId: number,
  data: Partial<
    Pick<
      AggModel,
      | "time_field"
      | "granularity"
      | "time_field_name"
      | "lookback_hours"
      | "backfill_hours"
      | "is_enabled"
    >
  >
) => {
  return http.request<{ success: boolean; data: AggModel }>(
    "put",
    `${API_PREFIX}/agg/models/${modelId}`,
    { data }
  );
};

export const getAggSourceColumns = (modelId: number) => {
  return http.request<{ success: boolean; data: { columns: SourceColumn[] } }>(
    "get",
    `${API_PREFIX}/agg/models/${modelId}/source-columns`
  );
};

export const suggestAggFields = (modelId: number) => {
  return http.request<{
    success: boolean;
    data: {
      time_field: string;
      granularity: string;
      time_field_name: string;
      lookback_hours: number;
      backfill_hours: number;
      columns: string[];
      fields: AggField[];
    };
  }>("post", `${API_PREFIX}/agg/models/${modelId}/suggest`);
};

export const generateAggFormula = (
  modelId: number,
  payload: {
    prompt: string;
    hint_field?: string;
    available_fields?: string[];
    mode?: "auto" | "ai" | "rules";
  }
) => {
  return http.request<{ success: boolean; data: FormulaGenerateResult }>(
    "post",
    `${API_PREFIX}/agg/models/${modelId}/formula/generate`,
    { data: payload, timeout: 180000 }
  );
};

export const saveAggConfig = (
  modelId: number,
  payload: {
    time_field?: string;
    granularity?: string;
    time_field_name?: string;
    lookback_hours?: number;
    backfill_hours?: number;
    is_enabled?: boolean;
    fields: AggField[];
  }
) => {
  return http.request<{ success: boolean; data: AggModel }>(
    "put",
    `${API_PREFIX}/agg/models/${modelId}/config`,
    { data: payload }
  );
};

export const getAggSqlPreview = (modelId: number) => {
  return http.request<{ success: boolean; data: { sql: string; sql_path: string } }>(
    "get",
    `${API_PREFIX}/agg/models/${modelId}/sql-preview`
  );
};

export const previewAggData = (
  modelId: number,
  opts?: { hours?: number; limit?: number; live?: boolean }
) => {
  return http.request<{ success: boolean; data: AggPreview }>(
    "post",
    `${API_PREFIX}/agg/models/${modelId}/preview`,
    {
      data: {
        hours: opts?.hours,
        limit: opts?.limit ?? 200,
        live: Boolean(opts?.live)
      }
    }
  );
};

export const runAgg = (opts?: {
  projectId?: string;
  modelId?: number;
  fullRefresh?: boolean;
}) => {
  return http.request<{ success: boolean; data: AggEnqueueResult }>(
    "post",
    `${API_PREFIX}/agg/run`,
    {
      data: {
        project_id: opts?.projectId || "",
        model_id: opts?.modelId ?? null,
        full_refresh: Boolean(opts?.fullRefresh)
      }
    }
  );
};

export const getAggJob = (jobId: number) => {
  return http.request<{ success: boolean; data: AggJob }>(
    "get",
    `${API_PREFIX}/agg/jobs/${jobId}`
  );
};

export async function waitForAggJob(
  jobId: number,
  options?: {
    intervalMs?: number;
    maxAttempts?: number;
    onUpdate?: (job: AggJob) => void;
  }
): Promise<AggJob> {
  const intervalMs = options?.intervalMs ?? 1000;
  const maxAttempts = options?.maxAttempts ?? 600;
  for (let i = 0; i < maxAttempts; i++) {
    const res = await getAggJob(jobId);
    const job = res?.data;
    if (!job) throw new Error("任务不存在");
    options?.onUpdate?.(job);
    if (
      job.status === "success" ||
      job.status === "failed" ||
      job.status === "cancelled"
    ) {
      return job;
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }
  throw new Error("等待聚合服务超时，请确认聚合服务已在运行");
}
