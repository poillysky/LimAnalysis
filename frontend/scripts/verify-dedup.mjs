/**
 * 去重差分验证：旧 .vue 快照里的实现 vs 新 utils/pivotTable.ts，行为必须逐用例一致。
 * 用法：node scripts/verify-dedup.mjs
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { createRequire } from "node:module";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");   // -> frontend/
const SRC = resolve(root, "src");
const require = createRequire(import.meta.url);
const ts = require("typescript");

/** 用项目自带的 typescript 转译 TS 片段（不新增依赖） */
function transpile(code) {
  return ts.transpileModule(code, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020
    }
  }).outputText;
}

/**
 * 最小 computed / ref shim：只保留 getter 求值与 .value 读写，不做真响应式。
 *
 * 这里刻意用「不缓存」的 computed —— 差分时要能通过改依赖 ref 的 .value 来
 * 模拟换了一份数据，如果做了缓存就测不到「闭包是不是活引用」了。
 */
const shimComputed = fn => ({
  get value() {
    return fn();
  }
});
const shimRef = initial => ({ value: initial });

/** 抽取 alertRules 时 loadCavityAlertRules() 的桩值，随后会被测试用例覆盖 */
const DEFAULT_RULES = {
  cavityRateAbovePct: 5,
  cavityMinQty: 100,
  machineRateAbovePct: 8,
  machineMinQty: 200,
  bodyRateAbovePct: 3,
  bodyMinQty: 50
};

let pass = 0;
const fails = [];
const groups = [];

function eq(label, a, b) {
  const sa = JSON.stringify(a);
  const sb = JSON.stringify(b);
  if (sa === sb) {
    pass += 1;
  } else {
    fails.push({ label, old: sa, new: sb });
  }
}

function group(name) {
  groups.push({ name, n: 0 });
  return { hit: () => (groups[groups.length - 1].n += 1) };
}

// ---------- 1. 抽取旧实现 ----------
function scriptOf(p) {
  const t = readFileSync(p, "utf8");
  const m = /<script[^>]*>([\s\S]*?)<\/script>/.exec(t);
  return m ? m[1] : "";
}

/** 用项目自带 typescript 把 TS 片段转成可执行 JS */
function compileTs(code, label) {
  try {
    const mod = { exports: {} };
    // eslint-disable-next-line no-new-func
    new Function("module", "exports", transpile(code))(mod, mod.exports);
    return mod.exports;
  } catch (e) {
    throw new Error(`编译 ${label} 失败: ${e.message}`);
  }
}

