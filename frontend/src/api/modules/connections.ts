import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type PgConnForm = {
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
};

export type PgConnPublic = {
  key: "raw" | "dwh" | "defect";
  label: string;
  host: string;
  port: number;
  database: string;
  username: string;
  password_set: boolean;
};

export type DbwebForm = {
  url: string;
  sqlite_path: string;
};

export type MetabaseForm = {
  url: string;
  username: string;
  password: string;
};

export type ConnStatus = { ok: boolean; error: string | null };

export type ConnectionsResult = {
  success: boolean;
  data: {
    connections: { raw: PgConnPublic; dwh: PgConnPublic; defect: PgConnPublic };
    dbweb: DbwebForm & { label?: string };
    metabase?: MetabaseForm & { label?: string; password_set?: boolean };
    status: {
      raw: ConnStatus;
      dwh: ConnStatus;
      defect: ConnStatus;
      dbweb: ConnStatus & { url?: string };
      metabase?: ConnStatus & { url?: string };
    };
  };
};

export const listConnections = () => {
  return http.request<ConnectionsResult>("get", `${API_PREFIX}/system/connections`);
};

export const saveConnections = (data: {
  raw: PgConnForm;
  dwh: PgConnForm;
  defect: PgConnForm;
  dbweb: DbwebForm;
  metabase?: MetabaseForm;
}) => {
  return http.request<ConnectionsResult>("put", `${API_PREFIX}/system/connections`, {
    data
  });
};

export const testConnection = (data: PgConnForm & { target: "raw" | "dwh" | "defect" }) => {
  return http.request<{
    success: boolean;
    data: { target: string; label: string; ok: boolean; error: string | null };
  }>("post", `${API_PREFIX}/system/connections/test`, { data });
};

export const testDbweb = (data?: { url?: string }) => {
  return http.request<{
    success: boolean;
    data: { label: string; ok: boolean; error: string | null; url?: string };
  }>("post", `${API_PREFIX}/system/connections/dbweb/test`, {
    data: data || {}
  });
};

export const testMetabase = (data?: {
  url?: string;
  username?: string;
  password?: string;
}) => {
  return http.request<{
    success: boolean;
    data: { label: string; ok: boolean; error: string | null; url?: string };
  }>("post", `${API_PREFIX}/system/connections/metabase/test`, {
    data: data || {}
  });
};
