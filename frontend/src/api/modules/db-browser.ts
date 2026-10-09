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

export const getDbTables = (target: DbTarget, signal?: AbortSignal) => {
  return http.request<{
    success: boolean;
    data: { info: DbTargetInfo; tables: DbTableItem[] };
  }>("get", `${API_PREFIX}/system/db/${target}/tables`, { signal });
};

export const getDbTableRows = (
  target: DbTarget,
  table: string,
  params?: { limit?: number; offset?: number } & DbTimeRange,
  signal?: AbortSignal
) => {
  return http.request<{ success: boolean; data: DbTablePreview }>(
    "get",
    `${API_PREFIX}/system/db/${target}/tables/${encodeURIComponent(table)}`,
    { params, signal }
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

/** 下载当前表为 CSV（可带 ServerTime 范围） */
export async function downloadDbTable(
  target: DbTarget,
  table: string,
  range?: DbTimeRange
): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token?.accessToken) {
    headers.Authorization = formatToken(token.accessToken);
  }
  const qs = new URLSearchParams();
  if (range?.time_from) qs.set("time_from", range.time_from);
  if (range?.time_to) qs.set("time_to", range.time_to);
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
