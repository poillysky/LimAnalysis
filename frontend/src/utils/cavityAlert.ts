/** LIM 机台/模穴、本体模具/模穴标红规则；总不良与子不良各一套。 */
import { http } from "@/utils/http";
import { API_PREFIX } from "@/api/http";

export type AlertRules = {
  limCavityRateAbovePct: number;
  limCavityMinQty: number;
  limMachineRateAbovePct: number;
  limMachineMinQty: number;
  bodyCavityRateAbovePct: number;
  bodyCavityMinQty: number;
  bodyMachineRateAbovePct: number;
  bodyMachineMinQty: number;
  /** LIM 模穴/机台别名；系统通知用 machine*（机台线） */
  cavityRateAbovePct: number;
  cavityMinQty: number;
  machineRateAbovePct: number;
  machineMinQty: number;
};

/** total=总不良（外观/注塑）；item=筛选到的其他子不良 */
export type AlertRulesBundle = {
  total: AlertRules;
  item: AlertRules;
};

export type AlertRuleSetKind = keyof AlertRulesBundle;

export const CAVITY_ALERT_KEY = "limanalysis.cavity.alertRules";
export const DEFAULT_CAVITY_ALERT: AlertRules = {
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

export const DEFAULT_CAVITY_ALERT_BUNDLE: AlertRulesBundle = {
  total: { ...DEFAULT_CAVITY_ALERT },
  item: { ...DEFAULT_CAVITY_ALERT }
};

export function isTotalDefectMetric(metricKey: string) {
  const key = String(metricKey || "").trim();
  return key === "appearance" || key === "mold";
}

function clampPct(value: unknown, fallback: number) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(100, Math.max(0, n));
}

function clampQty(value: unknown, fallback: number) {
  const n = Math.floor(Number(value));
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, n);
}

function firstNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    if (value == null || value === "") continue;
    const n = Number(value);
    if (Number.isFinite(n)) return n;
  }
  return undefined;
}

type AlertRulesRaw = Partial<AlertRules> & {
  rateAbovePct?: number;
  minQty?: number;
  yieldBelowPct?: number;
  rate_above_pct?: number;
  min_qty?: number;
  cavity_rate_above_pct?: number;
  cavity_min_qty?: number;
  machine_rate_above_pct?: number;
  machine_min_qty?: number;
  lim_cavity_rate_above_pct?: number;
  lim_cavity_min_qty?: number;
  lim_machine_rate_above_pct?: number;
  lim_machine_min_qty?: number;
  body_cavity_rate_above_pct?: number;
  body_cavity_min_qty?: number;
  body_machine_rate_above_pct?: number;
  body_machine_min_qty?: number;
  item?: AlertRulesRaw | null;
  total?: AlertRulesRaw | null;
};

export function normalizeAlertRules(
  raw?: AlertRulesRaw | null,
  fallback: AlertRules = DEFAULT_CAVITY_ALERT
): AlertRules {
  const parsed = raw || {};
  let legacyRate = parsed.rateAbovePct ?? parsed.rate_above_pct;
  if (legacyRate == null && parsed.yieldBelowPct != null) {
    legacyRate = 100 - Number(parsed.yieldBelowPct);
  }
  const legacyQty = parsed.minQty ?? parsed.min_qty;

  const limCavityRateAbovePct = clampPct(
    firstNumber(
      parsed.limCavityRateAbovePct,
      parsed.lim_cavity_rate_above_pct,
      parsed.cavityRateAbovePct,
      parsed.cavity_rate_above_pct,
      legacyRate
    ),
    fallback.limCavityRateAbovePct
  );
  const limCavityMinQty = clampQty(
    firstNumber(
      parsed.limCavityMinQty,
      parsed.lim_cavity_min_qty,
      parsed.cavityMinQty,
      parsed.cavity_min_qty,
      legacyQty
    ),
    fallback.limCavityMinQty
  );
  const limMachineRateAbovePct = clampPct(
    firstNumber(
      parsed.limMachineRateAbovePct,
      parsed.lim_machine_rate_above_pct,
      parsed.machineRateAbovePct,
      parsed.machine_rate_above_pct,
      legacyRate
    ),
    fallback.limMachineRateAbovePct
  );
  const limMachineMinQty = clampQty(
    firstNumber(
      parsed.limMachineMinQty,
      parsed.lim_machine_min_qty,
      parsed.machineMinQty,
      parsed.machine_min_qty,
      legacyQty
    ),
    fallback.limMachineMinQty
  );
  const bodyCavityRateAbovePct = clampPct(
    firstNumber(
      parsed.bodyCavityRateAbovePct,
      parsed.body_cavity_rate_above_pct,
      limCavityRateAbovePct
    ),
    fallback.bodyCavityRateAbovePct
  );
  const bodyCavityMinQty = clampQty(
    firstNumber(
      parsed.bodyCavityMinQty,
      parsed.body_cavity_min_qty,
      limCavityMinQty
    ),
    fallback.bodyCavityMinQty
  );
  const bodyMachineRateAbovePct = clampPct(
    firstNumber(
      parsed.bodyMachineRateAbovePct,
      parsed.body_machine_rate_above_pct,
      limMachineRateAbovePct
    ),
    fallback.bodyMachineRateAbovePct
  );
  const bodyMachineMinQty = clampQty(
    firstNumber(
      parsed.bodyMachineMinQty,
      parsed.body_machine_min_qty,
      limMachineMinQty
    ),
    fallback.bodyMachineMinQty
  );

  return {
    limCavityRateAbovePct,
    limCavityMinQty,
    limMachineRateAbovePct,
    limMachineMinQty,
    bodyCavityRateAbovePct,
    bodyCavityMinQty,
    bodyMachineRateAbovePct,
    bodyMachineMinQty,
    cavityRateAbovePct: limCavityRateAbovePct,
    cavityMinQty: limCavityMinQty,
    machineRateAbovePct: limMachineRateAbovePct,
    machineMinQty: limMachineMinQty
  };
}