/** 从 script 中抠出若干顶层声明，连同依赖一起转译 */
function extractOld(snapPath, names) {
  const src = scriptOf(snapPath);
  const blocks = [];
  for (const name of names) {
    const fnStart = new RegExp(`(?:^|\\n)function ${name}\\s*\\(`, "m").exec(
      src
    );
    if (fnStart) {
      const at = src.indexOf(`function ${name}`, fnStart.index);
      blocks.push(sliceFunction(src, at));
      continue;
    }
    const constStart = new RegExp(`(?:^|\\n)const ${name}\\b`, "m").exec(src);
    if (constStart) {
      const at = src.indexOf(`const ${name}`, constStart.index);
      const eq = src.indexOf("=", at);
      const lb = src.indexOf("[", eq);
      const ob = src.indexOf("{", eq);
      // 谁先出现用谁（跳过类型注解里的 Record<...> 与 { property?: string }）
      if (lb >= 0 && (ob < 0 || lb < ob)) {
        blocks.push(
          src.slice(at, lb) + sliceBalanced(src, lb, "[", "]")
        );
      } else if (
        // ⚠️ 特判：值是**函数调用**的 const，例如
        //    `const limAlertHint = computed(() => { ... })`
        // 这里第一个 `{` 是箭头函数体，光按 {} 配平会丢掉结尾的 `)`，
        // 拼出来的代码 `const x = computed(() => {...}` 直接语法错误。
        // 所以先按 () 配平整个调用表达式，再取其中第一个 {} 作为终止。
        /^[A-Za-z_$][\w$.]*\s*\(/.test(src.slice(eq + 1).trimStart())
      ) {
        const callOpen = src.indexOf("(", eq);
        const callEnd = sliceBalanced(src, callOpen, "(", ")").length + callOpen;
        blocks.push(src.slice(at, callEnd));
      } else {
        blocks.push(src.slice(at, ob) + sliceBalanced(src, ob, "{", "}"));
      }
      continue;
    }
    throw new Error(`在 ${snapPath} 中找不到 ${name}`);
  }
  const code = blocks.join("\n\n");
  const namesCsv = names.join(", ");
  const wrapped = `${code}\nmodule.exports = { ${namesCsv} };`;
  const mod = { exports: {} };
  // 旧快照里 `const alertRules = ref(loadCavityAlertRules())` 与
  // `const limAlertHint = computed(...)` 需要 vue 的 ref/computed；
  // 验证环境注入最小 shim，只关心求值结果与活引用语义。
  new Function(
    "module",
    "exports",
    "computed",
    "ref",
    "loadCavityAlertRules",
    transpile(wrapped)
  )(mod, mod.exports, shimComputed, shimRef, () => DEFAULT_RULES);
  return mod.exports;
}

/** 从函数声明起点截出完整函数（含解构参数） */
function sliceFunction(src, start) {
  const p = src.indexOf("(", start);
  if (p < 0) throw new Error(`找不到参数括号 @${start}`);
  let d = 0;
  let endParams = -1;
  for (let j = p; j < src.length; j += 1) {
    if (src[j] === "(") d += 1;
    else if (src[j] === ")") {
      d -= 1;
      if (d === 0) {
        endParams = j;
        break;
      }
    }
  }
  if (endParams < 0) throw new Error("参数未配平");
  const b = src.indexOf("{", endParams);
  if (b < 0) throw new Error("找不到函数体");
  return src.slice(start, b) + sliceBalanced(src, b, "{", "}");
}

/** 从 start 处按 open/close 配平截取（返回含 open 的片段） */
function sliceBalanced(src, start, open, close) {
  const i = src.indexOf(open, start);
  if (i < 0) throw new Error(`找不到 ${open}`);
  let depth = 0;
  for (let j = i; j < src.length; j += 1) {
    if (src[j] === open) depth += 1;
    else if (src[j] === close) {
      depth -= 1;
      if (depth === 0) return src.slice(start, j + 1);
    }
  }
  throw new Error(`括号未配平: ${open} @${start}`);
}

// ---------- 2. 载入新实现 ----------
// 抽掉 type-only import 后转译成 CJS 载入
const newSrc = readFileSync(resolve(SRC, "utils/pivotTable.ts"), "utf8")
  .replace(/^import type .*$/gm, "")
  .replace(/^import \{[^}]*\} from "@\/utils\/cavityAlert";?$/gm, "")
  // pivotTable.ts 里的 `import { computed } from "vue"`：验证环境不需要真响应式，
  // 用最小 shim 顶替，只关心 getter 求值结果是否与改前一致。
  .replace(/^import \{ computed \} from "vue";?$/gm, "");
const newMod = (() => {
  const mod = { exports: {} };
  new Function("module", "exports", "computed", transpile(newSrc))(
    mod,
    mod.exports,
    shimComputed
  );
  return mod.exports;
})();

const SNAP = process.env.LIM_SNAP_DIR;
if (!SNAP) {
  console.error("需要设置 LIM_SNAP_DIR 指向快照目录（去重前的 .vue 备份）");
  process.exit(2);
}
const cavitySnap = resolve(SNAP, "cavity.vue");
const scanSnap = resolve(SNAP, "scan.vue");

const PURE = [
  "isAbortError",
  "cavityLetter",
  "bodyCavityLetter",
  "rateOf",
  "formatQty",
  "formatRate",
  "cellText",
  "totalText",
  "cellStyle",
  "isAlert"
];

const oldCav = extractOld(cavitySnap, [
  ...PURE,
  "BODY_DIGIT_TO_LETTER",
  "CAVITY_LETTERS",
  "BODY_CAVITY_LETTERS"
]);
const oldScan = extractOld(scanSnap, [
  ...PURE,
  "BODY_DIGIT_TO_LETTER",
  "CAVITY_LETTERS",
  "BODY_CAVITY_LETTERS"
]);

