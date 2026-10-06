import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type BoardProject = {
  project_id: string;
  display_name: string;
  has_board: boolean;
};

export type BoardKind = "appearance" | "mold" | "main";

export type BoardOption = {
  kind: BoardKind;
  label: string;
  name?: string;
  dashboard_id?: number;
};

export type BoardCurrent = {
  project_id: string;
  display_name: string;
  embed_url: string;
  dashboard_id?: number;
  board?: BoardKind | "";
  boards?: BoardOption[];
};

export type BoardResult = {
  success: boolean;
  data: {
    projects: BoardProject[];
    current: BoardCurrent | null;
    error: string | null;
  };
};

export const getMetabaseBoard = (projectId?: string, board?: string) => {
  return http.request<BoardResult>("get", `${API_PREFIX}/system/metabase/board`, {
    params: {
      ...(projectId ? { project_id: projectId } : {}),
      ...(board ? { board } : {})
    }
  });
};

export type QueryProject = {
  project_id: string;
  display_name: string;
};

export type QueryDimField = {
  key: "line" | "machine" | "cavity" | "core";
  column: string;
  label: string;
};

export type QueryMetric = {
  key: string;
  label: string;
};

export type QueryFilters = {
  line?: string;
  machine?: string;
  cavity?: string;
  core?: string;
  cavity_letter?: string;
  body_mold?: string;
  body_cavity?: string;
};

export type QueryCatalogResult = {
  success: boolean;
  data: {
    projects: QueryProject[];
    current: {
      project_id: string;
      display_name: string;
      prefix: string;
    } | null;
    ready: boolean;
    dims: Record<string, string[]>;
    dim_fields: QueryDimField[];
    metrics: QueryMetric[];
  };
};

export type QueryHourRow = {
  hour: string;
  hour_label: string;
  qty: number;
  ng: number;
  rate: number | null;
  rate_pct: number | null;
};

export type QuerySeriesResult = {
  success: boolean;
  data: {
    metric: string;
    metric_label: string;
    filters: QueryFilters;
    rows: QueryHourRow[];
    total: number;
  };
};

export const getQueryCatalog = (
  projectId?: string,
  filters?: QueryFilters,
  signal?: AbortSignal
) => {
  return http.request<QueryCatalogResult>("get", `${API_PREFIX}/system/query/catalog`, {
    params: {
      ...(projectId ? { project_id: projectId } : {}),
      ...(filters || {})
    },
    signal
  });
};

export const getQuerySeries = (
  projectId: string,
  metric: string,
  filters?: QueryFilters,
  signal?: AbortSignal
) => {
  return http.request<QuerySeriesResult>("get", `${API_PREFIX}/system/query/series`, {
    params: { project_id: projectId, metric, ...(filters || {}) },
    signal
  });
};

export type MachineCavityRow = {
  machine: string;
  cavity: string;
  qty: number;
  ng: number;
  rate: number | null;
  rate_pct: number | null;
};

export type MachineCavityResult = {
  success: boolean;
  data: {
    project_id: string;
    metric: string;
    metric_label: string;
    hours: number;
    from_hour: string;
    to_hour: string;
    rows: MachineCavityRow[];
    total: number;
  };
};

export type CavityQueryExtra = {
  excludeMachineCavities?: string[];
  excludeBodyCavities?: string[];
};

export const getMachineCavityRates = (
  projectId: string,
  hours = 3,
  metric = "appearance",
  signal?: AbortSignal,
  extra?: CavityQueryExtra
) => {
  return http.request<MachineCavityResult>(
    "get",
    `${API_PREFIX}/system/query/machine-cavity`,
    {
      params: {
        project_id: projectId,
        hours,
        metric,
        exclude_machine_cavities:
          extra?.excludeMachineCavities?.join(",") || undefined,
        exclude_body_cavities:
          extra?.excludeBodyCavities?.join(",") || undefined
      },
      signal
    }
  );
};

export type BodyCavityRow = {
  body: string;
  cavity: string;
  qty: number;
  ng: number;
  rate: number | null;
  rate_pct: number | null;
};

export type BodyCavityResult = {
  success: boolean;
  data: {
    project_id: string;
    metric: string;
    metric_label: string;
    hours: number;
    from_hour: string;
    to_hour: string;
    rows: BodyCavityRow[];
    total: number;
  };
};

export const getBodyCavityRates = (
  projectId: string,
  hours = 3,
  metric = "appearance",
  signal?: AbortSignal,
  extra?: CavityQueryExtra
) => {
  return http.request<BodyCavityResult>(
    "get",
    `${API_PREFIX}/system/query/body-cavity`,
    {
      params: {
        project_id: projectId,
        hours,
        metric,
        exclude_machine_cavities:
          extra?.excludeMachineCavities?.join(",") || undefined,
        exclude_body_cavities:
          extra?.excludeBodyCavities?.join(",") || undefined
      },
      signal
    }
  );
};
