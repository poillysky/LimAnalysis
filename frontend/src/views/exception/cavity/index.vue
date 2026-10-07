<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  getBodyCavityRates,
  getMachineCavityRates,
  getQueryCatalog,
  type BodyCavityRow,
  type MachineCavityRow,
  type QueryFilters,
  type QueryMetric,
  type QueryProject
} from "@/api/modules/exception";
import { backendErrorHint } from "@/api/http";
import {
  loadCavityAlertRules,
  saveCavityAlertRules,
  saveCavityAlertRulesRemote,
  getCavityAlertRulesRemote,
  rulesFromRemote,
  normalizeAlertRules,
  isDefaultAlertRules,
  type AlertRules
} from "@/utils/cavityAlert";
import PageTabs from "@/components/PageTabs/index.vue";
import PageMetricBar from "@/components/PageMetricBar/index.vue";
import SeriesPanel from "./SeriesPanel.vue";
import {
  BODY_CAVITY_LETTERS,
  BODY_DIGIT_TO_LETTER,
  CAVITY_LETTERS,
  PIVOT_HEADER_CELL_STYLE as headerCellStyle,
  bodyCavityLetter,
  cavityLetter,
  cellStyle,
  cellText,
  createCellAlert,
  formatQty,
  formatRate,
  isAbortError,
  rateOf,
  totalText,
  makeSpanMethod,
  makeLimAlertHint,
  type PivotRow,
  type PivotSource
} from "@/utils/pivotTable";

defineOptions({
  name: "ExceptionCavity"
});

const BODY_LETTER_TO_DIGIT: Record<string, string> = {
  A: "1",
  B: "2",
  C: "3",
  D: "4",
  E: "5",
  F: "6",
  G: "7",
  H: "8"
};

const loading = ref(false);
const hint = ref("");
const projects = ref<QueryProject[]>([]);
const projectId = ref("");
const projectTabs = computed(() =>
  projects.value.map(item => ({
    value: item.project_id,
    label: item.display_name
  }))
);
const ready = ref(false);
const hours = ref(3);
const metric = ref("appearance");
const metrics = ref<QueryMetric[]>([]);
const WINDOW_OPTIONS = [
  { value: 1, label: "近 1 小时" },
  { value: 3, label: "近 3 小时" },
  { value: 24, label: "近 1 天" },
  { value: 72, label: "近 3 天" }
];
const windowName = computed(
  () =>
    WINDOW_OPTIONS.find(item => item.value === hours.value)?.label || "近 3 小时"
);
const metricName = computed(() => {
  const item = metrics.value.find(row => row.key === metric.value);
  if (!item) return "总不良（外观）";
  return cavityMetricLabel(item);
});

function cavityMetricLabel(item: QueryMetric) {
  if (item.key === "appearance") return "总不良（外观）";
  if (item.key === "mold") return "总不良（注塑）";
  if (item.key.startsWith("defect:")) return item.key.slice("defect:".length);
  return item.label.replace(/不良率$/, "");
}
const rows = ref<MachineCavityRow[]>([]);
const bodyRows = ref<BodyCavityRow[]>([]);
const bodyHint = ref("");
const fromHour = ref("");
const toHour = ref("");
const excludeAlertMachines = ref(false);
const excludeAlertBodies = ref(false);
const seriesOpen = ref(false);
const seriesMounted = ref(false);
const seriesTitle = ref("");
const seriesFilters = ref<QueryFilters>({});
const alertMachineCavities = ref<string[]>([]);
const alertBodyCavities = ref<string[]>([]);
const alertRules = ref<AlertRules>(loadCavityAlertRules());
const alertOpen = ref(false);
const alertDraft = ref<AlertRules>({ ...alertRules.value });
let catalogAbort: AbortController | null = null;
let tableAbort: AbortController | null = null;

/** 标红判定读当前规则（活引用，规则改动即时生效） */
const cellAlert = createCellAlert(() => alertRules.value);

