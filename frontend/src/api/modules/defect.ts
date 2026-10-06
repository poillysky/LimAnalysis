import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export const getDefectSummary = (params?: object) => {
  return http.request("get", `${API_PREFIX}/defects/summary`, { params });
};

export type YieldAlertContact = {
  person_id: number | null;
  name: string;
  phone: string;
};

export type YieldAlertRow = {
  project_id?: string;
  project_name?: string;
  machine: string;
  cavity?: string;
  cavity_raw?: string;
  qty: number;
  ng: number;
  rate_pct: number | null;
  reasons?: string[];
  defects?: { item: string; label: string; ng: number }[];
  machine_qty?: number;
  machine_ng?: number;
  machine_rate_pct?: number | null;
  contacts: YieldAlertContact[];
};

export type YieldNoticeMachine = {
  project_id?: string;
  project_name?: string;
  machine: string;
  qty: number;
  ng: number;
  rate_pct: number | null;
};

export type YieldNotice = {
  name: string;
  phone: string;
  person_id: number | null;
  duty: string;
  machines: YieldNoticeMachine[];
};

export type YieldAlertResult = {
  success: boolean;
  data: {
    projects: { project_id: string; display_name: string }[];
    current: { project_id: string; display_name: string } | null;
    ready: boolean;
    duty: string;
    hours: number;
    from_hour: string;
    to_hour: string;
    rules: {
      cavity_rate_above_pct: number;
      cavity_min_qty: number;
      machine_rate_above_pct: number;
      machine_min_qty: number;
    };
    alerts: YieldAlertRow[];
    notices: YieldNotice[];
  };
};

export const getYieldAlerts = (
  params: {
    project_id?: string;
    hours?: number;
  },
  signal?: AbortSignal
) => {
  return http.request<YieldAlertResult>(
    "get",
    `${API_PREFIX}/system/query/yield-alerts`,
    { params, signal }
  );
};

export type ManualRecipient = {
  department: string;
  name: string;
  phone: string;
};

export type ManualNotice = {
  id: number;
  from_dept: string;
  topic: string;
  body: string;
  recipients: ManualRecipient[];
  created_at: string;
};

export const listManualNotices = (signal?: AbortSignal) => {
  return http.request<{ success: boolean; data: { notices: ManualNotice[] } }>(
    "get",
    `${API_PREFIX}/system/manual-notices`,
    { signal }
  );
};

export const sendManualNotice = (data: {
  from_dept: string;
  topic: string;
  body: string;
  recipients: ManualRecipient[];
}) => {
  return http.request<{ success: boolean; data: ManualNotice }>(
    "post",
    `${API_PREFIX}/system/manual-notices`,
    { data }
  );
};

export const deleteManualNotice = (id: number) => {
  return http.request("delete", `${API_PREFIX}/system/manual-notices/${id}`);
};
