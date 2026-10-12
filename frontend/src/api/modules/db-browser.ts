import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";
import { formatToken, getToken } from "@/utils/auth";

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
  time_column?: string | null;
};

export type DbTablePreview = {
  target: DbTarget;
  table: string;
  columns: string[];
  rows: Record<string, string | null>[];
  total: number;
  limit: number;
  offset: number;
  time_column?: string | null;
  time_from?: string | null;
  time_to?: string | null;
  filters?: Record<string, string>;
};

export type DbTableClearResult = {
  target: DbTarget;
  table: string;
  label: string;
};

export type DbTimeRange = {
  time_from?: string;
  time_to?: string;
};

/** 列筛选：{列名: 值}，空值请先剔除 */
export type DbFilters = Record<string, string>;

export type DbQueryParams = {
  limit?: number;
  offset?: number;
} & DbTimeRange & {
    filters?: DbFilters;
  };

/** 后端 filters 是 JSON 字符串参数；空对象不发，避免出现 filters={} */
function withFilters(params: Record<string, unknown>, filters?: DbFilters) {
  const clean: DbFilters = {};
  for (const [key, value] of Object.entries(filters || {})) {
    if (String(value ?? "").trim()) clean[key] = String(value).trim();
  }
  if (Object.keys(clean).length) params.filters = JSON.stringify(clean);
  return params;
}

export const getDbTables = (target: DbTarget, signal?: AbortSignal) => {
  return http.request<{
    success: boolean;
    data: { info: DbTargetInfo; tables: DbTableItem[] };
  }>("get", `${API_PREFIX}/system/db/${target}/tables`, { signal });
};

export const getDbTableRows = (
  target: DbTarget,
  table: string,
  params?: DbQueryParams,
  signal?: AbortSignal
) => {
  const query: Record<string, unknown> = {};
  if (params?.limit != null) query.limit = params.limit;
  if (params?.offset != null) query.offset = params.offset;
  if (params?.time_from) query.time_from = params.time_from;
  if (params?.time_to) query.time_to = params.time_to;
  withFilters(query, params?.filters);
  return http.request<{ success: boolean; data: DbTablePreview }>(
    "get",
    `${API_PREFIX}/system/db/${target}/tables/${encodeURIComponent(table)}`,
    { params: query, signal }
  );
};

/** 某列的去重取值，用于筛选下拉；可传其它列做级联 */
export const getDbColumnValues = (
  target: DbTarget,
  table: string,
  column: string,
  filters?: DbFilters,
  signal?: AbortSignal
) => {
  const query: Record<string, unknown> = { column };
  withFilters(query, filters);
  return http.request<{
    success: boolean;
    data: { column: string; values: string[] };
  }>(
    "get",
    `${API_PREFIX}/system/db/${target}/tables/${encodeURIComponent(
      table
    )}/values`,
    { params: query, signal }
  );
};

export const clearDbTable = (target: DbTarget, table: string) => {
  return http.request<{
    success: boolean;
    data: DbTableClearResult;
    message?: string;
  }>("post", `${API_PREFIX}/system/db/${target}/tables/${encodeURIComponent(table)}/clear`, {
    timeout: 120000
  });
};

/** 下载当前表为 CSV（可带 ServerTime 范围与列筛选） */
export async function downloadDbTable(
  target: DbTarget,
  table: string,
  range?: DbTimeRange,
  filters?: DbFilters
): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token?.accessToken) {
    headers.Authorization = formatToken(token.accessToken);
  }
  const qs = new URLSearchParams();
  if (range?.time_from) qs.set("time_from", range.time_from);
  if (range?.time_to) qs.set("time_to", range.time_to);
  const clean: DbFilters = {};
  for (const [key, value] of Object.entries(filters || {})) {
    if (String(value ?? "").trim()) clean[key] = String(value).trim();
  }
  if (Object.keys(clean).length) qs.set("filters", JSON.stringify(clean));
  const query = qs.toString();
  const res = await fetch(
    `${API_PREFIX}/system/db/${target}/tables/${encodeURIComponent(table)}/export${
      query ? `?${query}` : ""
    }`,
    { method: "GET", headers }
  );
  if (!res.ok) {
    let message = `下载失败（${res.status}）`;
    try {
      const body = (await res.json()) as { message?: string };
      if (body?.message) message = body.message;
    } catch {
      /* ignore */
    }
    throw new Error(message);
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const matched = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(
    disposition
  );
  const rawName = decodeURIComponent(matched?.[1] || matched?.[2] || "");
  const filename = rawName || `${table}.csv`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
