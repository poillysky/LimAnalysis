import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type MachineGroup = {
  name: string;
  machines: string[];
};

export type OwnerRoles = {
  production: number[];
  quality: number[];
  process: number[];
};

export type ProjectOwners = {
  injection: OwnerRoles;
  lim: OwnerRoles;
  finished: OwnerRoles;
  structure_rd: number[];
  pm: number[];
};

/** CSV 原列名 → 入库列名，如 BCoverSN → FCoverSN */
export type ColumnMapItem = {
  source: string;
  target: string;
};

export type ProjectItem = {
  project_id: string;
  display_name: string;
  enabled: boolean;
  sfc_code?: string;
  btype?: string;
  prefix?: string;
  machines?: string[];
  /** 外观机自由列表，如 GV-0701 */
  appearance_machines?: string[];
  /** 外观视角名（登记后预警异常说明按此排除） */
  appearance_views?: string[];
  owners?: ProjectOwners;
  column_map?: ColumnMapItem[];
};

export type ProjectListResult = {
  success: boolean;
  data: {
    defaults: Record<string, unknown>;
    projects: ProjectItem[];
    machine_catalog?: { groups: MachineGroup[] };
  };
};

export const listProjects = () => {
  return http.request<ProjectListResult>("get", `${API_PREFIX}/system/projects`);
};

export const createProject = (
  data: Partial<ProjectItem> & {
    display_name: string;
    machines?: string[];
    appearance_machines?: string[];
    appearance_views?: string[];
  }
) => {
  return http.request("post", `${API_PREFIX}/system/projects`, { data });
};

export const updateProject = (projectId: string, data: Partial<ProjectItem>) => {
  const id = encodeURIComponent(String(projectId || "").trim());
  return http.request("put", `${API_PREFIX}/system/projects/${id}`, {
    data
  });
};

export const deleteProject = (projectId: string) => {
  const id = encodeURIComponent(String(projectId || "").trim());
  return http.request("delete", `${API_PREFIX}/system/projects/${id}`);
};

/** 视角名下拉选项：项目聚合度量 *不良数 → 去掉后缀 */
export const listAppearanceViewOptions = (projectId: string) => {
  const id = encodeURIComponent(String(projectId || "").trim());
  return http.request<{
    success: boolean;
    data: { project_id: string; items: string[] };
  }>("get", `${API_PREFIX}/system/projects/${id}/appearance-view-options`);
};
