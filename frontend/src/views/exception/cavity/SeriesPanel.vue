<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import {
  getQuerySeries,
  type QueryFilters,
  type QueryHourRow
} from "@/api/modules/exception";
import { backendErrorHint } from "@/api/http";
import echarts from "@/plugins/echarts";
import PageTabs from "@/components/PageTabs/index.vue";

const props = defineProps<{
  projectId: string;
  metric: string;
  filters: QueryFilters;
}>();

const loading = ref(false);
const hint = ref("");
const pane = ref<"chart" | "table">("chart");
const paneOptions = [
  { value: "chart", label: "历史曲线" },
  { value: "table", label: "每小时明细" }
];
const metricLabel = ref("不良率");
const rows = ref<QueryHourRow[]>([]);
const chartEl = ref<HTMLDivElement | null>(null);
let chart: ReturnType<typeof echarts.init> | null = null;
let seriesAbort: AbortController | null = null;
let resizeObs: ResizeObserver | null = null;

function isAbortError(error: unknown) {
  return (
    (error as { code?: string; name?: string })?.code === "ERR_CANCELED" ||
    (error as { name?: string })?.name === "CanceledError" ||
    (error as { name?: string })?.name === "AbortError"
  );
}

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

const latestRow = computed(() => rows.value[rows.value.length - 1] || null);

const CHART = {
  moss: "#1e4e79",
  mossDeep: "#163c5c",
  ink: "#0c3f56",
  mute: "#6b7c70",
  line: "#d5ddd6",
  paper: "#fbfcf9",
  card: "#ffffff",
  rust: "#b45309",
  bar: "rgba(11, 154, 216, 0.16)"
};

