import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

type Result = {
  success: boolean;
  data: Array<any>;
};

export const getAsyncRoutes = () => {
  return http.request<Result>("get", `${API_PREFIX}/auth/routes`);
};
