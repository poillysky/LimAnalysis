import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type DbTarget = "meta" | "raw" | "dwh" | "defect";

export type DbTargetInfo = {
  target: DbTarget;
  label: string;
  endpoint: string;
  ok: boolean;
  error: string | null;
  dialect: string;
};

export type DbTableItem = {
  name: string;
  columns: number;
};

export type DbTablePreview = {
  target: DbTarget;
  table: string;
  columns: string[];
  rows: Record<string, string | null>[];
  total: number;
  limit: number;
  offset: number;
};

export const getDbTables = (target: DbTarget, signal?: AbortSignal) => {
  return http.request<{
    success: boolean;
    data: { info: DbTargetInfo; tables: DbTableItem[] };
  }>("get", `${API_PREFIX}/system/db/${target}/tables`, { signal });
};

export const getDbTableRows = (
  target: DbTarget,
  table: string,
  params?: { limit?: number; offset?: number },
  signal?: AbortSignal
) => {
  return http.request<{ success: boolean; data: DbTablePreview }>(
    "get",
    `${API_PREFIX}/system/db/${target}/tables/${encodeURIComponent(table)}`,
    { params, signal }
  );
};
