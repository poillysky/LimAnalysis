import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type EtlJob = {
  id: number;
  job_type: string;
  status: string;
  payload?: Record<string, unknown>;
  message?: string;
  result?: Record<string, unknown>;
  created_at?: string;
  started_at?: string;
  ended_at?: string;
};

export type EtlFieldTypeOption = {
  value: string;
  label: string;
};

export type EtlField = {
  id?: number;
  source_field: string;
  target_field: string;
  field_type: string;
  mapping_type: "direct" | "derived" | "constant" | string;
  derive_level: number;
  formula: string;
  constant_value: string;
  sort_order: number;
  is_required: boolean;
  description: string;
};

export type EtlSourceField = {
  source_field: string;
  field_type: string;
  sort_order?: number;
};

export type EtlModel = {
  id: number;
  project_id: string;
  display_name?: string;
  name: string;
  source_table: string;
  target_table: string;
  unique_key: string;
  incremental_field: string;
  sql_path: string;
  is_enabled: boolean;
  is_draft: boolean;
  field_count: number;
  source_field_count?: number;
  can_run: boolean;
  last_run_time: string;
  last_run_status: string;
  last_run_rows: number;
  last_run_message: string;
  source_fields?: EtlSourceField[];
  fields?: EtlField[];
  sql_preview?: string;
};

export type EtlProjectRow = {
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
  last_etl_time: string;
  last_etl_status: string;
  last_etl_rows: number;
  last_etl_message: string;
  last_crawl_rows: number;
};

export type EtlEnqueueResult = {
  accepted: boolean;
  job_id: number;
  message?: string;
  status?: string;
};

export type SourceColumn = {
  column_name: string;
  column_type: string;
  nullable: boolean;
};

export const getEtlFieldTypes = () => {
  return http.request<{ success: boolean; data: { types: EtlFieldTypeOption[] } }>(
    "get",
    `${API_PREFIX}/etl/field-types`
  );
};

export type EtlScheduler = {
  is_active: boolean;
  run_interval: number;
  last_run_time: string;
  last_run_status: string;
  last_run_message: string;
};

export type EtlLogLine = {
  time?: string;
  level?: string;
  message?: string;
};

export type EtlRunLog = {
  id: number;
  started_at: string;
  ended_at: string;
  trigger: string;
  run_mode: string;
  status: string;
  message: string;
  rows_affected: number;
  rows_inserted?: number;
  rows_updated?: number;
  duration: number;
  job_id: number;
  detail?: {
    lines?: EtlLogLine[];
    projects?: Record<string, unknown>[];
    rows_inserted?: number;
    rows_updated?: number;
  };
};

export const listEtlLogs = (limit = 50) => {
  return http.request<{ success: boolean; data: { logs: EtlRunLog[] } }>(
    "get",
    `${API_PREFIX}/etl/logs`,
    { params: { limit } }
  );
};

export const clearEtlLogs = () => {
  return http.request<{ success: boolean; data: { deleted: number } }>(
    "delete",
    `${API_PREFIX}/etl/logs`
  );
};

export const etlOverview = () => {
  return http.request<{
    success: boolean;
    data: {
      projects: EtlProjectRow[];
      models: EtlModel[];
      active_job: EtlJob | null;
      scheduler?: EtlScheduler;
    };
  }>("get", `${API_PREFIX}/etl/overview`);
};

export const getEtlScheduler = () => {
  return http.request<{ success: boolean; data: EtlScheduler }>(
    "get",
    `${API_PREFIX}/etl/scheduler`
  );
};

export const saveEtlScheduler = (payload: {
  is_active?: boolean;
  run_interval?: number;
}) => {
  return http.request<{ success: boolean; data: EtlScheduler }>(
    "put",
    `${API_PREFIX}/etl/scheduler`,
    { data: payload }
  );
};

export const getEtlModel = (modelId: number) => {
  return http.request<{ success: boolean; data: EtlModel }>(
    "get",
    `${API_PREFIX}/etl/models/${modelId}`
  );
};

export const ensureEtlModel = (projectId: string) => {
  return http.request<{ success: boolean; data: EtlModel }>(
    "post",
    `${API_PREFIX}/etl/models`,
    { data: { project_id: projectId } }
  );
};

