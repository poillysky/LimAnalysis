/**
 * CDP 批量截图：登录 LimAnalysis → 逐个路由渲染 → 截图。
 *
 * 为什么需要它：改版前必须先真实渲染看清现状（技能 SKILL.md §0 第 1 条），
 * 而这个应用有鉴权，直接导航会被路由守卫弹回登录页。
 *
 * 登录方式：在同源页面里 fetch /api/v1/auth/login，把返回的 token 写进
 * Cookie（键名 authorized-token，值是 {accessToken,expires,refreshToken} 的 JSON）
 * 与 localStorage（键名 user-info），然后 reload 让路由守卫放行。
 *
 * 用法：
 *   node .tmpdl/cdp-shoot.mjs <输出目录>
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const PORT = process.env.CDP_PORT || '9333';
const OUT_DIR = process.argv[2] || '.tmpdl/shots';
const VW = Number(process.env.VW || 1440);
const VH = Number(process.env.VH || 900);
const APP = process.env.APP || 'http://127.0.0.1:8848/';

// 要截的路由（hash 路由）。挑代表性页面：外壳 + 数据表格 + 图表 + 配置页 + 登录
const ROUTES = [
  ['welcome', '/welcome'],
  ['exception-query', '/exception/query'],
  ['exception-cavity', '/exception/cavity'],
  ['defect-analysis', '/defect/analysis'],
  ['feature-etl', '/feature/etl'],
];

mkdirSync(OUT_DIR, { recursive: true });

const ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
const ws = new WebSocket(ver.webSocketDebuggerUrl);

let msgId = 0;
let sessionId = null; // attach 到 page target 后填；之后所有命令都带它
const pending = new Map();

ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const { resolve, reject } = pending.get(m.id);
    pending.delete(m.id);
    m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result);
  }
});

/**
 * 发命令。注意 /json/version 给的是**浏览器级**端点的 ws，
 * 它没有 Page/Runtime 域 —— 必须先 Target.createTarget 开一个 page，
 * 再 attach 拿到 sessionId，后续命令都挂在这个 session 上。
 * 直接对浏览器端点发 Page.enable 会报 "'Page.enable' wasn't found"。
 */
const send = (method, params = {}, useSession = true) =>
  new Promise((resolve, reject) => {
    const id = ++msgId;
    pending.set(id, { resolve, reject });
    const msg = { id, method, params };
    if (useSession && sessionId) msg.sessionId = sessionId;
    ws.send(JSON.stringify(msg));
  });

const sleep = ms => new Promise(r => setTimeout(r, ms));

/** 轮询直到条件成立或超时。比死等 sleep 可靠。 */
async function waitFor(expr, timeoutMs = 25000, label = '') {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result?.value) return true;
    await sleep(400);
  }
  console.warn(`    ⚠️ 等待超时(${label}): ${expr.slice(0, 60)}`);
  return false;
}

async function evaluate(expression) {
  const r = await send('Runtime.evaluate', {
    expression, returnByValue: true, awaitPromise: true, userGesture: true,
  });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + ' ' + (r.exceptionDetails.exception?.description || ''));
  return r.result?.value;
}

async function shot(name) {
  const r = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  const p = join(OUT_DIR, `${name}.png`);
  writeFileSync(p, Buffer.from(r.data, 'base64'));
  console.log(`    📸 ${p}`);
}

await new Promise((res, rej) => {
  ws.addEventListener('open', res);
  ws.addEventListener('error', rej);
});

// 开一个 page target 并 attach，之后所有命令都在这个 session 上发
const { targetId } = await send('Target.createTarget', { url: 'about:blank' }, false);
const attached = await send('Target.attachToTarget', { targetId, flatten: true }, false);
sessionId = attached.sessionId;
console.log(`page target: ${targetId}  session: ${sessionId.slice(0, 12)}…`);