const summary = computed(() => {
  const qty = rows.value.reduce((sum, row) => sum + Number(row.qty || 0), 0);
  const ng = rows.value.reduce((sum, row) => sum + Number(row.ng || 0), 0);
  const machines = new Set(rows.value.map(r => r.machine)).size;
  return {
    qty,
    ng,
    machines,
    ratePct: rateOf(qty, ng)
  };
});

const windowLabel = computed(() => {
  if (fromHour.value && toHour.value && fromHour.value !== toHour.value) {
    return `${fromHour.value} ~ ${toHour.value}`;
  }
  return fromHour.value || toHour.value || windowName.value;
});

const summaryMetrics = computed(() => [
  {
    value: formatRate(summary.value.ratePct) || "—",
    label: `${metricName.value}合计`,
    accent: true
  },
  { value: formatQty(summary.value.qty) || "0", label: "产量" },
  { value: formatQty(summary.value.ng) || "0", label: "不良" },
  { value: summary.value.machines, label: "机台" }
]);

function buildPivot(
  source: PivotSource[],
  axes: readonly string[],
  axisOf: (cavity: string) => string
): PivotRow[] {
  const byEntity = new Map<string, Map<string, { qty: number; ng: number }>>();
  for (const row of source) {
    const axis = axisOf(row.cavity);
    if (!axis || !axes.includes(axis)) {
      continue;
    }
    if (!byEntity.has(row.entity)) byEntity.set(row.entity, new Map());
    const cells = byEntity.get(row.entity)!;
    const prev = cells.get(axis) || { qty: 0, ng: 0 };
    cells.set(axis, {
      qty: prev.qty + Number(row.qty || 0),
      ng: prev.ng + Number(row.ng || 0)
    });
  }

  const entities = [...byEntity.keys()].sort((a, b) =>
    a.localeCompare(b, "zh-CN", { numeric: true })
  );
  const out: PivotRow[] = [];
  const grandAxis = new Map<string, { qty: number; ng: number }>();
  let grandQty = 0;
  let grandNg = 0;

  for (const entity of entities) {
    const cells = byEntity.get(entity)!;
    let totalQty = 0;
    let totalNg = 0;
    const qtyCells: Record<string, number | null> = {};
    const rateCells: Record<string, number | null> = {};
    for (const axis of axes) {
      const cell = cells.get(axis);
      const qty = cell?.qty ?? 0;
      const ng = cell?.ng ?? 0;
      qtyCells[axis] = cell ? qty : null;
      rateCells[axis] = cell ? rateOf(qty, ng) : null;
      totalQty += qty;
      totalNg += ng;
      const g = grandAxis.get(axis) || { qty: 0, ng: 0 };
      g.qty += qty;
      g.ng += ng;
      grandAxis.set(axis, g);
    }
    grandQty += totalQty;
    grandNg += totalNg;
    const qtyMap: Record<string, number> = {};
    for (const axis of axes) {
      qtyMap[axis] = Number(qtyCells[axis] || 0);
    }
    out.push({
      entity,
      metric: "qty",
      metricLabel: "产量",
      cells: qtyCells,
      qtys: qtyMap,
      totalQty,
      totalNg,
      totalRate: rateOf(totalQty, totalNg)
    });
    out.push({
      entity,
      metric: "rate",
      metricLabel: "不良率",
      cells: rateCells,
      qtys: qtyMap,
      totalQty,
      totalNg,
      totalRate: rateOf(totalQty, totalNg)
    });
  }

  if (out.length) {
    const qtyCells: Record<string, number | null> = {};
    const rateCells: Record<string, number | null> = {};
    const qtyMap: Record<string, number> = {};
    for (const axis of axes) {
      const cell = grandAxis.get(axis);
      const qty = cell?.qty ?? 0;
      const ng = cell?.ng ?? 0;
      qtyCells[axis] = cell ? qty : null;
      rateCells[axis] = cell ? rateOf(qty, ng) : null;
      qtyMap[axis] = qty;
    }
    out.push({
      entity: "汇总",
      metric: "qty",
      metricLabel: "产量",
      cells: qtyCells,
      qtys: qtyMap,
      totalQty: grandQty,
      totalNg: grandNg,
      totalRate: rateOf(grandQty, grandNg),
      isTotal: true
    });
    out.push({
      entity: "汇总",
      metric: "rate",
      metricLabel: "不良率",
      cells: rateCells,
      qtys: qtyMap,
      totalQty: grandQty,
      totalNg: grandNg,
      totalRate: rateOf(grandQty, grandNg),
      isTotal: true
    });
  }
  return out;
}

