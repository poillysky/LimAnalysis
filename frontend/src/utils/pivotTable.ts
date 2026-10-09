/**
 * 模穴透视表共享逻辑 —— 由 `views/exception/cavity/index.vue` 与 `views/scan/analysis.vue`
 * 逐字相同的实现收敛而来（2026-10-06 去重）。
 *
 * ⚠️ 刻意保留的「同名不同义」函数，**不要**合并：
 * - `buildPivot`：两处仅格式化不同但属各自模块演进节奏，差异风险高于收益，保持各一份。
 * - `cellClassName`：本目录版会拼 `is-series` 双类名；scan 版只返回 `is-alert`。
 *   两者渲染契约不同（是否给整列加边框底色），合并会改变 scan 页面视觉。
 * - etl/agg 的 `startRunBar` / `applyJobToBar` / `finishRunBar`：名字相同但语义不同
 *   （etl 为 8/22/68/100 + 1s 轮询 + 「分秒」，agg 为 12/20/55 + 500ms + 「m s」），
 *   且 agg 的 applyJobToBar 不处理终态。属于两套不同 UI 契约，**不是**复制粘贴。
 */

import { computed } from "vue";
import type { AlertRules } from "@/utils/cavityAlert";

export type MetricKind = "qty" | "rate";

export type PivotRow = {
  /** 行维：机台号或本体模具号 */
  entity: string;
  metric: MetricKind;
  metricLabel: string;
  cells: Record<string, number | null>;
  /** 各模穴产量，供不良率行做投入数门槛判断 */
  qtys: Record<string, number>;
  totalQty: number;
  totalNg: number;
  totalRate: number | null;
  isTotal?: boolean;
};

export type PivotSource = {
  entity: string;
  cavity: string;
  qty: number;
  ng: number;
};

/** 模穴字母横轴（跳过 I / O，与现场穴位命名一致） */
export const CAVITY_LETTERS = [
  "A",
  "B",
  "C",
  "D",
  "E",
  "F",
  "G",
  "H",
  "J",
  "K",
  "L",
  "M",
  "N",
  "P",
  "Q",
  "R"
] as const;

/** 本体码第 2 位 1–8 映射为表头 A–H */
export const BODY_CAVITY_LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H"] as const;

export const BODY_DIGIT_TO_LETTER: Record<
  string,
  (typeof BODY_CAVITY_LETTERS)[number]
> = {
  "1": "A",
  "2": "B",
  "3": "C",
  "4": "D",
  "5": "E",
  "6": "F",
  "7": "G",
  "8": "H"
};

export const PIVOT_HEADER_CELL_STYLE = {
  background: "#1e4e79",
  color: "#fff",
  fontWeight: 600,
  fontSize: "12px",
  borderColor: "#163c5c",
  textAlign: "center" as const,
  padding: "0"
};

/** axios 取消错误识别：三种来源（axios / element / 原生）都要认。 */
export function isAbortError(error: unknown) {
  return (
    (error as { code?: string; name?: string })?.code === "ERR_CANCELED" ||
    (error as { name?: string })?.name === "CanceledError" ||
    (error as { name?: string })?.name === "AbortError"
  );
}

/** 全角字母/数字 → 半角，再 trim，避免 NAS 脏数据进不了格子。 */
export function normalizeCavityText(cavity: string) {
  return String(cavity || "")
    .normalize("NFKC")
    .trim()
    .toUpperCase();
}

/**
 * 从模穴字段取横轴字母。兼容：`A`、`A1`、`模穴A`、全角 `Ａ`。
 * 取最后一个拉丁字母；I/O 由调用方用 CAVITY_LETTERS 过滤（现场穴位命名跳过）。
 */
export function cavityLetter(cavity: string) {
  const letters = normalizeCavityText(cavity).match(/[A-Z]/g);
  return letters?.[letters.length - 1] || "";
}

/**
 * 本体穴位 → A–H。兼容：`1`–`8`、已是 `A`–`H`、全角数字、夹杂字符取末位。
 */
export function bodyCavityLetter(cavity: string) {
  const s = normalizeCavityText(cavity);
  if (!s) return "";
  if (BODY_DIGIT_TO_LETTER[s]) return BODY_DIGIT_TO_LETTER[s];
  if ((BODY_CAVITY_LETTERS as readonly string[]).includes(s)) return s;
  const digit = s.match(/[1-8]/g)?.at(-1);
  if (digit) return BODY_DIGIT_TO_LETTER[digit] || "";
  const letter = s.match(/[A-H]/g)?.at(-1) || "";
  return (BODY_CAVITY_LETTERS as readonly string[]).includes(letter) ? letter : "";
}

/** 不良率 %：ng/qty，保留两位；产量为 0 时返回 null（格子显示空，不是 0%）。 */
export function rateOf(qty: number, ng: number) {
  return qty > 0 ? Math.round((ng / qty) * 10000) / 100 : null;
}