function withAlpha(color: string, alpha: number) {
  const c = color.trim();
  if (c.startsWith("#") && (c.length === 7 || c.length === 4)) {
    const hex =
      c.length === 4 ? `#${c[1]}${c[1]}${c[2]}${c[2]}${c[3]}${c[3]}` : c;
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  return c;
}

function bindChart() {
  if (!chartEl.value) return;
  if (!chart) chart = echarts.init(chartEl.value);
  const labels = rows.value.map(item => item.hour_label);
  const last = rows.value.length - 1;
  let maxIdx = -1;
  let maxVal = -1;
  const points = rows.value.map((item, index) => {
    const value = item.rate_pct;
    if (value != null && value > maxVal) {
      maxVal = value;
      maxIdx = index;
    }
    const isLast = index === last;
    return {
      value,
      qty: item.qty,
      ng: item.ng,
      symbol: isLast ? "circle" : "emptyCircle",
      symbolSize: isLast ? 9 : 6,
      itemStyle: {
        color: isLast ? CHART.card : CHART.moss,
        borderColor: CHART.moss,
        borderWidth: isLast ? 2.5 : 1.25
      }
    };
  });
  const rateMax = Math.max(maxVal, 0);
  const yMax = Math.max(5, Math.ceil((rateMax * 1.2) / 5) * 5);
  const markPoint =
    maxIdx >= 0 && maxIdx !== last
      ? {
          silent: true,
          symbol: "circle",
          symbolSize: 7,
          itemStyle: { color: CHART.rust, borderColor: "#fff", borderWidth: 1.5 },
          label: {
            show: true,
            formatter: `${maxVal.toFixed(2)}%`,
            position: "top",
            distance: 6,
            color: CHART.rust,
            fontSize: 11,
            fontWeight: 700,
            fontFamily: "Calibri, Microsoft YaHei, sans-serif"
          },
          data: [{ coord: [labels[maxIdx], maxVal] }]
        }
      : undefined;

  chart.setOption(
    {
      color: [CHART.moss, CHART.bar],
      animationDuration: 480,
      animationEasing: "cubicOut",
      backgroundColor: CHART.paper,
      legend: {
        right: 8,
        top: 2,
        itemWidth: 12,
        itemHeight: 8,
        itemGap: 14,
        icon: "roundRect",
        textStyle: {
          color: CHART.mute,
          fontSize: 11,
          fontFamily: "Calibri, Microsoft YaHei, sans-serif"
        }
      },
      grid: { left: 44, right: 48, top: 36, bottom: 28, containLabel: false },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: CHART.card,
        borderColor: "#c6c6c6",
        borderWidth: 1,
        padding: [10, 12],
        extraCssText:
          "border-radius:2px;box-shadow:0 10px 22px rgba(31,61,46,0.12);",
        textStyle: {
          color: CHART.ink,
          fontSize: 12,
          fontFamily: "Calibri, Microsoft YaHei, sans-serif"
        },
        axisPointer: {
          type: "line",
          snap: true,
          lineStyle: { color: withAlpha(CHART.moss, 0.45), width: 1 },
          z: 1
        },
        formatter: (params: unknown) => {
          const list = Array.isArray(params) ? params : [params];
          const rateItem = list.find(
            (item: { seriesType?: string }) => item.seriesType === "line"
          ) as
            | {
                name?: string;
                data?: { value?: number | null; qty?: number; ng?: number };
              }
            | undefined;
          const data = rateItem?.data;
          const rate =
            data?.value == null ? "—" : `${Number(data.value).toFixed(2)}%`;
          const row = (css: string, label: string, value: string) =>
            `<div style="display:flex;justify-content:space-between;gap:28px;margin:4px 0;${css}"><span style="color:${CHART.mute}">${label}</span><b style="font-variant-numeric:tabular-nums;font-weight:650">${value}</b></div>`;
          return [
            `<div style="margin-bottom:8px;font-weight:700;color:${CHART.ink}">${rateItem?.name || ""}</div>`,
            row("", metricLabel.value, rate),
            row("", "产量", Number(data?.qty || 0).toLocaleString()),
            row("", "不良", Number(data?.ng || 0).toLocaleString())
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
        boundaryGap: true,
        axisLine: { lineStyle: { color: CHART.line } },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: {
          hideOverlap: true,
          color: CHART.mute,
          fontSize: 11,
          margin: 10,
          fontFamily: "Calibri, Microsoft YaHei, sans-serif"
        }
      },
      yAxis: [
        {
          type: "value",
          min: 0,
          max: yMax,
          splitNumber: 4,
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { lineStyle: { color: CHART.line, type: "solid", width: 1 } },
          axisLabel: {
            color: CHART.mute,
            fontSize: 11,
            margin: 8,
            fontFamily: "Calibri, Microsoft YaHei, sans-serif",
            formatter: (v: number) => `${v}%`
          }
        },
        {
          type: "value",
          min: 0,
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: {
            color: CHART.mute,
            fontSize: 11,
            margin: 8,
            fontFamily: "Calibri, Microsoft YaHei, sans-serif",
            formatter: (v: number) =>
              v >= 1000 ? `${Math.round(v / 1000)}k` : `${Math.round(v)}`
          }
        }
      ],
      series: [
        {
          type: "bar",
          name: "产量",
          yAxisIndex: 1,
          data: rows.value.map(item => item.qty),
          barMaxWidth: 18,
          itemStyle: { color: CHART.bar },
          emphasis: { itemStyle: { color: "rgba(11, 154, 216, 0.28)" } },
          z: 1
        },
        {
          type: "line",
          name: metricLabel.value,
          data: points,
          showSymbol: true,
          symbol: "emptyCircle",
          symbolSize: 6,
          connectNulls: false,
          smooth: 0.18,
          sampling: "lttb",
          z: 3,
          lineStyle: { width: 2.25, color: CHART.moss },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: withAlpha(CHART.moss, 0.18) },
              { offset: 1, color: withAlpha(CHART.moss, 0.01) }
            ])
          },
          endLabel: {
            show: last >= 0 && points[last]?.value != null,
            formatter: () => {
              const value = points[last]?.value;
              return value == null ? "" : `${Number(value).toFixed(2)}%`;
            },
            color: CHART.mossDeep,
            fontSize: 12,
            fontWeight: 700,
            offset: [6, 0],
            fontFamily: "Calibri, Microsoft YaHei, sans-serif"
          },
          markPoint,
          emphasis: {
            scale: false,
            focus: "series",
            itemStyle: {
              color: CHART.card,
              borderColor: CHART.moss,
              borderWidth: 2
            }
          }
        }
      ]
    },
    true
  );
  chart.resize();
}