await send('Page.enable');
await send('Runtime.enable');
await send('Network.enable');
await send('Network.setCacheDisabled', { cacheDisabled: true });
await send('Emulation.setDeviceMetricsOverride', {
  width: VW, height: VH, deviceScaleFactor: 1, mobile: false,
});

console.log(`视口 ${VW}x${VH}  应用 ${APP}`);

// ── 1. 先开应用根路径（此时会停在登录页），拿到同源上下文
await send('Page.navigate', { url: APP });
await sleep(3500);
await waitFor(`!!document.querySelector('body')`, 15000, 'body');

// ── 2. 走应用自己的登录表单，而不是手写 Cookie/localStorage。
//
// 为什么放弃手写凭据：守卫的条件是 `Cookies.get('multiple-tabs') && storageLocal()['user-info']`，
// 而 storageLocal 来自 @pureadmin/utils —— 它对 key/value 的封装方式不明
// （可能加前缀或改序列化），手写的 localStorage 它读不到，导致守卫持续判未登录。
// 与其逆向它的存储实现，不如直接填表单 + 点按钮，走应用自己的 setToken 流程，
// 这样凭据格式天然一致，不会有"我以为是这个格式"的问题。
//
// 要点：给 Vue 绑定的 input 赋值必须用 native setter 再派发 input 事件，
// 直接 `el.value = x` 不会触发 v-model 更新。
const loginResult = await evaluate(`(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const setVal = (el, v) => {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const u = document.querySelector('input[placeholder="输入账号"]');
  const p = document.querySelector('input[placeholder="输入密码"]');
  if (!u || !p) return 'NO_INPUT: ' + JSON.stringify({
    inputs: [...document.querySelectorAll('input')].map(i => i.placeholder || i.type).slice(0, 8),
  });
  setVal(u, 'admin');
  setVal(p, 'admin123');
  await sleep(400);
  const btn = [...document.querySelectorAll('button')]
    .find(b => (b.textContent || '').includes('登录'));
  if (!btn) return 'NO_BUTTON: ' + JSON.stringify(
    [...document.querySelectorAll('button')].map(b => (b.textContent || '').trim().slice(0, 20)));
  btn.click();
  await sleep(3500);
  return 'clicked; hash=' + location.hash + ' hasLoginPage=' + !!document.querySelector('.login-page');
})()`);
console.log(`  登录: ${loginResult}`);
if (!String(loginResult).startsWith('clicked')) {
  console.error('登录未成功（输入框/按钮没找到或未跳转），中止。');
  process.exit(1);
}

// ── 3. 等登录后的跳转完成（离开登录页）
await waitFor(
  `!document.querySelector('.login-page')`,
  25000,
  'after-reload'
);

// ── 4. 逐个路由：设置 hash → 等外壳渲染出来 → 截图
for (const [name, route] of ROUTES) {
  console.log(`  → ${route}`);
  await evaluate(`location.hash = '#${route}'; 'ok'`);
  // 判据：已离开登录页，且 hash 已落在目标路由上（守卫放行的信号），
  // 且 #app 里已经渲染出内容。不用具体布局类名，避免类名变了就恒真/恒假。
  // 注意：hash 形如 `#/welcome`，所以要跟 `'#${route}'` 全等比较；
  // 早前写成 indexOf(route) === 0 是错的 —— '#' 占一位，indexOf 永远返回 1。
  await waitFor(
    `!document.querySelector('.login-page')
     && location.hash === '#${route}'
     && (document.querySelector('#app')?.children.length || 0) > 0`,
    25000,
    route
  );
  await sleep(2500); // 留给图表 / 表格异步数据渲染
  await shot(name);
}

// ── 5. 登录页也截一张（清掉凭据后重载）
await evaluate(`(() => {
  document.cookie = 'authorized-token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
  localStorage.clear();
  return 'cleared';
})()`);
await send('Page.navigate', { url: APP });
await sleep(3500);
await waitFor(`!!document.querySelector('.login-page')`, 15000, 'login');
await sleep(1500);
await shot('login');

console.log('\n完成');
ws.close();
process.exit(0);
