<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import {
  getQueryCatalog,
  getQuerySeries,
  type QueryDimField,
  type QueryFilters,
  type QueryHourRow,
  type QueryMetric,
  type QueryProject
} from "@/api/modules/exception";
import { backendErrorHint } from "@/api/http";
import echarts from "@/plugins/echarts";
import PageTabs from "@/components/PageTabs/index.vue";
import PageMetricBar from "@/components/PageMetricBar/index.vue";

defineOptions({
  name: "ExceptionQuery"
});

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
const dimFields = ref<QueryDimField[]>([]);
const dimOptions = ref<Record<string, string[]>>({});
const metrics = ref<QueryMetric[]>([]);
const ready = ref(false);
const line = ref("");
const machine = ref("");
const cavity = ref("");
const core = ref("");
const metric = ref("appearance");
const metricLabel = ref("自动外观不良率");
const rows = ref<QueryHourRow[]>([]);
const chartEl = ref<HTMLDivElement | null>(null);
let chart: ReturnType<typeof echarts.init> | null = null;
let catalogAbort: AbortController | null = null;
let seriesAbort: AbortController | null = null;
let resizeObs: ResizeObserver | null = null;

function onWinResize() {
  chart?.resize();
}

function isAbortError(error: unknown) {
  return (
    (error as { code?: string; name?: string })?.code === "ERR_CANCELED" ||
    (error as { name?: string })?.name === "CanceledError" ||
    (error as { name?: string })?.name === "AbortError"
  );
}

const filters = computed<QueryFilters>(() => {
  const next: QueryFilters = {};
  if (line.value) next.line = line.value;
  if (machine.value) next.machine = machine.value;
  if (cavity.value) next.cavity = cavity.value;
  if (core.value) next.core = core.value;
  return next;
});

const tableRows = computed(() => [...rows.value].reverse());

const windowSummary = computed(() => {
  const qty = rows.value.reduce((sum, row) => sum + Number(row.qty || 0), 0);
  const ng = rows.value.reduce((sum, row) => sum + Number(row.ng || 0), 0);
  return {
    qty,
    ng,
    hours: rows.value.length,
    ratePct: qty > 0 ? Math.round((ng / qty) * 10000) / 100 : null
  };
});

const latestRow = computed(() => tableRows.value[0] || null);

const summaryMetrics = computed(() => {
  if (!rows.value.length) return [];
  return [
    {
      value: formatRate(windowSummary.value.ratePct),
      label: "筛选合计",
      accent: true
    },
    {
      value: formatRate(latestRow.value?.rate_pct ?? null),
      label: latestRow.value?.hour_label
        ? `最近 ${latestRow.value.hour_label}`
        : "最近小时"
    }
  ];
});

const maxRate = computed(() => {
  let max = 0;
  for (const row of rows.value) {
    if (row.rate_pct != null) max = Math.max(max, row.rate_pct);
  }
  return max || 1;
});

function dimValue(key: QueryDimField["key"]) {
  if (key === "line") return line.value;
  if (key === "machine") return machine.value;
  if (key === "cavity") return cavity.value;
  return core.value;
}

function setDim(key: QueryDimField["key"], value: string | number | null) {
  const next = String(value || "");
  if (key === "line") line.value = next;
  else if (key === "machine") machine.value = next;
  else if (key === "cavity") cavity.value = next;
  else core.value = next;
  onFilterChange();
}

function pruneSelect(current: string, options: string[]) {
  if (!current) return "";
  return options.includes(current) ? current : "";
}

function chartColors() {
  const el = chartEl.value;
  if (!el) {
    return {
      primary: "#3b6ce8",
      muted: "#8a93a3",
      line: "#e7eaf0",
      text: "#5b6472",
      card: "#ffffff"
    };
  }
  const styles = getComputedStyle(el);
  return {
    primary: styles.getPropertyValue("--el-color-primary").trim() || "#3b6ce8",
    muted: styles.getPropertyValue("--el-text-color-secondary").trim() || "#8a93a3",
    line: styles.getPropertyValue("--el-border-color-extra-light").trim() || "#e7eaf0",
    text: styles.getPropertyValue("--el-text-color-regular").trim() || "#5b6472",
    card: styles.getPropertyValue("--el-bg-color").trim() || "#ffffff"
  };
}

