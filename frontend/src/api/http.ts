/** 自建后端统一前缀（含登录）。 */
export const API_PREFIX = "/api/v1";

export function backendErrorHint(error: unknown): string {
  const err = error as {
    code?: string;
    message?: string;
    response?: { status?: number; data?: { message?: string } };
  };
  if (!err.response) {
    if (err.code === "ECONNABORTED" || /timeout/i.test(err.message || "")) {
      return "请求超时。AI 生成可能需要几十秒，请稍后重试，或到 AI 模型配置里加大超时时间。";
    }
    return "无法连接后端。先启动 API，再刷新本页。";
  }
  return err.response.data?.message || `请求失败（${err.response.status}）`;
}