const pivotRows = computed(() =>
  buildPivot(
    rows.value.map(row => ({
      entity: row.machine,
      cavity: row.cavity,
      qty: row.qty,
      ng: row.ng
    })),
    CAVITY_LETTERS,
    cavityLetter
  )
);

const bodyPivotRows = computed(() =>
  buildPivot(
    bodyRows.value.map(row => ({
      entity: row.body,
      cavity: row.cavity,
      qty: row.qty,
      ng: row.ng
    })),
    BODY_CAVITY_LETTERS,
    bodyCavityLetter
  )
);

function isSeriesProp(prop: string) {
  return prop === "total" || prop.startsWith("c_");
}

function seriesCellClass(prop: string, alert: boolean) {
  return [alert ? "is-alert" : "", isSeriesProp(prop) ? "is-series" : ""]
    .filter(Boolean)
    .join(" ");
}

function cellClassName({
  row,
  column
}: {
  row: PivotRow;
  column: { property?: string };
}) {
  const prop = column.property || "";
  return seriesCellClass(prop, cellAlert({ row, column }, "lim"));
}

function bodyCellClassName({
  row,
  column
}: {
  row: PivotRow;
  column: { property?: string };
}) {
  const prop = column.property || "";
  return seriesCellClass(prop, cellAlert({ row, column }, "body"));
}

function openSeries(title: string, filters: QueryFilters) {
  seriesTitle.value = title;
  seriesFilters.value = filters;
  seriesOpen.value = true;
}

function onLimCellClick(row: PivotRow, column: { property?: string }) {
  const prop = column.property || "";
  if (!isSeriesProp(prop)) return;
  const machine = row.isTotal ? undefined : row.entity;
  if (prop === "total") {
    if (!row.totalQty) return;
    openSeries(machine ? `机台 ${machine}` : "全部机台", {
      ...(machine ? { machine } : {})
    });
    return;
  }
  const letter = prop.slice(2);
  if (row.cells[letter] == null) return;
  openSeries(machine ? `${machine} · 模穴 ${letter}` : `模穴 ${letter}`, {
    ...(machine ? { machine } : {}),
    cavity_letter: letter
  });
}

function onBodyCellClick(row: PivotRow, column: { property?: string }) {
  const prop = column.property || "";
  if (!isSeriesProp(prop)) return;
  const mold = row.isTotal ? undefined : row.entity;
  if (prop === "total") {
    if (!row.totalQty) return;
    openSeries(mold ? `模具 ${mold}` : "全部本体", {
      ...(mold ? { body_mold: mold } : {})
    });
    return;
  }
  const letter = prop.slice(2);
  if (row.cells[letter] == null) return;
  const digit = BODY_LETTER_TO_DIGIT[letter];
  if (!digit) return;
  openSeries(mold ? `${mold} · ${letter}（${digit}）` : `本体穴位 ${letter}`, {
    ...(mold ? { body_mold: mold } : {}),
    body_cavity: digit
  });
}

function asPivotSource(
  list: Array<{ cavity: string; qty: number; ng: number }>,
  entityKey: "machine" | "body"
): PivotSource[] {
  return list.map(row => ({
    entity: String((row as Record<string, unknown>)[entityKey] ?? ""),
    cavity: row.cavity,
    qty: row.qty,
    ng: row.ng
  }));
}