function withAlpha(color: string, alpha: number) {
  const c = color.trim();
  if (c.startsWith("#") && (c.length === 7 || c.length === 4)) {
    const hex =
      c.length === 4
        ? `#${c[1]}${c[1]}${c[2]}${c[2]}${c[3]}${c[3]}`
        : c;
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  const rgb = c.match(/rgba?\(([^)]+)\)/i);
  if (rgb) {
    const [r, g, b] = rgb[1].split(",").map(s => s.trim());
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  return c;
}

function bindChart() {
  if (!chartEl.value) return;
  if (!chart) chart = echarts.init(chartEl.value);
  const colors = chartColors();
  const labels = rows.value.map(item => item.hour_label);
  const last = rows.value.length - 1;
  const points = rows.value.map((item, index) => ({
    value: item.rate_pct,
    qty: item.qty,
    ng: item.ng,
    symbol: index === last ? "circle" : "none",
    symbolSize: index === last ? 9 : 0,
    itemStyle:
      index === last
        ? {
            color: colors.card,
            borderColor: colors.primary,
            borderWidth: 2.5,
            shadowBlur: 8,
            shadowColor: withAlpha(colors.primary, 0.35)
          }
        : undefined
  }));
  chart.setOption(
    {
      color: [colors.primary],
      animationDuration: 420,
      animationEasing: "cubicOut",
      grid: { left: 48, right: 20, top: 22, bottom: 32, containLabel: false },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: withAlpha(colors.card, 0.96),
        borderColor: colors.line,
        borderWidth: 1,
        padding: [10, 12],
        extraCssText:
          "border-radius:10px;box-shadow:0 8px 24px rgba(15,23,42,0.08);backdrop-filter:blur(6px);",
        textStyle: { color: colors.text, fontSize: 12 },
        axisPointer: {
          type: "line",
          snap: true,
          lineStyle: {
            color: withAlpha(colors.primary, 0.45),
            width: 1,
            type: [4, 4]
          },
          label: { show: false }
        },
        formatter: (params: unknown) => {
          const list = Array.isArray(params) ? params : [params];
          const item = list[0] as {
            name?: string;
            data?: { value?: number | null; qty?: number; ng?: number };
          };
          const data = item?.data;
          const rate =
            data?.value == null ? "—" : `${Number(data.value).toFixed(2)}%`;
          return [
            `<div style="margin-bottom:6px;font-weight:650;letter-spacing:-0.01em">${item?.name || ""}</div>`,
            `<div style="display:flex;justify-content:space-between;gap:18px;margin:3px 0"><span style="color:${colors.muted}">${metricLabel.value}</span><b style="font-variant-numeric:tabular-nums">${rate}</b></div>`,
            `<div style="display:flex;justify-content:space-between;gap:18px;margin:3px 0"><span style="color:${colors.muted}">产量</span><span style="font-variant-numeric:tabular-nums">${Number(data?.qty || 0).toLocaleString()}</span></div>`,
            `<div style="display:flex;justify-content:space-between;gap:18px;margin:3px 0"><span style="color:${colors.muted}">不良</span><span style="font-variant-numeric:tabular-nums">${Number(data?.ng || 0).toLocaleString()}</span></div>`
          ].join("");
        }
      },
      dataZoom: [
        {
          type: "inside",
          xAxisIndex: 0,
          filterMode: "none",
          zoomOnMouseWheel: "shift"
        }
      ],
      xAxis: {
        type: "category",
        data: labels,
        boundaryGap: false,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: {
          hideOverlap: true,
          color: colors.muted,
          fontSize: 11,
          margin: 12
        }
      },
      yAxis: {
        type: "value",
        min: 0,
        splitNumber: 4,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: {
          lineStyle: {
            color: withAlpha(colors.line, 0.95),
            type: [3, 5]
          }
        },
        axisLabel: {
          color: colors.muted,
          fontSize: 11,
          margin: 10,
          formatter: (v: number) => `${Math.round(v)}%`
        }
      },
      series: [
        {
          type: "line",
          name: metricLabel.value,
          data: points,
          showSymbol: true,
          connectNulls: false,
          smooth: 0.28,
          sampling: "lttb",
          lineStyle: {
            width: 2.5,
            color: colors.primary,
            shadowBlur: 10,
            shadowColor: withAlpha(colors.primary, 0.22),
            shadowOffsetY: 3
          },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: withAlpha(colors.primary, 0.28) },
              { offset: 0.55, color: withAlpha(colors.primary, 0.08) },
              { offset: 1, color: withAlpha(colors.primary, 0.01) }
            ])
          },
          emphasis: {
            focus: "series",
            scale: true,
            itemStyle: {
              color: colors.card,
              borderColor: colors.primary,
              borderWidth: 2.5,
              shadowBlur: 10,
              shadowColor: withAlpha(colors.primary, 0.4)
            }
          }
        }
      ]
    },
    true
  );
}

