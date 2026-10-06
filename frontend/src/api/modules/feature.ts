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

export type ProjectItem = {
  project_id: string;
  display_name: string;
  enabled: boolean;
  sfc_code?: string;
  btype?: string;
  prefix?: string;
  machines?: string[];
  owners?: ProjectOwners;
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
  data: Partial<ProjectItem> & { display_name: string; machines?: string[] }
) => {
  return http.request("post", `${API_PREFIX}/system/projects`, { data });
};

export const updateProject = (projectId: string, data: Partial<ProjectItem>) => {
  return http.request("put", `${API_PREFIX}/system/projects/${projectId}`, {
    data
  });
};

export const deleteProject = (projectId: string) => {
  return http.request("delete", `${API_PREFIX}/system/projects/${projectId}`);
};
