import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type PhotoSource = "mold" | "appearance";
export type AppearanceDim = "tester" | "mold";

export type InspectionProject = {
  project_id: string;
  display_name: string;
  machines: string[];
};

export type InspectionSettings = {
  mold_root_path: string;
  appearance_root_path: string;
};

export type InspectionDirItem = {
  path: string;
  name: string;
};

export type InspectionDirListing = {
  parent: string;
  up: string;
  dirs: InspectionDirItem[];
};

export type InspectionImage = {
  id: string;
  machine: string;
  cavity: string;
  filename: string;
  date_str: string;
  rel_path: string;
  view_url: string;
  /** 文件名解析出的二维码 / SN */
  sn?: string;
  /** lim_raw.ServerTime，ISO 或可解析时间串 */
  server_time?: string | null;
  status?: string;
  camera?: string;
};

export type AppearanceViewCount = {
  camera: string;
  count: number;
};

export const getInspectionBootstrap = () => {
  return http.request<{
    success: boolean;
    data: {
      projects: InspectionProject[];
      settings: InspectionSettings;
      cavities: string[];
      statuses: string[];
      ready: { mold: boolean; appearance: boolean };
    };
  }>("get", `${API_PREFIX}/inspection/bootstrap`);
};

export const saveInspectionSettings = (data: Partial<InspectionSettings>) => {
  return http.request<{ success: boolean; data: InspectionSettings }>(
    "put",
    `${API_PREFIX}/inspection/settings`,
    { data }
  );
};

export const getInspectionDirs = (parent = "") => {
  return http.request<{
    success: boolean;
    data: {
      parent: string;
      up: string;
      dirs: { path: string; name: string }[];
    };
  }>("get", `${API_PREFIX}/inspection/dirs`, {
    params: { parent: parent || undefined }
  });
};

export const getViewerFolders = (
  projectId: string,
  tester = "",
  dim: AppearanceDim = "tester"
) => {
  return http.request<{
    success: boolean;
    data: {
      dim?: AppearanceDim;
      testers: string[];
      cameras: string[];
      machines?: string[];
      cavities?: string[];
      project_folder?: string;
    };
  }>("get", `${API_PREFIX}/inspection/viewer/folders`, {
    params: {
      project_id: projectId,
      tester: tester || undefined,
      source: "appearance",
      dim
    }
  });
};

export const getViewerDates = (
  projectId: string,
  machine: string,
  source: PhotoSource = "mold",
  camera = "",
  dim: AppearanceDim = "tester",
  /** 本体号如 A1；有值时按本体口径，可不传机台 */
  body = ""
) => {
  return http.request<{
    success: boolean;
    data: {
      dates: string[];
      today: string;
      default_date: string;
      layout: string;
      dim?: AppearanceDim | string;
      body?: string;
      cavities: string[];
      statuses: string[];
      testers?: string[];
      cameras?: string[];
      machines?: string[];
    };
  }>("get", `${API_PREFIX}/inspection/viewer/dates`, {
    params: {
      project_id: projectId,
      machine: machine || undefined,
      body: body || undefined,
      source,
      camera: camera || undefined,
      dim: source === "appearance" && !body ? dim : undefined
    }
  });
};

export const getViewerImages = (params: {
  project_id: string;
  machine?: string;
  cavity?: string;
  date: string;
  status?: string;
  source?: PhotoSource;
  dim?: AppearanceDim;
  camera?: string;
  /** 本体号如 A1；与 machine×cavity 互斥 */
  body?: string;
  /** desc=ServerTime 最新优先（交叉表/通知弹窗）；默认 asc */
  order?: "asc" | "desc";
}) => {
  return http.request<{
    success: boolean;
    data: {
      images: InspectionImage[];
      total_count: number;
      machine?: string;
      cavity?: string;
      body?: string;
      date_str: string;
      status?: string;
      camera?: string;
      dim?: AppearanceDim | string;
      hint?: string;
      sn_count?: number;
    };
  }>("get", `${API_PREFIX}/inspection/viewer/images`, {
    params: {
      project_id: params.project_id,
      machine: params.machine || undefined,
      cavity: params.cavity || undefined,
      body: params.body || undefined,
      date: params.date,
      status: params.status || "OK",
      source: params.source || "mold",
      dim: params.body ? undefined : params.dim || undefined,
      camera: params.camera || undefined,
      order: params.order || undefined
    },
    timeout: 120000
  });
};

/** 外观各视角数量：mold=生产日命中；tester=截图日目录张数；可按本体号 */
export const getAppearanceViewCounts = (params: {
  project_id: string;
  machine?: string;
  date: string;
  cavity?: string;
  body?: string;
  dim?: AppearanceDim;
}) => {
  return http.request<{
    success: boolean;
    data: {
      cameras: AppearanceViewCount[];
      date_str: string;
      sn_count?: number;
      dim?: AppearanceDim | string;
      body?: string;
    };
  }>("get", `${API_PREFIX}/inspection/viewer/appearance-view-counts`, {
    params: {
      project_id: params.project_id,
      machine: params.machine || undefined,
      cavity: params.cavity || undefined,
      body: params.body || undefined,
      date: params.date,
      dim: params.body ? "mold" : params.dim || "mold"
    },
    timeout: 120000
  });
};

export const searchViewerImages = (
  projectId: string,
  query: string,
  source: PhotoSource = "mold",
  dim?: AppearanceDim
) => {
  return http.request<{
    success: boolean;
    data: {
      images: InspectionImage[];
      total_count: number;
      query: string;
      hint?: string;
      dim?: AppearanceDim;
    };
  }>("get", `${API_PREFIX}/inspection/viewer/search`, {
    params: {
      project_id: projectId,
      q: query,
      source,
      ...(source === "appearance" && dim ? { dim } : {})
    },
    timeout: 120000
  });
};

export type AppearanceIndexStatus = {
  project_id?: string;
  project_key?: string;
  status: "building" | "ready" | "empty" | string;
  status_label: string;
  building?: boolean;
  dir_count?: number;
  file_count?: number;
  indexed_label?: string;
  warm_started?: boolean;
};

export const getAppearanceIndexStatus = (projectId: string) => {
  return http.request<{ success: boolean; data: AppearanceIndexStatus }>(
    "get",
    `${API_PREFIX}/inspection/viewer/appearance-index`,
    { params: { project_id: projectId } }
  );
};

/** 进页后台全量建/刷；之后只增量 */
export const warmAppearanceIndex = (projectId: string) => {
  return http.request<{ success: boolean; data: AppearanceIndexStatus }>(
    "post",
    `${API_PREFIX}/inspection/viewer/appearance-index/warm`,
    { params: { project_id: projectId } }
  );
};