console.log("=== 1. 纯函数差分（旧 cavity 快照 vs 新模块） ===");
{
  const g = group("纯函数");
  for (const name of PURE) {
    const o = oldCav[name];
    const n = newMod[name];
    if (typeof o !== "function" || typeof n !== "function") {
      fails.push({ label: `${name} 类型不符`, old: typeof o, new: typeof n });
      continue;
    }
    switch (name) {
      case "isAbortError": {
        for (const e of [
          null,
          undefined,
          {},
          { code: "ERR_CANCELED" },
          { name: "CanceledError" },
          { name: "AbortError" },
          { code: "ECONNABORTED" },
          { name: "Error" },
          "str",
          0
        ]) {
          eq(`${name}(${JSON.stringify(e)})`, o(e), n(e));
          g.hit();
        }
        break;
      }
      case "cavityLetter": {
        for (const c of [
          "1A",
          "a",
          "H",
          "  b  ",
          "12",
          "",
          null,
          undefined,
          "AB",
          "3R"
        ]) {
          eq(`${name}(${JSON.stringify(c)})`, o(c), n(c));
          g.hit();
        }
        break;
      }
      case "bodyCavityLetter": {
        for (const c of ["1", "8", " 3 ", "9", "", null, undefined, "A"]) {
          eq(`${name}(${JSON.stringify(c)})`, o(c), n(c));
          g.hit();
        }
        break;
      }
      case "rateOf": {
        for (const [q, ng] of [
          [100, 5],
          [0, 5],
          [0, 0],
          [3, 1],
          [7, 2],
          [-5, 1],
          [1, 0]
        ]) {
          eq(`${name}(${q},${ng})`, o(q, ng), n(q, ng));
          g.hit();
        }
        break;
      }
      case "formatQty":
      case "formatRate": {
        for (const v of [0, 1234, 1234567, null, undefined, -5, 1.5]) {
          eq(`${name}(${String(v)})`, o(v), n(v));
          g.hit();
        }
        break;
      }
      case "cellText":
      case "totalText": {
        const rows = [
          {
            entity: "M1",
            metric: "qty",
            metricLabel: "产量",
            cells: { A: 100, B: null },
            qtys: { A: 100, B: 50 },
            totalQty: 150,
            totalNg: 5,
            totalRate: 3.33
          },
          {
            entity: "汇总",
            metric: "rate",
            metricLabel: "不良率",
            cells: { A: 3.33, B: 0 },
            qtys: { A: 100, B: 50 },
            totalQty: 150,
            totalNg: 5,
            totalRate: 3.33,
            isTotal: true
          }
        ];
        for (const r of rows) {
          if (name === "cellText") {
            for (const l of ["A", "B", "Z"]) {
              eq(`${name}(${r.metric},${l})`, o(r, l), n(r, l));
              g.hit();
            }
          } else {
            eq(`${name}(${r.metric})`, o(r), n(r));
            g.hit();
          }
        }
        break;
      }
      case "cellStyle": {
        for (const [prop, isTotal] of [
          ["entity", false],
          ["total", false],
          ["c_A", false],
          ["c_A", true]
        ]) {
          const row = {
            entity: "M1",
            metric: "rate",
            metricLabel: "不良率",
            cells: {},
            qtys: {},
            totalQty: 1,
            totalNg: 1,
            totalRate: 1,
            isTotal
          };
          const a = { row, column: { property: prop } };
          eq(`cellStyle(${prop},isTotal=${isTotal})`, o(a), n(a));
          g.hit();
        }
        break;
      }
      case "isAlert": {
        for (const [r, q, ra, mq] of [
          [5, 100, 5, 30],
          [4.99, 100, 5, 30],
          [5, 29, 5, 30],
          [null, 100, 5, 30],
          [10, 30, 5, 30]
        ]) {
          eq(`isAlert(${r},${q},${ra},${mq})`, o(r, q, ra, mq), n(r, q, ra, mq));
          g.hit();
        }
        break;
      }
    }
  }
}

console.log("=== 2. 旧 cavity vs 旧 scan 互相验证（确认旧本身就一致） ===");
{
  const g = group("旧双实现自洽");
  for (const name of PURE) {
    if (typeof oldCav[name] !== "function") continue;
    const a = oldCav[name];
    const b = oldScan[name];
    for (const c of [null, undefined, "", 0, 5, 100, "1A", "H"]) {
      try {
        eq(`旧自洽 ${name}(${String(c)})`, a(c), b(c));
        g.hit();
      } catch {
        /* 签名不同则跳过 */
      }
    }
  }
}

