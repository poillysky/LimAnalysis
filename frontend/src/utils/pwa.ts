/** PWA 注册与「安装到桌面」提示（Edge / Chrome）。 */

export type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
};

export type InstallResult =
  | { ok: true }
  | { ok: false; reason: "standalone" | "no_prompt" | "dismissed" | "insecure" };

let deferred: BeforeInstallPromptEvent | null = null;
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach(fn => fn());
}

export function isStandaloneDisplay(): boolean {
  if (typeof window === "undefined") return false;
  const mq = window.matchMedia?.(
    "(display-mode: standalone), (display-mode: window-controls-overlay)"
  );
  if (mq?.matches) return true;
  return Boolean((navigator as Navigator & { standalone?: boolean }).standalone);
}

export function isSecureInstallContext(): boolean {
  if (typeof window === "undefined") return false;
  if (window.isSecureContext) return true;
  const host = window.location.hostname;
  return host === "localhost" || host === "127.0.0.1" || host === "[::1]";
}

/** 未装成独立窗口时，顶栏始终显示入口（不一定已拿到系统安装弹窗）。 */
export function shouldShowInstallEntry(): boolean {
  return !isStandaloneDisplay();
}

export function hasNativeInstallPrompt(): boolean {
  return Boolean(deferred);
}

export function onPwaInstallChange(fn: () => void): () => void {
  listeners.add(fn);
  fn();
  return () => {
    listeners.delete(fn);
  };
}

export function installGuideText(): string {
  if (!isSecureInstallContext()) {
    return [
      "当前地址不是 HTTPS / localhost，浏览器通常不允许安装 PWA。",
      "请改用 https://… 或 http://localhost 访问，或在 Edge 把该站点加入「将不安全的源视为安全」。",
      "",
      "临时做法：Edge 地址栏右侧 ··· → 应用 → 安装此站点为应用（若菜单可用）。"
    ].join("\n");
  }
  return [
    "若未自动弹出安装框，请用 Microsoft Edge：",
    "1. 地址栏右侧「应用可用」图标，或",
    "2. 菜单 ··· → 应用 → 安装此站点为应用",
    "3. 安装后可固定到任务栏 / 发送到桌面",
    "",
    "需先部署 pnpm build 产物（开发模式默认不注册 Service Worker）。"
  ].join("\n");
}

export async function promptInstallPwa(): Promise<InstallResult> {
  if (isStandaloneDisplay()) {
    return { ok: false, reason: "standalone" };
  }
  if (!isSecureInstallContext()) {
    return { ok: false, reason: "insecure" };
  }
  if (!deferred) {
    return { ok: false, reason: "no_prompt" };
  }
  const event = deferred;
  deferred = null;
  notify();
  await event.prompt();
  const choice = await event.userChoice;
  if (choice.outcome === "accepted") {
    return { ok: true };
  }
  return { ok: false, reason: "dismissed" };
}

export function registerPwa() {
  if (typeof window === "undefined") return;

  window.addEventListener("beforeinstallprompt", event => {
    event.preventDefault();
    deferred = event as BeforeInstallPromptEvent;
    notify();
  });

  window.addEventListener("appinstalled", () => {
    deferred = null;
    notify();
    document.documentElement.classList.add("is-pwa");
  });

  const mq = window.matchMedia?.(
    "(display-mode: standalone), (display-mode: window-controls-overlay)"
  );
  mq?.addEventListener?.("change", () => notify());

  if (isStandaloneDisplay()) {
    document.documentElement.classList.add("is-pwa");
  }
}