/** 原始行里能落入交叉表横轴的产量合计（与透视表汇总同口径）。 */
export function pivotKeptTotals(
  source: PivotSource[],
  axes: readonly string[],
  axisOf: (cavity: string) => string
) {
  let qty = 0;
  let ng = 0;
  const entities = new Set<string>();
  let droppedQty = 0;
  for (const row of source) {
    const q = Number(row.qty || 0);
    const n = Number(row.ng || 0);
    const axis = axisOf(row.cavity);
    const entity = String(row.entity || "").trim();
    if (!entity || !axis || !axes.includes(axis)) {
      droppedQty += q;
      continue;
    }
    qty += q;
    ng += n;
    entities.add(entity);
  }
  return {
    qty,
    ng,
    machines: entities.size,
    ratePct: rateOf(qty, ng),
    droppedQty
  };
}

export function formatQty(value: number | null | undefined) {
  if (value == null) return "";
  return Number(value).toLocaleString();
}

export function formatRate(value: number | null | undefined) {
  if (value == null) return "";
  return `${Number(value).toFixed(2)}%`;
}

/** 无产量格子用 —，避免看起来像渲染漏了 */
export function cellText(row: PivotRow, letter: string) {
  const value = row.cells[letter];
  if (value == null) return "—";
  return row.metric === "qty" ? formatQty(value) : formatRate(value);
}

export function totalText(row: PivotRow) {
  if (row.metric === "qty") {
    return row.totalQty > 0 ? formatQty(row.totalQty) : "—";
  }
  return row.totalRate == null ? "—" : formatRate(row.totalRate);
}

export function cellEmpty(row: PivotRow, letter: string) {
  return row.cells[letter] == null;
}

export function cellStyle({
  row,
  column
}: {
  row: PivotRow;
  column: { property?: string };
}) {
  const prop = column.property || "";
  return {
    borderColor: "#c6c6c6",
    padding: "0 4px",
    textAlign: "center" as const,
    background: "#fff",
    color: "inherit",
    fontWeight: prop === "entity" || prop === "total" || row.isTotal ? 600 : 400
  };
}

/** 投入数达标且不良率 ≥ 阈值 → 预警红 */
export function isAlert(
  ratePct: number | null,
  qty: number,
  rateAbovePct: number,
  minQty: number
) {
  if (ratePct == null) return false;
  if (qty < minQty) return false;
  return ratePct >= rateAbovePct;
}

type CellAlertArgs = {
  row: PivotRow;
  column: { property?: string };
};

/**
 * 单元格是否标红。依赖调用方的 `alertRules` ref —— 用工厂返回闭包，
 * 这样两个页面各自的规则状态互不干扰。
 */
export function createCellAlert(getRules: () => AlertRules) {
  return function cellAlert(
    { row, column }: CellAlertArgs,
    kind: "lim" | "body"
  ) {
    if (row.metric !== "rate") return false;
    const prop = column.property || "";
    const r = getRules();
    const machineRate =
      kind === "body" ? r.bodyMachineRateAbovePct : r.limMachineRateAbovePct;
    const machineQty = kind === "body" ? r.bodyMachineMinQty : r.limMachineMinQty;
    const cavityRate =
      kind === "body" ? r.bodyCavityRateAbovePct : r.limCavityRateAbovePct;
    const cavityQty = kind === "body" ? r.bodyCavityMinQty : r.limCavityMinQty;
    if (prop === "total") {
      return isAlert(row.totalRate, row.totalQty, machineRate, machineQty);
    }
    if (prop.startsWith("c_")) {
      const letter = prop.slice(2);
      return isAlert(
        row.cells[letter] ?? null,
        Number(row.qtys[letter] || 0),
        cavityRate,
        cavityQty
      );
    }
    return false;
  };
}

/**
 * Element Plus `<el-table>` 的 `span-method` 工厂：把同一 entity 的连续行合并。
 *
 * 形态说明 —— 收进来而不是直接导出 `spanMethod`，是因为它必须闭包捕获调用方的
 * 行数据源。两处调用点拿到的行数组不同（cavity 用 `pivotRows`、scan 也有自己的
 * `pivotRows`），所以对外只暴露工厂，由调用方传 `() => rows.value`。
 */
export function makeSpanMethod(list: () => PivotRow[]) {
  return ({
    rowIndex,
    columnIndex
  }: {
    rowIndex: number;
    columnIndex: number;
  }) => {
    if (columnIndex !== 0) return { rowspan: 1, colspan: 1 };
    const rowsList = list();
    const cur = rowsList[rowIndex]?.entity;
    if (!cur) return { rowspan: 1, colspan: 1 };
    if (rowIndex > 0 && rowsList[rowIndex - 1]?.entity === cur) {
      return { rowspan: 0, colspan: 0 };
    }
    let span = 1;
    for (let i = rowIndex + 1; i < rowsList.length; i++) {
      if (rowsList[i]?.entity !== cur) break;
      span += 1;
    }
    return { rowspan: span, colspan: 1 };
  };
}

/**
 * 「模穴 / 机台 显红规则」的提示文案。
 *
 * 同样只暴露工厂：文案里的数字全部来自 `alertRules`，而两个页面各自持有自己的
 * rules ref（cavity 走本地 storage，scan 走后端接口），不能共用同一个实例。
 */
export function makeLimAlertHint(rules: () => AlertRules) {
  return computed(() => {
    const r = rules();
    return `模穴 ≥ ${r.limCavityRateAbovePct}%（产量不低于 ${r.limCavityMinQty} 才标）；机台 ≥ ${r.limMachineRateAbovePct}%（产量不低于 ${r.limMachineMinQty} 才标）`;
  });
}
