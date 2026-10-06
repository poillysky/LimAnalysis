import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type PhotoSource = "mold" | "appearance";

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
  status?: string;
  camera?: string;
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

export const getViewerFolders = (projectId: string, tester = "") => {
  return http.request<{
    success: boolean;
    data: {
      testers: string[];
      cameras: string[];
      project_folder?: string;
    };
  }>("get", `${API_PREFIX}/inspection/viewer/folders`, {
    params: {
      project_id: projectId,
      tester: tester || undefined,
      source: "appearance"
    }
  });
};

export const getViewerDates = (
  projectId: string,
  machine: string,
  source: PhotoSource = "mold",
  camera = ""
) => {
  return http.request<{
    success: boolean;
    data: {
      dates: string[];
      today: string;
      default_date: string;
      layout: string;
      cavities: string[];
      statuses: string[];
      testers?: string[];
      cameras?: string[];
    };
  }>("get", `${API_PREFIX}/inspection/viewer/dates`, {
    params: {
      project_id: projectId,
      machine,
      source,
      camera: camera || undefined
    }
  });
};

export const getViewerImages = (params: {
  project_id: string;
  machine: string;
  cavity: string;
  date: string;
  status?: string;
  source?: PhotoSource;
}) => {
  return http.request<{
    success: boolean;
    data: {
      images: InspectionImage[];
      total_count: number;
      machine: string;
      cavity: string;
      date_str: string;
      status: string;
    };
  }>("get", `${API_PREFIX}/inspection/viewer/images`, {
    params: {
      project_id: params.project_id,
      machine: params.machine,
      cavity: params.cavity,
      date: params.date,
      status: params.status || "OK",
      source: params.source || "mold"
    },
    timeout: 120000
  });
};

export const searchViewerImages = (
  projectId: string,
  query: string,
  source: PhotoSource = "mold"
) => {
  return http.request<{
    success: boolean;
    data: {
      images: InspectionImage[];
      total_count: number;
      query: string;
    };
  }>("get", `${API_PREFIX}/inspection/viewer/search`, {
    params: { project_id: projectId, q: query, source },
    timeout: 120000
  });
};
