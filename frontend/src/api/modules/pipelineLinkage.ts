import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type PipelineLinkage = {
  enabled: boolean;
  delay_seconds: number;
};

export const getPipelineLinkage = () => {
  return http.request<{ success: boolean; data: PipelineLinkage }>(
    "get",
    `${API_PREFIX}/system/pipeline-linkage`
  );
};

export const savePipelineLinkage = (payload: {
  enabled?: boolean;
  delay_seconds?: number;
}) => {
  return http.request<{ success: boolean; data: PipelineLinkage }>(
    "put",
    `${API_PREFIX}/system/pipeline-linkage`,
    { data: payload }
  );
};