function alertCavityPairs(
  source: PivotSource[],
  axes: readonly string[],
  axisOf: (cavity: string) => string,
  kind: "lim" | "body"
) {
  const pairs: string[] = [];
  for (const row of buildPivot(source, axes, axisOf)) {
    if (row.isTotal || row.metric !== "rate") continue;
    for (const axis of axes) {
      if (
        cellAlert({ row, column: { property: `c_${axis}` } }, kind)
      ) {
        pairs.push(`${row.entity}:${axis}`);
      }
    }
  }
  return pairs;
}

function openAlertConfig() {
  alertDraft.value = { ...alertRules.value };
  alertOpen.value = true;
}

function saveAlertConfig() {
  const next = normalizeAlertRules(alertDraft.value);
  alertRules.value = next;
  saveCavityAlertRules(next);
  void saveCavityAlertRulesRemote(next);
  alertOpen.value = false;
  loadTable();
}

const limAlertHint = makeLimAlertHint(() => alertRules.value);

const bodyAlertHint = computed(() => {
  const r = alertRules.value;
  return `模穴 ≥ ${r.bodyCavityRateAbovePct}%（产量不低于 ${r.bodyCavityMinQty} 才标）；模具 ≥ ${r.bodyMachineRateAbovePct}%（产量不低于 ${r.bodyMachineMinQty} 才标）`;
});

const excludeHint = computed(() => {
  const parts: string[] = [];
  if (excludeAlertMachines.value && alertMachineCavities.value.length) {
    parts.push(
      `已从本体表去掉 LIM 异常模穴 ${alertMachineCavities.value
        .map(item => item.replace(":", "-"))
        .join("、")}`
    );
  }
  if (excludeAlertBodies.value && alertBodyCavities.value.length) {
    parts.push(
      `已从机台表去掉本体异常模穴 ${alertBodyCavities.value
        .map(item => item.replace(":", "-"))
        .join("、")}`
    );
  }
  return parts.join("；");
});

const spanMethod = makeSpanMethod(() => pivotRows.value);
const bodySpanMethod = makeSpanMethod(() => bodyPivotRows.value);

async function loadTable() {
  if (!projectId.value || !ready.value) {
    rows.value = [];
    bodyRows.value = [];
    return;
  }
  tableAbort?.abort();
  tableAbort = new AbortController();
  const signal = tableAbort.signal;
  loading.value = true;
  hint.value = "";
  bodyHint.value = "";
  try {
    const [machineRes, bodyRes] = await Promise.allSettled([
      getMachineCavityRates(projectId.value, hours.value, metric.value, signal),
      getBodyCavityRates(projectId.value, hours.value, metric.value, signal)
    ]);

    let machineData: MachineCavityRow[] = [];
    let bodyData: BodyCavityRow[] = [];
    if (machineRes.status === "fulfilled") {
      const data = machineRes.value?.data;
      machineData = data?.rows || [];
      fromHour.value = data?.from_hour || "";
      toHour.value = data?.to_hour || "";
    } else if (!isAbortError(machineRes.reason)) {
      hint.value = backendErrorHint(machineRes.reason);
    }

    if (bodyRes.status === "fulfilled") {
      bodyData = bodyRes.value?.data?.rows || [];
    } else if (!isAbortError(bodyRes.reason)) {
      bodyHint.value = backendErrorHint(bodyRes.reason);
    }

    alertMachineCavities.value = alertCavityPairs(
      asPivotSource(machineData, "machine"),
      CAVITY_LETTERS,
      cavityLetter,
      "lim"
    );
    alertBodyCavities.value = alertCavityPairs(
      asPivotSource(bodyData, "body"),
      BODY_CAVITY_LETTERS,
      bodyCavityLetter,
      "body"
    );

    if (excludeAlertMachines.value && alertMachineCavities.value.length) {
      const bodyEx = await getBodyCavityRates(
        projectId.value,
        hours.value,
        metric.value,
        signal,
        { excludeMachineCavities: alertMachineCavities.value }
      ).catch(error => {
        if (!isAbortError(error)) bodyHint.value = backendErrorHint(error);
        return null;
      });
      if (bodyEx?.data) bodyData = bodyEx.data.rows || [];
    }

    if (excludeAlertBodies.value && alertBodyCavities.value.length) {
      const machineEx = await getMachineCavityRates(
        projectId.value,
        hours.value,
        metric.value,
        signal,
        { excludeBodyCavities: alertBodyCavities.value }
      ).catch(error => {
        if (!isAbortError(error)) hint.value = backendErrorHint(error);
        return null;
      });
      if (machineEx?.data) {
        machineData = machineEx.data.rows || [];
        fromHour.value = machineEx.data.from_hour || fromHour.value;
        toHour.value = machineEx.data.to_hour || toHour.value;
      }
    }

    rows.value = machineData;
    bodyRows.value = bodyData;
  } finally {
    loading.value = false;
  }
}

