<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import {
  getQuerySeries,
  type QueryFilters,
  type QueryHourRow
} from "@/api/modules/exception";
import {
  getViewerDates,
  getViewerFolders,
  getViewerImages,
  type InspectionImage,
  type PhotoSource
} from "@/api/modules/inspection";
import { backendErrorHint } from "@/api/http";
import echarts from "@/plugins/echarts";
import PageTabs from "@/components/PageTabs/index.vue";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";

const props = defineProps<{
  projectId: string;
  metric: string;
  filters: QueryFilters;
}>();

type PaneKey = "chart" | "table" | "mold" | "appearance";

const loading = ref(false);
const hint = ref("");
const pane = ref<PaneKey>("chart");
const paneOptions = [
  { value: "chart", label: "历史曲线" },
  { value: "table", label: "每小时明细" },
  { value: "mold", label: "注塑机图片" },
  { value: "appearance", label: "自动外观图片" }
];
const metricLabel = ref("不良率");
const rows = ref<QueryHourRow[]>([]);
const chartEl = ref<HTMLDivElement | null>(null);
let chart: ReturnType<typeof echarts.init> | null = null;
let seriesAbort: AbortController | null = null;
let resizeObs: ResizeObserver | null = null;

const photoLoading = ref(false);
const photoHint = ref("");
const photoImages = ref<InspectionImage[]>([]);
const photoIndex = ref(0);
const photoCameras = ref<string[]>([]);
const photoCamera = ref("");
const photoCurrent = computed(
  () => photoImages.value[photoIndex.value] || null
);
const photoMachine = computed(() => String(props.filters?.machine || "").trim());
const photoCavity = computed(() =>
  String(props.filters?.cavity_letter || props.filters?.cavity || "")
    .trim()
    .toUpperCase()
);

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

async function ensurePhotoCameras() {
  if (!props.projectId) {
    photoCameras.value = [];
    photoCamera.value = "";
    return;
  }
  const folders = await getViewerFolders(props.projectId, "", "mold").catch(
    () => null
  );
  const cameras = folders?.data?.cameras || [];
  photoCameras.value = cameras;
  if (!cameras.length) {
    photoCamera.value = "";
    return;
  }
  if (!cameras.includes(photoCamera.value)) {
    photoCamera.value = cameras[0];
  }
}

async function collectImages(source: PhotoSource) {
  const machine = photoMachine.value;
  const cavity = photoCavity.value;
  if (!cavity) return [];
  if (source === "appearance") {
    const camera = photoCamera.value;
    if (!camera) return [];
    const dates = await getViewerDates(
      props.projectId,
      machine,
      "appearance",
      camera,
      "mold"
    ).catch(() => null);
    const day = dates?.data?.default_date || dates?.data?.dates?.[0] || "";
    if (!day) return [];
    const res = await getViewerImages({
      project_id: props.projectId,
      machine,
      cavity,
      date: day,
      source: "appearance",
      dim: "mold",
      camera
    });
    return res?.data?.images || [];
  }
  const dates = await getViewerDates(props.projectId, machine, "mold");
  const day = dates?.data?.default_date || dates?.data?.dates?.[0] || "";
  if (!day) return [];
  const res = await getViewerImages({
    project_id: props.projectId,
    machine,
    cavity,
    date: day,
    status: "OK",
    source: "mold"
  });
  return res?.data?.images || [];
}

async function loadPhotos(source: PhotoSource) {
  photoImages.value = [];
  photoIndex.value = 0;
  photoHint.value = "";
  if (!props.projectId) {
    photoHint.value = "未选择项目";
    return;
  }
  if (!photoMachine.value) {
    photoHint.value = "请先点选具体机台单元格后再看图片";
    return;
  }
  if (!photoCavity.value) {
    photoHint.value =
      source === "appearance"
        ? "请先点选具体模穴单元格后再看自动外观图片"
        : "请先点选具体模穴单元格后再看注塑机图片";
    return;
  }
  photoLoading.value = true;
  try {
    if (source === "appearance") {
      await ensurePhotoCameras();
      if (!photoCamera.value) {
        photoHint.value = "没有可用视角";
        return;
      }
    }
    const images = await collectImages(source);
    photoImages.value = images;
    if (!images.length) photoHint.value = "这一天没有找到图片";
  } catch (error) {
    photoHint.value = backendErrorHint(error);
  } finally {
    photoLoading.value = false;
  }
}

function shiftPhoto(step: number) {
  if (!photoImages.value.length) return;
  const next = photoIndex.value + step;
  if (next < 0 || next >= photoImages.value.length) return;
  photoIndex.value = next;
}

function onPhotoKey(event: KeyboardEvent) {
  if (pane.value !== "mold" && pane.value !== "appearance") return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    shiftPhoto(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    shiftPhoto(1);
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
  if (value === "chart") {
    await nextTick();
    chart?.resize();
    return;
  }
  if (value === "mold" || value === "appearance") {
    await loadPhotos(value);
  }
});

async function onPhotoCameraChange() {
  if (pane.value !== "appearance") return;
  await loadPhotos("appearance");
}

