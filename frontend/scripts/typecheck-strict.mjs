/**
 * 严格类型守卫：分级守住 strict 基线
 *
 * 用法：node scripts/typecheck-strict.mjs  或  pnpm typecheck:strict
 *
 * ── 为什么需要这个脚本 ──────────────────────────────────────────────
 * 一开始试过「tsconfig.strict.json 只 include 业务目录」，看着很优雅，实际无效：
 * TS 的 `include` 只决定哪些文件是**入口**，`exclude` 只过滤 include 的匹配结果，
 * 两者都管不到「被 import 进来的文件」。而 `src/api/modules/*.ts` → `@/utils/http`
 * → `components/ReIcon`、`ReSegmented`，一条 import 链就把 300+ 模板层文件全拖进
 * 严格检查，398 个错误直接卡死 CI —— 等于什么都没守住。
 *
 * ── 现在的做法 ──────────────────────────────────────────────────────
 * 承认「模板层有存量债」这件事，然后分级：
 *   · 业务目录（views 除 login / api / utils 业务文件 / composables）→ 零容忍，一个都不许有
 *   · 模板层（layout / components / store / router / config / directives 等）→ 记账，
 *     数量记在 baseline.json 里，只许降不许涨
 * 这样每改一次业务代码，strict 都真实在跑；模板层的债则显式可见、可分期偿还。
 *
 * 退出码：0 = 通过（业务 0 错且模板层未超基线）；1 = 回归。
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, relative, sep } from "node:path";
import { spawnSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, ".."); // -> frontend/
const BASELINE_FILE = resolve(here, "typecheck-strict-baseline.json");

/**
 * 模板层目录（相对 frontend/，按最长前缀匹配）。
 * 这些是 pure-admin 骨架带进来的、尚未 strict 化的代码，不是本项目业务代码。
 * 唯一例外：views/login 也是模板带来的，所以排除在业务目录之外。
 */
const TEMPLATE_PREFIXES = [
  "src/layout",
  "src/components",
  "src/store",
  "src/router",
  "src/config",
  "src/directives",
  "src/utils/http",
  "src/utils/auth.ts",
  "src/utils/localforage",
  "src/utils/sso.ts",
  "src/utils/preventDefault.ts",
  "src/utils/tree.ts",
  "src/utils/genTree.ts",
  "src/utils/responsive-storage.ts",
  "src/views/login",
  "src/plugins",
  "src/style",
  "types"
];

/**
 * 判定优先级：先看是否在 TEMPLATE_PREFIXES 里，不在的就是业务代码。
 * 详见 classify() 里的注释 —— 默认严格是有意的设计。
 */

/** vue-tsc 的输出形如： src/xxx.vue(12,5): error TS2322: ... */
const DIAG_RE = /^(.+?)\((\d+),(\d+)\):\s+error\s+(TS\d+):\s*(.*)$/;

function classify(file) {
  const f = file.replace(/\\/g, "/");
  // 模板层优先：views/login 既是 views 的一部分，也属于模板遗留
  for (const p of TEMPLATE_PREFIXES) {
    if (f === p || f.startsWith(p + "/") || f.startsWith(p + sep)) return "template";
  }
  // ⚠️ 没列进 TEMPLATE_PREFIXES 的一律按业务代码零容忍处理。
  // 反过来（默认归模板层）会造成静默逃逸：新写的业务文件因为没登记就自动
  // 变成"模板层"，错误被基线吞掉，守卫等于没守。所以新文件默认最严，
  // 要豁免必须显式加进 TEMPLATE_PREFIXES —— 这个方向上"忘记登记"的代价
  // 是 CI 报错（吵但安全），而不是 CI 静默放过（安静但危险）。
  return "business";
}

const args = process.argv.slice(2);
const updateBaseline = args.includes("--update-baseline");

const proc = spawnSync(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["vue-tsc", "--noEmit", "-p", "tsconfig.strict.json"],
  { cwd: root, encoding: "utf8", shell: process.platform === "win32", maxBuffer: 64 * 1024 * 1024 }
);

const output = `${proc.stdout || ""}\n${proc.stderr || ""}`;
const diagnostics = [];
for (const line of output.split(/\r?\n/)) {
  const m = DIAG_RE.exec(line.trim());
  if (!m) continue;
  const [, file, lineNo, col, code, msg] = m;
  diagnostics.push({
    file: relative(root, resolve(root, file)).replace(/\\/g, "/"),
    pos: `${lineNo}:${col}`,
    code,
    msg,
    kind: classify(file)
  });
}

const business = diagnostics.filter(d => d.kind === "business");
const template = diagnostics.filter(d => d.kind === "template");

// 解析错误（配置写错、模块找不到等）不属于任何分类，必须直接失败
const infra = output
  .split(/\r?\n/)
  .filter(l => /error TS\d+/.test(l) && !DIAG_RE.test(l.trim()));

let baseline = { templateErrorCount: 0, files: [] };
if (existsSync(BASELINE_FILE)) {
  baseline = JSON.parse(readFileSync(BASELINE_FILE, "utf8"));
}

console.log("─".repeat(64));
console.log("strict 类型守卫");
console.log("─".repeat(64));
console.log(`  业务目录   : ${business.length} 个错误   ${business.length === 0 ? "✓" : "✗"}`);
console.log(`  模板层     : ${template.length} 个错误 / 基线 ${baseline.templateErrorCount}  ${
  template.length <= baseline.templateErrorCount ? "✓" : "✗ 超出基线"
}`);

if (infra.length) {
  console.log(`\n解析级错误 ${infra.length} 条（配置/模块解析问题，直接失败）：`);
  infra.slice(0, 20).forEach(l => console.log("  " + l.trim()));
}

if (business.length) {
  console.log(`\n业务目录的 strict 错误明细（必须修）：`);
  const byFile = new Map();
  for (const d of business) {
    if (!byFile.has(d.file)) byFile.set(d.file, []);
    byFile.get(d.file).push(d);
  }
  for (const [file, list] of byFile) {
    console.log(`\n  ${file}`);
    for (const d of list.slice(0, 20)) {
      console.log(`    (${d.pos}) ${d.code}: ${d.msg}`);
    }
    if (list.length > 20) console.log(`    ... 另有 ${list.length - 20} 条`);
  }
}

const failed =
  business.length > 0 ||
  template.length > baseline.templateErrorCount ||
  infra.length > 0 ||
  diagnostics.length === 0; // 一条错误都没解析出来，说明 vue-tsc 挂了，不能当通过

if (diagnostics.length === 0) {
  console.log("\n✗ 没解析到任何诊断，vue-tsc 可能自身失败（超时/崩溃）。不算通过。");
  console.log(output.split(/\r?\n/).slice(-15).join("\n"));
}

if (updateBaseline) {
  const files = {};
  for (const d of template) files[d.file] = (files[d.file] || 0) + 1;
  const next = {
    _comment: "模板层 strict 存量债基线，由 `pnpm typecheck:strict -- --update-baseline` 生成。只许降不许涨。",
    templateErrorCount: template.length,
    files: Object.fromEntries(Object.entries(files).sort((a, b) => b[1] - a[1]))
  };
  writeFileSync(BASELINE_FILE, JSON.stringify(next, null, 2) + "\n", "utf8");
  console.log(`\n✓ 基线已更新：模板层 ${template.length} 个错误 → ${relative(root, BASELINE_FILE)}`);
}

console.log("─".repeat(64));
if (failed && !updateBaseline) {
  console.log("✗ 未通过 —— 见上方明细。");
  process.exit(1);
}
console.log("✓ 通过");
