<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  getDefectAnalysis,
  getDefectAnalysisRules,
  getScanBootstrap,
  saveDefectAnalysisRules,
  type DefectAnalysisRow,
  type ScanDefectOption,
  type ScanProject
} from "@/api/modules/scan";
import { backendErrorHint } from "@/api/http";
import {
  DEFAULT_CAVITY_ALERT,
  normalizeAlertRules,
  rulesFromRemote,
  toRemoteAlertRules,
  type AlertRules
} from "@/utils/cavityAlert";
import PageTabs from "@/components/PageTabs/index.vue";
import PageMetricBar from "@/components/PageMetricBar/index.vue";
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
  isAlert,
  rateOf,
  totalText,
  makeSpanMethod,
  makeLimAlertHint,
  pivotKeptTotals,
  type PivotRow,
  type PivotSource
} from "@/utils/pivotTable";

defineOptions({
  name: "ScanDefectAnalysis"
});

const loading = ref(false);
const hint = ref("");
const projects = ref<ScanProject[]>([]);
const defects = ref<ScanDefectOption[]>([]);
const projectId = ref("");
const defectItem = ref("");
const hours = ref(12);
const rows = ref<DefectAnalysisRow[]>([]);
const bodyRows = ref<DefectAnalysisRow[]>([]);
const fromHour = ref("");
const toHour = ref("");
const alertRules = ref<AlertRules>({ ...DEFAULT_CAVITY_ALERT });
const alertDraft = ref<AlertRules>({ ...DEFAULT_CAVITY_ALERT });
const alertOpen = ref(false);
const excludeAlertMachines = ref(false);
const excludeAlertBodies = ref(false);
const alertMachineCavities = ref<string[]>([]);
const alertBodyCavities = ref<string[]>([]);
let bootAbort: AbortController | null = null;
let tableAbort: AbortController | null = null;

/** 标红判定读当前规则（活引用，规则改动即时生效） */
const cellAlert = createCellAlert(() => alertRules.value);

const WINDOW_OPTIONS = [
  { value: 1, label: "近 1 小时" },
  { value: 3, label: "近 3 小时" },
  { value: 12, label: "近 12 小时" },
  { value: 24, label: "近 1 天" },
  { value: 72, label: "近 3 天" }
];

const projectTabs = computed(() =>
  projects.value.map(item => ({
    value: item.project_id,
    label: item.display_name
  }))
);

const windowName = computed(
  () =>
    WINDOW_OPTIONS.find(item => item.value === hours.value)?.label || "近 12 小时"
);

const defectName = computed(() => {
  if (!defectItem.value) return "全部次品";
  return (
    defects.value.find(item => item.key === defectItem.value)?.label ||
    defectItem.value
  );
});

function buildPivot(
  source: PivotSource[],
  axes: readonly string[],
  axisOf: (cavity: string) => string
): PivotRow[] {
  const byEntity = new Map<string, Map<string, { qty: number; ng: number }>>();
  for (const row of source) {
    const entity = String(row.entity || "").trim();
    const axis = axisOf(row.cavity);
    if (!entity || !axis || !axes.includes(axis)) continue;
    if (!byEntity.has(entity)) byEntity.set(entity, new Map());
    const cells = byEntity.get(entity)!;
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
      entity: String(row.machine || ""),
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
      entity: String(row.body || ""),
      cavity: row.cavity,
      qty: row.qty,
      ng: row.ng
    })),
    BODY_CAVITY_LETTERS,
    bodyCavityLetter
  )
);

