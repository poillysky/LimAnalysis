import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type AiConfig = {
  enabled: boolean;
  provider: string;
  base_url: string;
  model: string;
  timeout_seconds: number;
  temperature: number;
  api_key_set: boolean;
  ready: boolean;
  workshop_offline?: boolean;
};

export const getAiConfig = () => {
  return http.request<{ success: boolean; data: AiConfig }>(
    "get",
    `${API_PREFIX}/ai/config`
  );
};

export const saveAiConfig = (payload: {
  enabled?: boolean;
  provider?: string;
  base_url?: string;
  model?: string;
  timeout_seconds?: number;
  temperature?: number;
  api_key?: string;
  clear_api_key?: boolean;
}) => {
  return http.request<{ success: boolean; data: AiConfig }>(
    "put",
    `${API_PREFIX}/ai/config`,
    { data: payload }
  );
};

export const testAiConnection = () => {
  return http.request<{
    success: boolean;
    data: { ok: boolean; message: string; reply?: string };
  }>("post", `${API_PREFIX}/ai/test`, { timeout: 180000 });
};

export const listAiModels = () => {
  return http.request<{
    success: boolean;
    data: {
      ok: boolean;
      models: string[];
      current?: string;
      current_found?: boolean;
      message?: string;
    };
  }>("get", `${API_PREFIX}/ai/models`, { timeout: 60000 });
};
