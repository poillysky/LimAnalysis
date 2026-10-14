import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type ScanProject = {
  project_id: string;
  display_name: string;
};

export type ScanDefectOption = {
  key: string;
  label: string;
};

export type DefectScanOp = {
  id: number;
  project_id: string;
  project_name: string;
  defect_item: string;
  method: string;
  method_label: string;
  count: number;
  created_at: string;
};

export const getScanBootstrap = (projectId?: string, signal?: AbortSignal) => {
  return http.request<{
    success: boolean;
    data: {
      projects: ScanProject[];
      current_id: string;
      defects: ScanDefectOption[];
    };
  }>("get", `${API_PREFIX}/scan/defect/bootstrap`, {
    params: projectId ? { project_id: projectId } : {},
    signal
  });
};

export type DefectScanBatchResult = {
  count: number;
  op: DefectScanOp;
};

export const listDefectScans = (
  params: {
    project_id?: string;
    defect_item?: string;
    limit?: number;
  },
  signal?: AbortSignal
) => {
  return http.request<{ success: boolean; data: { ops: DefectScanOp[] } }>(
    "get",
    `${API_PREFIX}/scan/defect/scans`,
    { params, signal }
  );
};

export const createDefectScan = (data: {
  project_id: string;
  defect_item: string;
  sn: string;
}) => {
  return http.request<{ success: boolean; data: DefectScanBatchResult }>(
    "post",
    `${API_PREFIX}/scan/defect/scans`,
    { data }
  );
};

export const getDefectScanItems = (projectId: string, signal?: AbortSignal) => {
  return http.request<{
    success: boolean;
    data: {
      project_id: string;
      items: string[];
      projects: ScanProject[];
    };
  }>("get", `${API_PREFIX}/scan/defect/items`, {
    params: { project_id: projectId },
    signal
  });
};

export const saveDefectScanItems = (data: {
  project_id: string;
  items: string[];
}) => {
  return http.request<{
    success: boolean;
    data: { project_id: string; items: string[] };
  }>("put", `${API_PREFIX}/scan/defect/items`, { data });
};

export const createDefectScanBatch = (data: {
  project_id: string;
  defect_item: string;
  sns: string[];
}) => {
  return http.request<{ success: boolean; data: DefectScanBatchResult }>(
    "post",
    `${API_PREFIX}/scan/defect/scans/batch`,
    { data, timeout: 60000 }
  );
};

export const importDefectScans = (
  projectId: string,
  defectItem: string,
  file: File
) => {
  const data = new FormData();
  data.append("project_id", projectId);
  data.append("defect_item", defectItem);
  data.append("file", file);
  return http.request<{ success: boolean; data: DefectScanBatchResult }>(
    "post",
    `${API_PREFIX}/scan/defect/scans/import`,
    { data, timeout: 60000 }
  );
};

export type DefectAnalysisRow = {
  machine?: string;
  body?: string;
  cavity: string;
  qty: number;
  ng: number;
  rate: number | null;
  rate_pct: number | null;
};

export type CavityDuty = "白班" | "夜班";

export type DefectAnalysisDatesResult = {
  success: boolean;
  data: {
    project_id: string;
    today: string;
    /** 当前班次归属生产日（凌晨夜班为昨天） */
    default_date?: string;
    duty: CavityDuty | string;
    dates: string[];
    total: number;
  };
};

export const getDefectAnalysisDates = (
  projectId: string,
  signal?: AbortSignal
) => {
  return http.request<DefectAnalysisDatesResult>(
    "get",
    `${API_PREFIX}/scan/defect/analysis-dates`,
    {
      params: { project_id: projectId },
      signal
    }
  );
};

export const getDefectAnalysis = (
  params: {
    project_id: string;
    hours?: number;
    date?: string;
    duty?: CavityDuty | string;
    defect_item?: string;
    exclude_machine_cavities?: string;
    exclude_body_cavities?: string;
  },
  signal?: AbortSignal
) => {
  return http.request<{
    success: boolean;
    data: {
      project_id: string;
      hours: number;
      date?: string;
      duty?: string;
      from_hour: string;
      to_hour: string;
      defect_item: string;
      machines: DefectAnalysisRow[];
      bodies: DefectAnalysisRow[];
    };
  }>("get", `${API_PREFIX}/scan/defect/analysis`, {
    params: {
      project_id: params.project_id,
      date: params.date || undefined,
      duty: params.duty || undefined,
      hours: params.date ? undefined : params.hours,
      defect_item: params.defect_item || undefined,
      exclude_machine_cavities: params.exclude_machine_cavities || undefined,
      exclude_body_cavities: params.exclude_body_cavities || undefined
    },
    signal,
    timeout: 60000
  });
};

export const getDefectAnalysisRules = (signal?: AbortSignal) => {
  return http.request<{ success: boolean; data: Record<string, number> }>(
    "get",
    `${API_PREFIX}/scan/defect/analysis-rules`,
    { signal }
  );
};

export const saveDefectAnalysisRules = (data: Record<string, number>) => {
  return http.request<{ success: boolean; data: Record<string, number> }>(
    "put",
    `${API_PREFIX}/scan/defect/analysis-rules`,
    { data }
  );
};