async function loadCatalog(id?: string) {
  catalogAbort?.abort();
  catalogAbort = new AbortController();
  const signal = catalogAbort.signal;
  loading.value = true;
  hint.value = "";
  try {
    const res = await getQueryCatalog(id, {}, signal);
    const data = res?.data;
    projects.value = data?.projects || [];
    if (data?.current?.project_id) projectId.value = data.current.project_id;
    else if (projects.value.length && !projectId.value) {
      projectId.value = projects.value[0].project_id;
    }
    ready.value = Boolean(data?.ready);
    metrics.value = data?.metrics || [];
    if (!metrics.value.some(item => item.key === metric.value)) {
      metric.value = metrics.value[0]?.key || "appearance";
    }
    if (!ready.value) {
      hint.value = "该项目还没有 ADS 数据";
      rows.value = [];
      bodyRows.value = [];
      return;
    }
    await loadTable();
  } catch (error) {
    if (!isAbortError(error)) hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

function onProjectChange(id: string) {
  projectId.value = id;
  loadCatalog(id);
}

function onWindowChange() {
  loadTable();
}

function onMetricChange() {
  loadTable();
}

onMounted(async () => {
  try {
    const res = await getCavityAlertRulesRemote();
    const remote = rulesFromRemote(res?.data);
    const local = loadCavityAlertRules();
    const hasLocal = Boolean(localStorage.getItem("limanalysis.cavity.alertRules"));
    if (hasLocal && isDefaultAlertRules(remote) && !isDefaultAlertRules(local)) {
      await saveCavityAlertRulesRemote(local);
      alertRules.value = local;
    } else {
      alertRules.value = remote;
      saveCavityAlertRules(remote);
    }
  } catch {
    alertRules.value = loadCavityAlertRules();
  }
  loadCatalog();
});

onUnmounted(() => {
  catalogAbort?.abort();
  tableAbort?.abort();
});
</script>

<template>
  <div class="cavity-page" v-loading="loading">
    <div class="cavity-projects">
      <PageTabs
        v-if="projectTabs.length"
        :model-value="projectId"
        :options="projectTabs"
        size="small"
        aria-label="项目"
        @change="onProjectChange"
      />
      <el-button
        class="cavity-alert-btn"
        size="small"
        @click="openAlertConfig"
      >
        预警规则
      </el-button>
    </div>

    <PageMetricBar :title="windowLabel" :metrics="summaryMetrics">
      <div class="cavity-filters">
        <label class="cavity-filter">
          <span>窗口</span>
          <el-select
            v-model="hours"
            size="small"
            placeholder="时间窗口"
            popper-class="cavity-filter-popper"
            @change="onWindowChange"
          >
            <el-option
              v-for="item in WINDOW_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </label>
        <label class="cavity-filter">
          <span>不良项</span>
          <el-select
            v-model="metric"
            size="small"
            placeholder="选择不良项"
            popper-class="cavity-filter-popper"
            @change="onMetricChange"
          >
            <el-option
              v-for="item in metrics"
              :key="item.key"
              :label="cavityMetricLabel(item)"
              :value="item.key"
            />
          </el-select>
        </label>
        <label class="cavity-exclude">
          <el-checkbox
            v-model="excludeAlertMachines"
            @change="loadTable"
          >
            排除 LIM 异常模穴
          </el-checkbox>
        </label>
        <label class="cavity-exclude">
          <el-checkbox
            v-model="excludeAlertBodies"
            @change="loadTable"
          >
            排除本体异常模穴
          </el-checkbox>
        </label>
      </div>
    </PageMetricBar>

    <el-alert
      v-if="excludeHint"
      class="cavity-hint"
      type="info"
      :closable="false"
      :title="excludeHint"
    />

    <el-alert
      v-if="hint"
      class="cavity-hint"
      type="warning"
      :closable="false"
      :title="hint"
    />

    <section class="cavity-panel">
      <div class="cavity-panel__head">
        <strong>机台 × 模穴交叉表</strong>
        <span>纵：机台 · 横：模穴 A–R · 点格子看历史曲线 · {{ limAlertHint }}</span>
      </div>
      <el-table
        class="cavity-table"
        :data="pivotRows"
        border
        :span-method="spanMethod"
        :cell-style="cellStyle"
        :cell-class-name="cellClassName"
        :header-cell-style="headerCellStyle"
        :empty-text="`${windowName}没有机台模穴数据`"
        @cell-click="onLimCellClick"
      >
        <el-table-column
          prop="entity"
          label="机台"
          width="72"
          fixed
          align="center"
        />
        <el-table-column
          prop="metric"
          label="指标"
          width="72"
          fixed
          align="center"
        >
          <template #default="{ row }">
            {{ row.metricLabel }}
          </template>
        </el-table-column>
        <el-table-column
          v-for="letter in CAVITY_LETTERS"
          :key="letter"
          :prop="`c_${letter}`"
          :label="letter"
          min-width="58"
          align="center"
        >
          <template #default="{ row }">
            <span class="num">{{ cellText(row, letter) }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="total"
          label="汇总"
          min-width="78"
          fixed="right"
          align="center"
        >
          <template #default="{ row }">
            <span class="num">{{ totalText(row) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-alert
      v-if="bodyHint"
      class="cavity-hint"
      type="warning"
      :closable="false"
      :title="bodyHint"
    />

    <section class="cavity-panel">
      <div class="cavity-panel__head">
        <strong>本体 × 模穴交叉表</strong>
        <span>纵：本体第 1 位（模具） · 横：本体第 2 位 1–8 → A–H · 点格子看历史曲线 · {{ bodyAlertHint }}</span>
      </div>
      <el-table
        class="cavity-table"
        :data="bodyPivotRows"
        border
        :span-method="bodySpanMethod"
        :cell-style="cellStyle"
        :cell-class-name="bodyCellClassName"
        :header-cell-style="headerCellStyle"
        :empty-text="`${windowName}没有本体模穴数据`"
        @cell-click="onBodyCellClick"
      >
        <el-table-column
          prop="entity"
          label="模具"
          width="72"
          fixed
          align="center"
        />
        <el-table-column
          prop="metric"
          label="指标"
          width="72"
          fixed
          align="center"
        >
          <template #default="{ row }">
            {{ row.metricLabel }}
          </template>
        </el-table-column>
        <el-table-column
          v-for="letter in BODY_CAVITY_LETTERS"
          :key="`body-${letter}`"
          :prop="`c_${letter}`"
          :label="letter"
          min-width="58"
          align="center"
        >
          <template #default="{ row }">
            <span class="num">{{ cellText(row, letter) }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="total"
          label="汇总"
          min-width="78"
          fixed="right"
          align="center"
        >
          <template #default="{ row }">
            <span class="num">{{ totalText(row) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog
      v-model="alertOpen"
      class="alert-dialog"
      width="680px"
      align-center
      destroy-on-close
    >
      <template #header>
        <div class="alert-dialog__head">
          <strong>预警规则</strong>
          <span>不良率达标且产量足够才标红</span>
        </div>
      </template>
      <div class="alert-grid">
        <section class="alert-group">
          <header class="alert-group__head">
            <strong>LIM</strong>
            <span>机台 × 模穴表；通知用机台线</span>
          </header>
          <div class="alert-pair">
            <div class="alert-block">
              <div class="alert-block__title">模穴</div>
              <label class="alert-field">
                <span>不良率 ≥</span>
                <el-input-number
                  v-model="alertDraft.limCavityRateAbovePct"
                  :min="0"
                  :max="100"
                  :precision="2"
                  :step="0.5"
                  controls-position="right"
                  size="small"
                />
                <em>%</em>
              </label>
              <label class="alert-field alert-field--wide">
                <span>产量不低于</span>
                <el-input-number
                  v-model="alertDraft.limCavityMinQty"
                  :min="0"
                  :max="1000000"
                  :step="10"
                  controls-position="right"
                  size="small"
                />
              </label>
            </div>
            <div class="alert-block">
              <div class="alert-block__title">机台</div>
              <label class="alert-field">
                <span>不良率 ≥</span>
                <el-input-number
                  v-model="alertDraft.limMachineRateAbovePct"
                  :min="0"
                  :max="100"
                  :precision="2"
                  :step="0.5"
                  controls-position="right"
                  size="small"
                />
                <em>%</em>
              </label>
              <label class="alert-field alert-field--wide">
                <span>产量不低于</span>
                <el-input-number
                  v-model="alertDraft.limMachineMinQty"
                  :min="0"
                  :max="1000000"
                  :step="10"
                  controls-position="right"
                  size="small"
                />
              </label>
            </div>
          </div>
        </section>
        <section class="alert-group">
          <header class="alert-group__head">
            <strong>本体</strong>
            <span>模具 × 模穴表</span>
          </header>
          <div class="alert-pair">
            <div class="alert-block">
              <div class="alert-block__title">模穴</div>
              <label class="alert-field">
                <span>不良率 ≥</span>
                <el-input-number
                  v-model="alertDraft.bodyCavityRateAbovePct"
                  :min="0"
                  :max="100"
                  :precision="2"
                  :step="0.5"
                  controls-position="right"
                  size="small"
                />
                <em>%</em>
              </label>
              <label class="alert-field alert-field--wide">
                <span>产量不低于</span>
                <el-input-number
                  v-model="alertDraft.bodyCavityMinQty"
                  :min="0"
                  :max="1000000"
                  :step="10"
                  controls-position="right"
                  size="small"
                />
              </label>
            </div>
            <div class="alert-block">
              <div class="alert-block__title">机台</div>
              <label class="alert-field">
                <span>不良率 ≥</span>
                <el-input-number
                  v-model="alertDraft.bodyMachineRateAbovePct"
                  :min="0"
                  :max="100"
                  :precision="2"
                  :step="0.5"
                  controls-position="right"
                  size="small"
                />
                <em>%</em>
              </label>
              <label class="alert-field alert-field--wide">
                <span>产量不低于</span>
                <el-input-number
                  v-model="alertDraft.bodyMachineMinQty"
                  :min="0"
                  :max="1000000"
                  :step="10"
                  controls-position="right"
                  size="small"
                />
              </label>
            </div>
          </div>
        </section>
      </div>
      <template #footer>
        <el-button @click="alertOpen = false">取消</el-button>
        <el-button type="primary" @click="saveAlertConfig">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="seriesOpen"
      class="series-dialog"
      width="1080px"
      align-center
      destroy-on-close
      @opened="seriesMounted = true"
      @closed="seriesMounted = false"
    >
      <template #header>
        <div class="alert-dialog__head">
          <strong>{{ seriesTitle }}</strong>
          <span>{{ metricName }}</span>
        </div>
      </template>
      <SeriesPanel
        v-if="seriesMounted"
        :project-id="projectId"
        :metric="metric"
        :filters="seriesFilters"
      />
    </el-dialog>
  </div>
</template>

<style lang="scss" scoped>
@use "@/style/cavity-page/scoped.scss" as *;
</style>

<style lang="scss">
@use "@/style/cavity-page/popper.scss" as *;
</style>