async function loadSeries() {
  if (!props.projectId) {
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
      props.projectId,
      props.metric || "appearance",
      props.filters,
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

function formatQty(value: number) {
  return Number(value || 0).toLocaleString();
}

function formatRate(value: number | null) {
  return value == null ? "—" : `${value.toFixed(2)}%`;
}

const headerCellStyle = {
  background: "#1e4e79",
  color: "#fff",
  fontWeight: 600,
  fontSize: "12px",
  borderColor: "#163c5c",
  textAlign: "center" as const,
  padding: "0"
};

function rowClass({ rowIndex }: { rowIndex: number }) {
  return rowIndex === 0 ? "is-latest" : "";
}

watch(chartEl, el => {
  resizeObs?.disconnect();
  if (!el) return;
  resizeObs = new ResizeObserver(() => chart?.resize());
  resizeObs.observe(el);
});

watch(pane, async value => {
  if (value !== "chart") return;
  await nextTick();
  chart?.resize();
});

onMounted(loadSeries);
onUnmounted(() => {
  seriesAbort?.abort();
  resizeObs?.disconnect();
  chart?.dispose();
  chart = null;
});
</script>

<template>
  <div class="series-panel" v-loading="loading">
    <PageTabs
      v-model="pane"
      :options="paneOptions"
      size="small"
      aria-label="历史数据"
    />
    <el-alert
      v-if="hint"
      class="series-hint"
      type="warning"
      :closable="false"
      :title="hint"
    />
    <section v-show="pane === 'chart'" class="query-panel query-panel--chart">
      <div class="query-panel__head">
        <strong>{{ metricLabel }}</strong>
        <span v-if="latestRow">
          最近 {{ latestRow.hour_label }}
          {{ formatRate(latestRow.rate_pct) }} · 窗口合计
          {{ formatRate(windowSummary.ratePct) }}
        </span>
      </div>
      <div v-show="rows.length" ref="chartEl" class="query-chart" />
      <div v-if="!rows.length && !loading" class="query-empty">
        当前筛选没有小时数据
      </div>
    </section>
    <section v-show="pane === 'table'" class="query-panel query-panel--table">
      <div class="query-panel__head">
        <strong>每小时明细</strong>
        <span v-if="rows.length"
          >{{ windowSummary.hours }} 小时 · 产量
          {{ formatQty(windowSummary.qty) }} · 不良
          {{ formatQty(windowSummary.ng) }}</span
        >
      </div>
      <el-table
        class="query-table"
        :data="tableRows"
        :row-class-name="rowClass"
        :header-cell-style="headerCellStyle"
        border
        height="100%"
        empty-text="无数据"
      >
        <el-table-column
          prop="hour_label"
          label="小时"
          min-width="110"
          align="center"
        />
        <el-table-column label="产量" min-width="88" align="center">
          <template #default="{ row }">
            <span class="num">{{ formatQty(row.qty) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="不良" min-width="80" align="center">
          <template #default="{ row }">
            <span class="num">{{ formatQty(row.ng) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="不良率" min-width="88" align="center">
          <template #default="{ row }">
            <span class="num">{{ formatRate(row.rate_pct) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.series-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: min(68vh, 640px);
  min-height: 420px;
}

.series-panel :deep(.page-tabs) {
  flex: none;
  align-self: flex-start;
}

.series-hint {
  flex: none;
}

.query-panel {
  display: flex;
  flex: 1;
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
  font-weight: 650;
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

.query-panel--chart {
  background: #fbfcf9;
  border: 1px solid #c6c6c6;
  border-radius: 0;
}

.query-panel--chart .query-panel__head {
  padding: 8px 10px 4px;
  background: #fff;
  border-bottom: 1px solid #e4ece6;
}

.query-panel--chart .query-panel__head strong::before {
  background: #1e4e79;
}

.query-chart {
  flex: 1;
  min-height: 0;
  padding: 0;
  background: #fbfcf9;
}

.query-empty {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.query-panel--table {
  background: #fff;
  border: 1px solid #c6c6c6;
  border-radius: 0;
}

.query-panel--table .query-panel__head {
  padding: 8px 10px 6px;
  background: #fff;
}

.query-panel--table :deep(.el-table) {
  flex: 1;
  --el-table-border-color: #c6c6c6;
  --el-table-header-bg-color: #1e4e79;
  --el-table-header-text-color: #fff;
  --el-table-row-hover-bg-color: #f5f5f5;
  --el-table-bg-color: #fff;
  font-family: Calibri, "Microsoft YaHei", "Segoe UI", sans-serif;
  font-size: 12px;
}

.query-panel--table :deep(.el-table__inner-wrapper::before),
.query-panel--table :deep(.el-table__inner-wrapper::after),
.query-panel--table :deep(.el-table__border-left-patch) {
  display: none;
}

.query-panel--table :deep(.el-table__header-wrapper th.el-table__cell) {
  padding: 0;
  height: 30px;
  background: #1e4e79 !important;
  color: #fff;
  border-color: #163c5c;
}

.query-panel--table :deep(td.el-table__cell) {
  height: 26px;
  padding: 0;
  border-color: #c6c6c6;
  background: #fff;
}

.query-panel--table :deep(.el-table__cell .cell) {
  padding: 0 6px;
  line-height: 26px;
}

.query-panel--table :deep(.is-latest td.el-table__cell) {
  background: #fff2cc;
  font-weight: 600;
}

.num {
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}
</style>
