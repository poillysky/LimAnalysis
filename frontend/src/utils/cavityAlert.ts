/** LIM 机台/模穴、本体模具/模穴：两套标红规则。 */
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
  /** LIM 模穴别名，系统通知按 LIM 红线穴位用这对 */
  cavityRateAbovePct: number;
  cavityMinQty: number;
  machineRateAbovePct: number;
  machineMinQty: number;
};

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

function firstNumber(
  ...values: unknown[]
): number | undefined {
  for (const value of values) {
    if (value == null || value === "") continue;
    const n = Number(value);
    if (Number.isFinite(n)) return n;
  }
  return undefined;
}

export function normalizeAlertRules(
  raw?: Partial<AlertRules> & {
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
  } | null
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
    DEFAULT_CAVITY_ALERT.limCavityRateAbovePct
  );
  const limCavityMinQty = clampQty(
    firstNumber(
      parsed.limCavityMinQty,
      parsed.lim_cavity_min_qty,
      parsed.cavityMinQty,
      parsed.cavity_min_qty,
      legacyQty
    ),
    DEFAULT_CAVITY_ALERT.limCavityMinQty
  );
  const limMachineRateAbovePct = clampPct(
    firstNumber(
      parsed.limMachineRateAbovePct,
      parsed.lim_machine_rate_above_pct,
      parsed.machineRateAbovePct,
      parsed.machine_rate_above_pct,
      legacyRate
    ),
    DEFAULT_CAVITY_ALERT.limMachineRateAbovePct
  );
  const limMachineMinQty = clampQty(
    firstNumber(
      parsed.limMachineMinQty,
      parsed.lim_machine_min_qty,
      parsed.machineMinQty,
      parsed.machine_min_qty,
      legacyQty
    ),
    DEFAULT_CAVITY_ALERT.limMachineMinQty
  );
  const bodyCavityRateAbovePct = clampPct(
    firstNumber(
      parsed.bodyCavityRateAbovePct,
      parsed.body_cavity_rate_above_pct,
      limCavityRateAbovePct
    ),
    DEFAULT_CAVITY_ALERT.bodyCavityRateAbovePct
  );
  const bodyCavityMinQty = clampQty(
    firstNumber(
      parsed.bodyCavityMinQty,
      parsed.body_cavity_min_qty,
      limCavityMinQty
    ),
    DEFAULT_CAVITY_ALERT.bodyCavityMinQty
  );
  const bodyMachineRateAbovePct = clampPct(
    firstNumber(
      parsed.bodyMachineRateAbovePct,
      parsed.body_machine_rate_above_pct,
      limMachineRateAbovePct
    ),
    DEFAULT_CAVITY_ALERT.bodyMachineRateAbovePct
  );
  const bodyMachineMinQty = clampQty(
    firstNumber(
      parsed.bodyMachineMinQty,
      parsed.body_machine_min_qty,
      limMachineMinQty
    ),
    DEFAULT_CAVITY_ALERT.bodyMachineMinQty
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

export function loadCavityAlertRules(): AlertRules {
  try {
    const raw = localStorage.getItem(CAVITY_ALERT_KEY);
    if (!raw) return { ...DEFAULT_CAVITY_ALERT };
    return normalizeAlertRules(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_CAVITY_ALERT };
  }
}

export function saveCavityAlertRules(rules: AlertRules) {
  localStorage.setItem(CAVITY_ALERT_KEY, JSON.stringify(normalizeAlertRules(rules)));
}

export function isDefaultAlertRules(rules: AlertRules) {
  const next = normalizeAlertRules(rules);
  return (
    next.limCavityRateAbovePct === DEFAULT_CAVITY_ALERT.limCavityRateAbovePct &&
    next.limCavityMinQty === DEFAULT_CAVITY_ALERT.limCavityMinQty &&
    next.limMachineRateAbovePct === DEFAULT_CAVITY_ALERT.limMachineRateAbovePct &&
    next.limMachineMinQty === DEFAULT_CAVITY_ALERT.limMachineMinQty &&
    next.bodyCavityRateAbovePct === DEFAULT_CAVITY_ALERT.bodyCavityRateAbovePct &&
    next.bodyCavityMinQty === DEFAULT_CAVITY_ALERT.bodyCavityMinQty &&
    next.bodyMachineRateAbovePct === DEFAULT_CAVITY_ALERT.bodyMachineRateAbovePct &&
    next.bodyMachineMinQty === DEFAULT_CAVITY_ALERT.bodyMachineMinQty
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

export const saveCavityAlertRulesRemote = (rules: AlertRules) => {
  return http.request<{
    success: boolean;
    data: Record<string, number>;
  }>("put", `${API_PREFIX}/system/alert-rules`, {
    data: toRemoteAlertRules(rules)
  });
};

export const getCavityAlertRulesRemote = () => {
  return http.request<{
    success: boolean;
    data: Record<string, number>;
  }>("get", `${API_PREFIX}/system/alert-rules`);
};

export function rulesFromRemote(data?: Record<string, number>): AlertRules {
  return normalizeAlertRules(data);
}