async function loadSeries() {
  if (!projectId.value || !ready.value) {
    rows.value = [];
    chart?.clear();
    return;
  }
  seriesAbort?.abort();
  seriesAbort = new AbortController();
  const signal = seriesAbort.signal;
  loading.value = true;
  hint.value = "";
  try {
    const res = await getQuerySeries(
      projectId.value,
      metric.value || "appearance",
      filters.value,
      signal
    );
    const data = res?.data;
    metricLabel.value = data?.metric_label || "不良率";
    rows.value = data?.rows || [];
    await nextTick();
    bindChart();
  } catch (error) {
    if (!isAbortError(error)) hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

async function loadCatalog(id?: string, resetDims = false) {
  catalogAbort?.abort();
  catalogAbort = new AbortController();
  const signal = catalogAbort.signal;
  loading.value = true;
  hint.value = "";
  try {
    const res = await getQueryCatalog(id, resetDims ? {} : filters.value, signal);
    const data = res?.data;
    projects.value = data?.projects || [];
    if (data?.current?.project_id) projectId.value = data.current.project_id;
    else if (projects.value.length && !projectId.value) {
      projectId.value = projects.value[0].project_id;
    }
    ready.value = Boolean(data?.ready);
    dimFields.value = data?.dim_fields || [];
    dimOptions.value = data?.dims || {};
    metrics.value = data?.metrics || [];
    if (resetDims) {
      line.value = "";
      machine.value = "";
      cavity.value = "";
      core.value = "";
    } else {
      line.value = pruneSelect(line.value, dimOptions.value.line || []);
      machine.value = pruneSelect(machine.value, dimOptions.value.machine || []);
      cavity.value = pruneSelect(cavity.value, dimOptions.value.cavity || []);
      core.value = pruneSelect(core.value, dimOptions.value.core || []);
    }
    if (!metrics.value.some(item => item.key === metric.value)) {
      metric.value = metrics.value[0]?.key || "appearance";
    }
    if (!ready.value) {
      hint.value = "该项目还没有 ADS 数据";
      rows.value = [];
      chart?.clear();
      return;
    }
    await loadSeries();
  } catch (error) {
    if (!isAbortError(error)) hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

function onProjectChange(id: string) {
  projectId.value = id;
  loadCatalog(id, true);
}

function onFilterChange() {
  loadCatalog(projectId.value);
}

function formatQty(value: number) {
  return Number(value || 0).toLocaleString();
}

function formatRate(value: number | null) {
  return value == null ? "—" : `${value.toFixed(2)}%`;
}

function rateBar(row: QueryHourRow) {
  if (row.rate_pct == null) return "0%";
  return `${Math.max(4, (row.rate_pct / maxRate.value) * 100)}%`;
}

function rowClass({ rowIndex }: { rowIndex: number }) {
  return rowIndex === 0 ? "is-latest" : "";
}

watch(chartEl, el => {
  resizeObs?.disconnect();
  if (!el) return;
  resizeObs = new ResizeObserver(() => chart?.resize());
  resizeObs.observe(el);
});

onMounted(() => {
  loadCatalog();
  window.addEventListener("resize", onWinResize);
});

onUnmounted(() => {
  catalogAbort?.abort();
  seriesAbort?.abort();
  resizeObs?.disconnect();
  window.removeEventListener("resize", onWinResize);
  chart?.dispose();
  chart = null;
});
</script>

<template>
  <div class="query-page" v-loading="loading">
    <div class="query-projects">
      <PageTabs
        v-if="projectTabs.length"
        :model-value="projectId"
        :options="projectTabs"
        size="small"
        aria-label="项目"
        @change="onProjectChange"
      />
    </div>

    <PageMetricBar :metrics="summaryMetrics">
      <div class="query-filters">
        <label v-for="field in dimFields" :key="field.key" class="query-field">
          <span>{{ field.label }}</span>
          <el-select
            :model-value="dimValue(field.key)"
            clearable
            filterable
            size="small"
            :placeholder="`全部${field.label}`"
            @update:model-value="val => setDim(field.key, val)"
          >
            <el-option
              v-for="opt in dimOptions[field.key] || []"
              :key="opt"
              :label="opt"
              :value="opt"
            />
          </el-select>
        </label>
        <label class="query-field query-field--metric">
          <span>指标</span>
          <el-select v-model="metric" filterable size="small" @change="loadSeries">
            <el-option
              v-for="item in metrics"
              :key="item.key"
              :label="item.label"
              :value="item.key"
            />
          </el-select>
        </label>
      </div>
    </PageMetricBar>

    <el-alert
      v-if="hint"
      class="query-hint"
      type="warning"
      :closable="false"
      :title="hint"
    />

    <div class="query-body">
      <section class="query-panel">
        <div class="query-panel__head">
          <strong>{{ metricLabel }}</strong>
          <span>历史曲线</span>
        </div>
        <div v-show="rows.length" ref="chartEl" class="query-chart" />
        <div v-if="!rows.length" class="query-empty">当前筛选没有小时数据</div>
      </section>

      <section class="query-panel query-panel--table">
        <div class="query-panel__head">
          <strong>每小时明细</strong>
          <span v-if="rows.length">{{ windowSummary.hours }} 小时 · 产量
            {{ formatQty(windowSummary.qty) }} · 不良
            {{ formatQty(windowSummary.ng) }}</span>
        </div>
        <el-table
          class="query-table"
          :data="tableRows"
          :row-class-name="rowClass"
          height="100%"
          empty-text="无数据"
        >
          <el-table-column prop="hour_label" label="小时" min-width="108" />
          <el-table-column label="产量" min-width="88" align="right">
            <template #default="{ row }">
              <span class="num">{{ formatQty(row.qty) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="不良数" min-width="88" align="right">
            <template #default="{ row }">
              <span class="num">{{ formatQty(row.ng) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="不良率" min-width="168">
            <template #default="{ row }">
              <div class="rate-cell">
                <span class="rate-cell__track">
                  <i
                    v-if="row.rate_pct"
                    class="rate-cell__bar"
                    :style="{ width: rateBar(row) }"
                  />
                </span>
                <span class="num rate-cell__value">{{ formatRate(row.rate_pct) }}</span>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>
  </div>
</template>

<style scoped>
.query-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-sizing: border-box;
  /* 抵消 layout .main-content 的 24px，但不能用负 margin（会顶进 tags 栏被遮挡） */
  height: calc(100vh - 86px);
  min-height: 0;
  margin: 0 !important;
  padding: 10px 12px 12px;
  background: color-mix(in srgb, var(--el-fill-color-light) 65%, var(--el-bg-color));
}

.query-projects {
  position: relative;
  z-index: 2;
  flex: none;
  padding: 2px 0 4px;
}

.query-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px 12px;
  min-width: 0;
  width: 100%;
}

.query-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1;
}

.query-field :deep(.el-select) {
  width: 128px;
}

.query-field--metric :deep(.el-select) {
  width: 176px;
}

.query-hint {
  flex: none;
}

.query-body {
  display: grid;
  grid-template-rows: minmax(280px, 38vh) minmax(0, 1fr);
  gap: 12px;
  min-height: 0;
  flex: 1;
}

.query-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background:
    linear-gradient(
      180deg,
      color-mix(in srgb, var(--el-color-primary) 3.5%, var(--el-bg-color)) 0%,
      var(--el-bg-color) 48px
    );
  border: 1px solid var(--el-border-color-extra-light);
  border-radius: 14px;
  box-shadow: 0 1px 0 color-mix(in srgb, var(--el-color-primary) 4%, transparent);
  overflow: hidden;
}

.query-panel__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 14px 18px 6px;
}

.query-panel__head strong {
  position: relative;
  padding-left: 12px;
  color: var(--el-text-color-primary);
  font-size: 14px;
  font-weight: 650;
  letter-spacing: -0.01em;
}

.query-panel__head strong::before {
  content: "";
  position: absolute;
  top: 0.2em;
  left: 0;
  width: 3px;
  height: 0.95em;
  background: var(--el-color-primary);
  border-radius: 99px;
}

.query-panel__head span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.query-chart {
  flex: 1;
  min-height: 0;
  padding: 0 4px 6px;
}

.query-empty {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.query-panel--table :deep(.el-table) {
  flex: 1;
  --el-table-border-color: transparent;
  --el-table-header-bg-color: transparent;
  --el-table-row-hover-bg-color: color-mix(
    in srgb,
    var(--el-color-primary) 6%,
    var(--el-bg-color)
  );
  font-size: 13px;
}

.query-panel--table :deep(.el-table__inner-wrapper::before),
.query-panel--table :deep(.el-table__inner-wrapper::after),
.query-panel--table :deep(.el-table__border-left-patch) {
  display: none;
}

.query-panel--table :deep(th.el-table__cell) {
  padding: 6px 16px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 500;
}

.query-panel--table :deep(td.el-table__cell) {
  padding: 9px 16px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
}

.query-panel--table :deep(.is-latest td.el-table__cell) {
  background: color-mix(in srgb, var(--el-color-primary) 5%, var(--el-bg-color));
}

.num {
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

.rate-cell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 64px;
  gap: 10px;
  align-items: center;
}

.rate-cell__track {
  display: block;
  height: 6px;
  overflow: hidden;
  background: var(--el-fill-color);
  border-radius: 99px;
}

.rate-cell__bar {
  display: block;
  height: 100%;
  background: var(--el-color-primary);
  border-radius: inherit;
}

.rate-cell__value {
  text-align: right;
  color: var(--el-text-color-primary);
  font-weight: 600;
}

@media (prefers-reduced-motion: reduce) {
  .rate-cell__bar {
    transition: none;
  }
}
</style>