export function normalizeAlertBundle(
  raw?: AlertRulesRaw | AlertRulesBundle | null
): AlertRulesBundle {
  const parsed = (raw || {}) as AlertRulesRaw;
  // 旧版扁平：整包当总不良；有 total/item 时分别读
  const flatSrc = {
    ...parsed,
    item: undefined,
    total: undefined
  } as AlertRulesRaw;
  const total = normalizeAlertRules(
    parsed.total != null ? parsed.total : flatSrc
  );
  const item = normalizeAlertRules(
    parsed.item != null ? parsed.item : undefined,
    total
  );
  return { total, item };
}

export function pickAlertRules(
  bundle: AlertRulesBundle,
  metricKey: string
): AlertRules {
  return isTotalDefectMetric(metricKey) ? bundle.total : bundle.item;
}

export function loadCavityAlertBundle(): AlertRulesBundle {
  try {
    const raw = localStorage.getItem(CAVITY_ALERT_KEY);
    if (!raw) return structuredClone(DEFAULT_CAVITY_ALERT_BUNDLE);
    return normalizeAlertBundle(JSON.parse(raw));
  } catch {
    return structuredClone(DEFAULT_CAVITY_ALERT_BUNDLE);
  }
}

/** @deprecated 仅扫码页等仍读单套时用；模穴页请用 loadCavityAlertBundle */
export function loadCavityAlertRules(): AlertRules {
  return loadCavityAlertBundle().total;
}

export function saveCavityAlertBundle(bundle: AlertRulesBundle) {
  const next = normalizeAlertBundle(bundle);
  localStorage.setItem(CAVITY_ALERT_KEY, JSON.stringify(next));
}

/** @deprecated */
export function saveCavityAlertRules(rules: AlertRules) {
  const prev = loadCavityAlertBundle();
  saveCavityAlertBundle({ ...prev, total: normalizeAlertRules(rules) });
}

export function isDefaultAlertRules(rules: AlertRules) {
  const next = normalizeAlertRules(rules);
  return (
    next.limCavityRateAbovePct === DEFAULT_CAVITY_ALERT.limCavityRateAbovePct &&
    next.limCavityMinQty === DEFAULT_CAVITY_ALERT.limCavityMinQty &&
    next.limMachineRateAbovePct ===
      DEFAULT_CAVITY_ALERT.limMachineRateAbovePct &&
    next.limMachineMinQty === DEFAULT_CAVITY_ALERT.limMachineMinQty &&
    next.bodyCavityRateAbovePct ===
      DEFAULT_CAVITY_ALERT.bodyCavityRateAbovePct &&
    next.bodyCavityMinQty === DEFAULT_CAVITY_ALERT.bodyCavityMinQty &&
    next.bodyMachineRateAbovePct ===
      DEFAULT_CAVITY_ALERT.bodyMachineRateAbovePct &&
    next.bodyMachineMinQty === DEFAULT_CAVITY_ALERT.bodyMachineMinQty
  );
}

export function isDefaultAlertBundle(bundle: AlertRulesBundle) {
  const next = normalizeAlertBundle(bundle);
  return (
    isDefaultAlertRules(next.total) && isDefaultAlertRules(next.item)
  );
}

export function toRemoteAlertRules(rules: AlertRules) {
  const next = normalizeAlertRules(rules);
  return {
    lim_cavity_rate_above_pct: next.limCavityRateAbovePct,
    lim_cavity_min_qty: next.limCavityMinQty,
    lim_machine_rate_above_pct: next.limMachineRateAbovePct,
    lim_machine_min_qty: next.limMachineMinQty,
    body_cavity_rate_above_pct: next.bodyCavityRateAbovePct,
    body_cavity_min_qty: next.bodyCavityMinQty,
    body_machine_rate_above_pct: next.bodyMachineRateAbovePct,
    body_machine_min_qty: next.bodyMachineMinQty,
    cavity_rate_above_pct: next.limCavityRateAbovePct,
    cavity_min_qty: next.limCavityMinQty,
    machine_rate_above_pct: next.limMachineRateAbovePct,
    machine_min_qty: next.limMachineMinQty
  };
}

export function toRemoteAlertBundle(bundle: AlertRulesBundle) {
  const next = normalizeAlertBundle(bundle);
  return {
    ...toRemoteAlertRules(next.total),
    item: toRemoteAlertRules(next.item)
  };
}

export const saveCavityAlertRulesRemote = (bundle: AlertRulesBundle) => {
  return http.request<{
    success: boolean;
    data: Record<string, unknown>;
  }>("put", `${API_PREFIX}/system/alert-rules`, {
    data: toRemoteAlertBundle(bundle)
  });
};

export const getCavityAlertRulesRemote = () => {
  return http.request<{
    success: boolean;
    data: Record<string, unknown>;
  }>("get", `${API_PREFIX}/system/alert-rules`);
};

export function rulesFromRemote(data?: Record<string, unknown>): AlertRules {
  return normalizeAlertBundle(data as AlertRulesRaw).total;
}

export function bundleFromRemote(
  data?: Record<string, unknown>
): AlertRulesBundle {
  return normalizeAlertBundle(data as AlertRulesRaw);
}