const summary = computed(() =>
  pivotKeptTotals(
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

const windowLabel = computed(() => {
  if (fromHour.value && toHour.value && fromHour.value !== toHour.value) {
    return `${fromHour.value} ~ ${toHour.value}`;
  }
  return fromHour.value || toHour.value || windowName.value;
});

const summaryMetrics = computed(() => {
  const r = alertRules.value;
  const red = isAlert(
    summary.value.ratePct,
    summary.value.qty,
    r.limMachineRateAbovePct,
    r.limMachineMinQty
  );
  return [
    {
      value: formatRate(summary.value.ratePct) || "—",
      label: `${defectName.value}合计`,
      accent: true,
      alert: red
    },
    { value: formatQty(summary.value.qty), label: "产量" },
    { value: formatQty(summary.value.ng), label: "次品" },
    { value: summary.value.machines, label: "机台" }
  ];
});

function cellClassName({
  row,
  column
}: {
  row: PivotRow;
  column: { property?: string };
}) {
  return cellAlert({ row, column }, "lim") ? "is-alert" : "";
}

function bodyCellClassName({
  row,
  column
}: {
  row: PivotRow;
  column: { property?: string };
}) {
  return cellAlert({ row, column }, "body") ? "is-alert" : "";
}

function openAlertConfig() {
  alertDraft.value = { ...alertRules.value };
  alertOpen.value = true;
}

async function saveAlertConfig() {
  const next = normalizeAlertRules(alertDraft.value);
  try {
    const res = await saveDefectAnalysisRules(toRemoteAlertRules(next));
    alertRules.value = rulesFromRemote(res?.data);
    alertOpen.value = false;
    ElMessage.success("显红规则已保存");
    await loadTable();
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  }
}

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

const limAlertHint = makeLimAlertHint(() => alertRules.value);

const bodyAlertHint = computed(() => {
  const r = alertRules.value;
  return `模穴 ≥ ${r.bodyCavityRateAbovePct}%（产量不低于 ${r.bodyCavityMinQty} 才标）；模具 ≥ ${r.bodyMachineRateAbovePct}%（产量不低于 ${r.bodyMachineMinQty} 才标）`;
});

const spanMethod = makeSpanMethod(() => pivotRows.value);
const bodySpanMethod = makeSpanMethod(() => bodyPivotRows.value);

function asPivotSource(
  list: DefectAnalysisRow[],
  entityKey: "machine" | "body"
): PivotSource[] {
  return list.map(row => ({
    entity: String(row[entityKey] || ""),
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
      if (cellAlert({ row, column: { property: `c_${axis}` } }, kind)) {
        pairs.push(`${row.entity}:${axis}`);
      }
    }
  }
  return pairs;
}

async function fetchAnalysis(
  extra: {
    exclude_machine_cavities?: string;
    exclude_body_cavities?: string;
  },
  signal: AbortSignal
) {
  return getDefectAnalysis(
    {
      project_id: projectId.value,
      hours: hours.value,
      defect_item: defectItem.value || undefined,
      ...extra
    },
    signal
  );
}

async function loadTable() {
  if (!projectId.value) {
    rows.value = [];
    bodyRows.value = [];
    return;
  }
  tableAbort?.abort();
  tableAbort = new AbortController();
  const signal = tableAbort.signal;
  loading.value = true;
  hint.value = "";
  try {
    const res = await fetchAnalysis({}, signal);
    const data = res?.data;
    let machineData = data?.machines || [];
    let bodyData = data?.bodies || [];
    fromHour.value = data?.from_hour || "";
    toHour.value = data?.to_hour || "";

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

    const excludeMachines =
      excludeAlertMachines.value && alertMachineCavities.value.length
        ? alertMachineCavities.value.join(",")
        : "";
    const excludeBodies =
      excludeAlertBodies.value && alertBodyCavities.value.length
        ? alertBodyCavities.value.join(",")
        : "";
    if (excludeMachines || excludeBodies) {
      const filtered = await fetchAnalysis(
        {
          exclude_machine_cavities: excludeMachines || undefined,
          exclude_body_cavities: excludeBodies || undefined
        },
        signal
      );
      const next = filtered?.data;
      if (excludeBodies) machineData = next?.machines || [];
      if (excludeMachines) bodyData = next?.bodies || [];
      fromHour.value = next?.from_hour || fromHour.value;
      toHour.value = next?.to_hour || toHour.value;
    }

    rows.value = machineData;
    bodyRows.value = bodyData;
  } catch (error) {
    if (!isAbortError(error)) hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

async function loadBootstrap(id = "") {
  bootAbort?.abort();
  bootAbort = new AbortController();
  loading.value = true;
  hint.value = "";
  try {
    const res = await getScanBootstrap(id || undefined, bootAbort.signal);
    const data = res?.data;
    projects.value = data?.projects || [];
    projectId.value = data?.current_id || projectId.value || "";
    defects.value = data?.defects || [];
    if (!defects.value.some(item => item.key === defectItem.value)) {
      defectItem.value = "";
    }
    if (!projects.value.length) hint.value = "还没有启用的项目";
    try {
      const rulesRes = await getDefectAnalysisRules(bootAbort.signal);
      alertRules.value = rulesFromRemote(rulesRes?.data);
    } catch {
      alertRules.value = { ...DEFAULT_CAVITY_ALERT };
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
  loadBootstrap(id);
}

onMounted(() => {
  loadBootstrap();
});
onUnmounted(() => {
  bootAbort?.abort();
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
        显红规则
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
            @change="loadTable"
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
          <span>次品项</span>
          <el-select
            v-model="defectItem"
            size="small"
            clearable
            placeholder="全部次品"
            popper-class="cavity-filter-popper"
            @change="loadTable"
          >
            <el-option
              v-for="item in defects"
              :key="item.key"
              :label="item.label"
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
        <strong>LIM 机台 × 模穴交叉表</strong>
        <span>纵：机台 · 横：模穴 A–R · 不良率 = 次品数 / 原始库产量 · {{ limAlertHint }}</span>
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

    <section class="cavity-panel">
      <div class="cavity-panel__head">
        <strong>本体 × 模穴交叉表</strong>
        <span>纵：本体第 1 位（模具） · 横：本体第 2 位 1–8 → A–H · {{ bodyAlertHint }}</span>
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

    <el-dialog
      v-model="alertOpen"
      class="alert-dialog"
      width="680px"
      align-center
      destroy-on-close
    >
      <template #header>
        <div class="alert-dialog__head">
          <strong>显红规则</strong>
          <span>不良率达标且产量足够才标红</span>
        </div>
      </template>
      <div class="alert-grid">
        <section class="alert-group">
          <header class="alert-group__head">
            <strong>LIM</strong>
            <span>机台 × 模穴表</span>
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
              <div class="alert-block__title">模具</div>
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
  </div>
</template>

<style lang="scss" scoped>
@use "@/style/cavity-page/scoped.scss" as *;
</style>

<style lang="scss">
@use "@/style/cavity-page/popper.scss" as *;
</style>