export const updateEtlModel = (
  modelId: number,
  data: Partial<
    Pick<EtlModel, "name" | "unique_key" | "incremental_field" | "is_enabled">
  >
) => {
  return http.request<{ success: boolean; data: EtlModel }>(
    "put",
    `${API_PREFIX}/etl/models/${modelId}`,
    { data }
  );
};

export const getSourceColumns = (modelId: number) => {
  return http.request<{ success: boolean; data: { columns: SourceColumn[] } }>(
    "get",
    `${API_PREFIX}/etl/models/${modelId}/source-columns`
  );
};

export const saveEtlFields = (modelId: number, fields: EtlField[]) => {
  return http.request<{ success: boolean; data: EtlModel }>(
    "put",
    `${API_PREFIX}/etl/models/${modelId}/fields`,
    { data: { fields } }
  );
};

export const saveEtlSourceFields = (
  modelId: number,
  sourceFields: EtlSourceField[]
) => {
  return http.request<{ success: boolean; data: EtlModel }>(
    "put",
    `${API_PREFIX}/etl/models/${modelId}/source-fields`,
    { data: { source_fields: sourceFields } }
  );
};

export const importDirectFields = (modelId: number) => {
  return http.request<{ success: boolean; data: EtlModel }>(
    "post",
    `${API_PREFIX}/etl/models/${modelId}/fields/import-direct`
  );
};

export const reanalyzeSourceFields = (modelId: number) => {
  return http.request<{ success: boolean; data: EtlModel }>(
    "post",
    `${API_PREFIX}/etl/models/${modelId}/source-fields/reanalyze`
  );
};

export type FormulaGenerateResult = {
  ok: boolean;
  formula: string;
  explanation: string;
  error?: string;
  examples?: { label: string; prompt: string }[];
  suggest_level?: number;
  source?: "ai" | "rules" | string;
  ai_fallback_error?: string;
  ai?: { ready?: boolean; enabled?: boolean; model?: string };
};

export const generateEtlFormula = (
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
    `${API_PREFIX}/etl/models/${modelId}/formula/generate`,
    { data: payload, timeout: 180000 }
  );
};

export const clearEtlFields = (modelId: number) => {
  return http.request<{ success: boolean; data: EtlModel }>(
    "delete",
    `${API_PREFIX}/etl/models/${modelId}/fields`
  );
};

export const getSqlPreview = (modelId: number) => {
  return http.request<{ success: boolean; data: { sql: string; sql_path: string } }>(
    "get",
    `${API_PREFIX}/etl/models/${modelId}/sql-preview`
  );
};

export const previewEtlData = (modelId: number, limit = 50) => {
  return http.request<{
    success: boolean;
    data: { columns: string[]; rows: Record<string, unknown>[]; sql: string };
  }>("post", `${API_PREFIX}/etl/models/${modelId}/preview`, {
    data: { limit }
  });
};

export const runEtl = (opts?: {
  projectId?: string;
  modelId?: number;
  fullRefresh?: boolean;
}) => {
  return http.request<{ success: boolean; data: EtlEnqueueResult }>(
    "post",
    `${API_PREFIX}/etl/run`,
    {
      data: {
        project_id: opts?.projectId || "",
        model_id: opts?.modelId ?? null,
        full_refresh: Boolean(opts?.fullRefresh)
      }
    }
  );
};

export const getEtlJob = (jobId: number) => {
  return http.request<{ success: boolean; data: EtlJob }>(
    "get",
    `${API_PREFIX}/etl/jobs/${jobId}`
  );
};

export async function waitForEtlJob(
  jobId: number,
  options?: {
    intervalMs?: number;
    maxAttempts?: number;
    onUpdate?: (job: EtlJob) => void;
  }
): Promise<EtlJob> {
  const intervalMs = options?.intervalMs ?? 1000;
  const maxAttempts = options?.maxAttempts ?? 600;
  for (let i = 0; i < maxAttempts; i++) {
    const res = await getEtlJob(jobId);
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
  throw new Error("等待 Worker 超时，请确认已启动 python -m collector.worker");
}