onMounted(() => {
  loadSeries();
  window.addEventListener("keydown", onPhotoKey);
});
onUnmounted(() => {
  seriesAbort?.abort();
  resizeObs?.disconnect();
  chart?.dispose();
  chart = null;
  window.removeEventListener("keydown", onPhotoKey);
});
</script>

<template>
  <div
    class="series-panel"
    v-loading="loading || (photoLoading && (pane === 'mold' || pane === 'appearance'))"
  >
    <PageTabs
      v-model="pane"
      :options="paneOptions"
      size="small"
      aria-label="历史数据"
    />
    <el-alert
      v-if="hint && (pane === 'chart' || pane === 'table')"
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

    <section
      v-show="pane === 'mold' || pane === 'appearance'"
      class="query-panel query-panel--photo"
    >
      <div class="query-panel__head">
        <strong>{{ pane === "mold" ? "注塑机图片" : "自动外观图片" }}</strong>
        <span v-if="photoMachine">
          {{ photoMachine
          }}{{ photoCavity ? ` · ${photoCavity}穴` : "" }}
        </span>
        <el-select
          v-if="pane === 'appearance'"
          v-model="photoCamera"
          class="photo-camera"
          size="small"
          placeholder="视角"
          @change="onPhotoCameraChange"
        >
          <el-option
            v-for="code in photoCameras"
            :key="code"
            :label="code"
            :value="code"
          />
        </el-select>
        <span v-if="photoCurrent" class="photo-file">{{ photoCurrent.filename }}</span>
        <span v-if="photoImages.length" class="photo-count">
          {{ photoIndex + 1 }} / {{ photoImages.length }}
        </span>
        <button
          type="button"
          class="photo-reload"
          @click="loadPhotos(pane === 'mold' ? 'mold' : 'appearance')"
        >
          刷新
        </button>
      </div>
      <div class="photo-stage">
        <p v-if="photoHint" class="photo-empty">{{ photoHint }}</p>
        <template v-else-if="photoCurrent">
          <button
            class="photo-nav is-prev"
            type="button"
            :disabled="photoIndex <= 0"
            aria-label="上一张"
            @click="shiftPhoto(-1)"
          >
            <component :is="useRenderIcon('ri/arrow-left-s-line')" />
          </button>
          <img :src="photoCurrent.view_url" :alt="photoCurrent.filename" />
          <button
            class="photo-nav is-next"
            type="button"
            :disabled="photoIndex >= photoImages.length - 1"
            aria-label="下一张"
            @click="shiftPhoto(1)"
          >
            <component :is="useRenderIcon('ri/arrow-right-s-line')" />
          </button>
        </template>
        <p v-else-if="!photoLoading" class="photo-empty">暂无图片</p>
      </div>
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

.query-panel--photo {
  background: #0b0c10;
  border: 1px solid #1f2430;
  border-radius: 0;
}

.query-panel--photo .query-panel__head {
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  background: #12141a;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  color: #f4f4f5;
}

.query-panel--photo .query-panel__head strong {
  color: #f4f4f5;
}

.query-panel--photo .query-panel__head strong::before {
  background: #69b889;
}

.query-panel--photo .query-panel__head span {
  color: rgba(244, 244, 245, 0.62);
}

.photo-camera {
  width: 132px;
  flex: none;
}

.photo-camera :deep(.el-select__wrapper) {
  background: rgba(255, 255, 255, 0.08);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.14) inset;
}

.photo-camera :deep(.el-select__placeholder),
.photo-camera :deep(.el-select__selected-item) {
  color: #f4f4f5;
}

.photo-file {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.photo-count {
  flex: none;
  padding: 2px 8px;
  border-radius: 999px;
  color: #f4f4f5;
  background: rgba(255, 255, 255, 0.1);
  font-variant-numeric: tabular-nums;
  font-weight: 650;
}

.photo-reload {
  flex: none;
  margin-left: auto;
  border: 0;
  padding: 2px 8px;
  border-radius: 6px;
  background: transparent;
  color: #69b889;
  font-size: 12px;
  cursor: pointer;
}

.photo-reload:hover {
  background: rgba(255, 255, 255, 0.06);
}

.photo-stage {
  position: relative;
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  min-height: 0;
  background: #0b0c10;
}

.photo-stage img {
  max-width: calc(100% - 96px);
  max-height: 100%;
  object-fit: contain;
}

.photo-empty {
  margin: 0;
  color: rgba(244, 244, 245, 0.72);
  font-size: 13px;
}

.photo-nav {
  position: absolute;
  top: 50%;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  color: #f4f4f5;
  background: rgba(18, 20, 26, 0.72);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  cursor: pointer;
  transform: translateY(-50%);
}

.photo-nav.is-prev {
  left: 12px;
}

.photo-nav.is-next {
  right: 12px;
}

.photo-nav:hover:not(:disabled) {
  background: rgba(33, 115, 70, 0.92);
}

.photo-nav:disabled {
  opacity: 0.28;
  cursor: default;
}

.photo-nav :deep(svg) {
  width: 20px;
  height: 20px;
}
</style>