console.log("=== 3. cellAlert 工厂差分（含规则状态敏感性） ===");
{
  const g = group("cellAlert");
  const RULES_A = {
    limCavityRateAbovePct: 5,
    limCavityMinQty: 30,
    limMachineRateAbovePct: 5,
    limMachineMinQty: 30,
    bodyCavityRateAbovePct: 5,
    bodyCavityMinQty: 30,
    bodyMachineRateAbovePct: 5,
    bodyMachineMinQty: 30,
    cavityRateAbovePct: 5,
    cavityMinQty: 30,
    machineRateAbovePct: 5,
    machineMinQty: 30
  };
  const RULES_B = {
    ...RULES_A,
    limCavityRateAbovePct: 50,
    limMachineRateAbovePct: 50,
    bodyCavityRateAbovePct: 50,
    bodyMachineRateAbovePct: 50
  };
  const rows = [
    {
      entity: "M1",
      metric: "rate",
      metricLabel: "不良率",
      cells: { A: 6 },
      qtys: { A: 100 },
      totalQty: 100,
      totalNg: 6,
      totalRate: 6
    },
    {
      entity: "M2",
      metric: "qty",
      metricLabel: "产量",
      cells: { A: 6 },
      qtys: { A: 100 },
      totalQty: 100,
      totalNg: 6,
      totalRate: 6
    },
    {
      entity: "M3",
      metric: "rate",
      metricLabel: "不良率",
      cells: { A: 6 },
      qtys: { A: 10 },
      totalQty: 10,
      totalNg: 6,
      totalRate: 60
    }
  ];
  const props = ["total", "c_A", "entity", "", "c_", "c_Z"];
  for (const [tag, rules] of [
    ["A", RULES_A],
    ["B", RULES_B]
  ]) {
    let cur = rules;
    const newCellAlert = newMod.createCellAlert(() => cur);
    // 旧实现：把 alertRules.value 注入闭包
    const oldSrc = scriptOf(cavitySnap);
    const fnStart = /(?:^|\n)function cellAlert\s*\(/.exec(oldSrc);
    if (!fnStart) throw new Error("快照中找不到 cellAlert");
    const fnBlock = sliceFunction(
      oldSrc,
      oldSrc.indexOf("function cellAlert", fnStart.index)
    );
    const wrapped = `${fnBlock}\nmodule.exports = { cellAlert };`;
    const js = transpile(wrapped);
    const alertRules = { value: rules };
    const mod = { exports: {} };
    new Function("module", "exports", "alertRules", "isAlert", js)(
      mod,
      mod.exports,
      alertRules,
      oldCav.isAlert
    );
    const oldCellAlert = mod.exports.cellAlert;

    for (const kind of ["lim", "body"]) {
      for (const r of rows) {
        for (const p of props) {
          const arg = { row: r, column: { property: p } };
          eq(
            `cellAlert[${tag}](${r.entity},${kind},${p})`,
            oldCellAlert(arg, kind),
            newCellAlert(arg, kind)
          );
          g.hit();
        }
      }
    }
    // 规则对象被换掉后，新工厂必须读到新值（验证闭包是活引用）
    cur = RULES_B;
    const arg = { row: rows[0], column: { property: "c_A" } };
    alertRules.value = RULES_B;
    eq(
      `cellAlert[${tag}] 规则热更新`,
      oldCellAlert(arg, "lim"),
      newCellAlert(arg, "lim")
    );
    g.hit();
    cur = rules;
    alertRules.value = rules;
  }
}

console.log("=== 5. 表格合并 / 告警文案工厂（第二轮收敛） ===");
{
  const g = group("工厂");
  // 旧实现直接来自快照 .vue，新实现来自 utils/pivotTable.ts。
  // 这两个都是「闭包捕获调用方状态」的工厂，所以两边都传同样的 getter 进去比。
  const oldCavSpan = extractOld(cavitySnap, ["makeSpanMethod"]).makeSpanMethod;
  const oldScanSpan = extractOld(scanSnap, ["makeSpanMethod"]).makeSpanMethod;

  // --- makeSpanMethod ---
  const mkRows = () => {
    const mk = (entity, metric = "qty") => ({
      entity,
      metric,
      metricLabel: entity,
      cells: {},
      qtys: {},
      totalQty: 0,
      totalNg: 0,
      totalRate: null
    });
    return [
      mk("M1"),
      mk("M1"),
      mk("M1"),
      mk("M2"),
      mk("M2"),
      mk("M3")
    ];
  };

  // 用例覆盖：首行 / 连续行中间 / 连续行末尾 / 实体切换处 / 非 0 列 / 越界行 / 空数组
  const spanCases = [
    { rowIndex: 0, columnIndex: 0 },
    { rowIndex: 1, columnIndex: 0 },
    { rowIndex: 2, columnIndex: 0 },
    { rowIndex: 3, columnIndex: 0 },
    { rowIndex: 4, columnIndex: 0 },
    { rowIndex: 5, columnIndex: 0 },
    { rowIndex: 0, columnIndex: 1 },
    { rowIndex: 3, columnIndex: 7 },
    { rowIndex: 99, columnIndex: 0 },
    { rowIndex: -1, columnIndex: 0 }
  ];
  for (const [tag, oldFn, newFn] of [
    ["cavity", oldCavSpan, newMod.makeSpanMethod],
    ["scan", oldScanSpan, newMod.makeSpanMethod]
  ]) {
    const rows = mkRows();
    const oldM = oldFn(() => rows);
    const newM = newFn(() => rows);
    for (const c of spanCases) {
      eq(`makeSpanMethod[${tag}] (${c.rowIndex},${c.columnIndex})`, oldM(c), newM(c));
      g.hit();
    }
    // 空数据
    eq(`makeSpanMethod[${tag}] 空数组`, oldFn(() => [])({ rowIndex: 0, columnIndex: 0 }),
       newFn(() => [])({ rowIndex: 0, columnIndex: 0 }));
    g.hit();
    // 闭包是活引用：换掉行数组后必须读到新值
    let cur = rows;
    const oldLive = oldFn(() => cur);
    const newLive = newFn(() => cur);
    const swapped = [mkRows()[0], mkRows()[0]];
    swapped[0].entity = "Z9";
    cur = swapped;
    eq(`makeSpanMethod[${tag}] 活引用刷新`, oldLive({ rowIndex: 0, columnIndex: 0 }),
       newLive({ rowIndex: 0, columnIndex: 0 }));
    g.hit();
  }

  // --- makeLimAlertHint ---
  // 旧实现是从 cavity 快照里抠出的 `const limAlertHint = computed(...)`，
  // 它闭包引用了页面里的 `alertRules`。所以必须连 alertRules 一起抽出来，
  // 才能给它喂受控的规则值 —— 这才是真正的差分（不是手抄一份当"旧实现"）。
  // extractOld 里 alertRules 是按 `ref({...})` 抽的，这里额外包一层 ref 让它可替换。
  const oldCavMod = extractOld(cavitySnap, ["limAlertHint", "alertRules"]);
  const oldCavHint = oldCavMod.limAlertHint;
  // 用可变 ref 驱动旧实现：每次改 .value 即模拟换了一份规则
  const driveOld = rules => {
    oldCavMod.alertRules.value = rules;
    return oldCavHint.value;
  };
  const ruleCases = [
    DEFAULT_RULES,
    { ...DEFAULT_RULES, cavityRateAbovePct: 0, machineRateAbovePct: 100 },
    { ...DEFAULT_RULES, cavityMinQty: 1, machineMinQty: 99999 }
  ];
  for (const [i, rules] of ruleCases.entries()) {
    eq(
      `limAlertHint[case${i}]`,
      driveOld(rules),
      newMod.makeLimAlertHint(() => rules).value
    );
    g.hit();
  }
}

console.log("=== 4. 常量一致性 ===");
{
  const g = group("常量");
  eq("CAVITY_LETTERS", [...oldCav.CAVITY_LETTERS], [
    ...newMod.CAVITY_LETTERS
  ]);
  eq("BODY_DIGIT_TO_LETTER", oldCav.BODY_DIGIT_TO_LETTER, {
    ...newMod.BODY_DIGIT_TO_LETTER
  });
  eq("BODY_CAVITY_LETTERS", [...oldCav.BODY_CAVITY_LETTERS], [
    ...newMod.BODY_CAVITY_LETTERS
  ]);
  g.hit();
  g.hit();
  g.hit();
}

// ---------- 5. 汇总 ----------
const out = {
  cases: pass + fails.length,
  pass,
  fails,
  groups,
  verdict: fails.length === 0 ? "PASS" : "FAIL"
};
console.log("\n" + JSON.stringify(out, null, 2));
process.exit(fails.length === 0 ? 0 : 1);
