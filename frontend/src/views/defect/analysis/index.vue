<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  getYieldAlerts,
  type YieldAlertRow,
  type YieldNotice
} from "@/api/modules/defect";
import {
  getViewerDates,
  type InspectionImage,
  type PhotoSource
} from "@/api/modules/inspection";
import { backendErrorHint } from "@/api/http";
import { rulesFromRemote } from "@/utils/cavityAlert";
import {
  emptyPhotoHint,
  fetchAppearanceCameraOptions,
  fetchCellPhotoDates,
  fetchCellPhotos,
  photoDateLabel,
  pickCameraValue,
  type PhotoCameraOption
} from "@/utils/machineCellPhotos";
import {
  DEFAULT_LIM_HOURS,
  DEFAULT_LIM_HOURS_LABEL,
  isAbortError
} from "@/utils/pivotTable";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import PageMetricBar from "@/components/PageMetricBar/index.vue";
import ZoomableImage from "@/components/ZoomableImage/index.vue";

defineOptions({
  name: "DefectAnalysis"
});

const loading = ref(false);
const hint = ref("");
const ready = ref(false);
const duty = ref("");
const fromHour = ref("");
const toHour = ref("");
const alerts = ref<YieldAlertRow[]>([]);
const notices = ref<YieldNotice[]>([]);
const selectedNoticeKey = ref("");
const rules = ref(rulesFromRemote());
let loadAbort: AbortController | null = null;

const windowLabel = computed(() => {
  if (fromHour.value && toHour.value && fromHour.value !== toHour.value) {
    return `${fromHour.value} ~ ${toHour.value}`;
  }
  return fromHour.value || toHour.value || DEFAULT_LIM_HOURS_LABEL;
});

const unassigned = computed(() => {
  const seen = new Set<string>();
  const rows: YieldAlertRow[] = [];
  for (const row of alerts.value) {
    if (row.contacts.length) continue;
    const key = `${row.project_id || ""}:${row.machine}`;
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push(row);
  }
  return rows;
});

const redMachineCount = computed(() => alerts.value.length);

const summaryMetrics = computed(() => [
  {
    value: redMachineCount.value,
    label: "异常机台",
    alert: redMachineCount.value > 0
  },
  { value: notices.value.length, label: "待通知" }
]);

// 表格表头配色从 token 借值（ECharts / Element Plus 的行内样式拿不到 CSS 变量）
function cssVar(name: string, fallback: string) {
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return v || fallback;
}

const CHART = {
  moss: cssVar("--el-color-primary", "#1e4e79"),
  mossDeep: cssVar("--el-color-primary-dark-2", "#163c5c"),
  onPrimary: cssVar("--el-color-white", "#fff")
};

const headerCellStyle = {
  background: CHART.moss,
  color: CHART.onPrimary,
  fontWeight: 600,
  fontSize: "12px",
  borderColor: CHART.mossDeep,
  textAlign: "center" as const,
  padding: "0"
};

function noticeKey(item: YieldNotice) {
  return `${item.name}\t${item.phone || ""}`;
}

const selectedNotice = computed(
  () => notices.value.find(item => noticeKey(item) === selectedNoticeKey.value) || null
);

const tableAlerts = computed(() => {
  const notice = selectedNotice.value;
  if (!notice) return alerts.value;
  const keys = new Set(
    notice.machines.map(row => `${row.project_id || ""}:${row.machine}`)
  );
  return alerts.value.filter(row =>
    keys.has(`${row.project_id || ""}:${row.machine}`)
  );
});

function rateText(value: number | null | undefined) {
  return value == null ? "—" : `${Number(value).toFixed(2)}%`;
}

function machineLine(row: {
  project_name?: string;
  machine: string;
  rate_pct: number | null;
}) {
  const rate = `不良率 ${rateText(row.rate_pct)}`;
  return row.project_name
    ? `${row.project_name} ${row.machine} ${rate}`
    : `${row.machine} ${rate}`;
}

/** 异常说明：后端已按项目登记的视角名排除；未登记则原样展示 */
function machineIssueText(row: YieldAlertRow) {
  const defects = row.defects || [];
  if (defects.length) {
    return defects
      .map(item => {
        const count = Number(item.ng || 0);
        const label = item.label || item.item;
        return count > 0
          ? `${label} ${Number(count).toLocaleString()}pcs`
          : label;
      })
      .join("、");
  }
  const reasons = (row.reasons || []).filter(Boolean);
  if (reasons.length) return reasons.join("、");
  return "窗口内无具体不良项";
}

const photoOpen = ref(false);
const photoLoading = ref(false);
const photoHint = ref("");
const photoTitle = ref("");
const photoSource = ref<PhotoSource>("mold");
const photoProjectId = ref("");
const photoMachine = ref("");
const photoCavity = ref("");
const photoCavities = ref<string[]>([]);
const photoDates = ref<string[]>([]);
const photoDate = ref("");
const photoToday = ref("");
const photoCameraOptions = ref<PhotoCameraOption[]>([]);
const photoCamera = ref("");
const photoImages = ref<InspectionImage[]>([]);
const photoIndex = ref(0);
const photoCurrent = computed(
  () => photoImages.value[photoIndex.value] || null
);

/** 与模穴页 SeriesPanel 同口径（machineCellPhotos） */
async function ensurePhotoDates(keepDate = false) {
  const meta = await fetchCellPhotoDates({
    projectId: photoProjectId.value,
    machine: photoMachine.value,
    source: photoSource.value
  });
  photoDates.value = meta.dates;
  photoToday.value = meta.today;
  if (keepDate && photoDate.value && meta.dates.includes(photoDate.value)) {
    return;
  }
  photoDate.value = meta.defaultDate;
}

async function ensurePhotoCavities() {
  if (!photoProjectId.value || !photoMachine.value) {
    photoCavities.value = [];
    return;
  }
  const dates = await getViewerDates(
    photoProjectId.value,
    photoMachine.value,
    photoSource.value,
    "",
    "mold"
  ).catch(() => null);
  const cavities = (dates?.data?.cavities || [])
    .map(item => String(item || "").trim().toUpperCase())
    .filter(Boolean);
  photoCavities.value = cavities;
  if (!cavities.length) {
    photoCavity.value = "";
    return;
  }
  if (!cavities.includes(photoCavity.value)) {
    photoCavity.value = cavities[0];
  }
}

async function ensureAppearanceCameras() {
  if (!photoDate.value || !photoCavity.value) {
    photoCameraOptions.value = [];
    photoCamera.value = "";
    return;
  }
  const options = await fetchAppearanceCameraOptions({
    projectId: photoProjectId.value,
    machine: photoMachine.value,
    cavity: photoCavity.value,
    date: photoDate.value
  });
  photoCameraOptions.value = options;
  photoCamera.value = pickCameraValue(options);
}

async function reloadPhotoImages() {
  photoImages.value = [];
  photoIndex.value = 0;
  photoHint.value = "";
  if (!photoProjectId.value || !photoMachine.value) {
    photoHint.value = "缺少机台";
    return;
  }
  if (!photoCavity.value) {
    photoHint.value = "该机台没有可用模穴图片";
    return;
  }
  if (!photoDate.value) {
    photoHint.value = "没有可用日期";
    return;
  }
  if (photoSource.value === "appearance" && !photoCamera.value) {
    photoHint.value = "没有可用视角";
    return;
  }
  photoLoading.value = true;
  try {
    const { images, hint: apiHint } = await fetchCellPhotos({
      projectId: photoProjectId.value,
      machine: photoMachine.value,
      cavity: photoCavity.value,
      date: photoDate.value,
      source: photoSource.value,
      camera: photoCamera.value
    });
    photoImages.value = images;
    if (!images.length) {
      photoHint.value = emptyPhotoHint(
        photoDate.value,
        photoToday.value,
        apiHint
      );
    }
  } catch (error) {
    photoHint.value = backendErrorHint(error);
  } finally {
    photoLoading.value = false;
  }
}

async function loadPhotos() {
  const source = photoSource.value;
  photoImages.value = [];
  photoIndex.value = 0;
  photoHint.value = "";
  if (!photoProjectId.value || !photoMachine.value) {
    photoHint.value = "缺少机台";
    return;
  }
  photoLoading.value = true;
  try {
    await ensurePhotoCavities();
    if (!photoCavity.value) {
      photoHint.value = "该机台没有可用模穴图片";
      return;
    }
    await ensurePhotoDates();
    if (!photoDate.value) {
      photoHint.value = "没有可用日期";
      return;
    }
    if (source === "appearance") {
      await ensureAppearanceCameras();
      if (!photoCamera.value) {
        photoHint.value = "没有可用视角";
        return;
      }
    }
    const { images, hint: apiHint } = await fetchCellPhotos({
      projectId: photoProjectId.value,
      machine: photoMachine.value,
      cavity: photoCavity.value,
      date: photoDate.value,
      source,
      camera: photoCamera.value
    });
    photoImages.value = images;
    if (!images.length) {
      photoHint.value = emptyPhotoHint(
        photoDate.value,
        photoToday.value,
        apiHint
      );
    }
  } catch (error) {
    photoHint.value = backendErrorHint(error);
  } finally {
    photoLoading.value = false;
  }
}

async function openPhotos(row: YieldAlertRow, source: PhotoSource) {
  if (!row.project_id || !row.machine) {
    ElMessage.warning("缺少机台，无法打开图片");
    return;
  }
  photoSource.value = source;
  photoProjectId.value = row.project_id;
  photoMachine.value = row.machine;
  photoCavity.value = "";
  photoCavities.value = [];
  photoDate.value = "";
  photoDates.value = [];
  photoToday.value = "";
  photoCamera.value = "";
  photoCameraOptions.value = [];
  photoTitle.value = `${source === "mold" ? "注塑机" : "外观机"} · ${row.machine}`;
  photoOpen.value = true;
  await loadPhotos();
}

async function onPhotoDateChange() {
  photoLoading.value = true;
  photoHint.value = "";
  try {
    if (photoSource.value === "appearance") {
      await ensureAppearanceCameras();
    }
    await reloadPhotoImages();
  } catch (error) {
    photoHint.value = backendErrorHint(error);
  } finally {
    photoLoading.value = false;
  }
}

async function onPhotoCameraChange() {
  if (photoSource.value !== "appearance") return;
  await reloadPhotoImages();
}

async function onPhotoCavityChange() {
  photoLoading.value = true;
  photoHint.value = "";
  try {
    if (photoSource.value === "appearance") {
      await ensureAppearanceCameras();
    }
    await reloadPhotoImages();
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
  if (!photoOpen.value) return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    shiftPhoto(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    shiftPhoto(1);
  }
}

function noticeText(item: YieldNotice) {
  const lines = [
    `【良率预警】${duty.value} ${windowLabel.value}`,
    `通知：${item.name}${item.phone ? ` ${item.phone}` : ""}`
  ];
  for (const machine of item.machines) {
    lines.push(machineLine(machine));
  }
  lines.push("请尽快到机台确认。");
  return lines.join("\n");
}

async function copyNotice(item: YieldNotice) {
  const text = noticeText(item);
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success(`已复制 ${item.name} 的通知`);
  } catch {
    ElMessage.error("复制失败");
  }
}

function selectNotice(item: YieldNotice) {
  const key = noticeKey(item);
  selectedNoticeKey.value = selectedNoticeKey.value === key ? "" : key;
}

async function load() {
  loadAbort?.abort();
  loadAbort = new AbortController();
  const signal = loadAbort.signal;
  loading.value = true;
  hint.value = "";
  try {
    const res = await getYieldAlerts({ hours: DEFAULT_LIM_HOURS }, signal);
    const data = res?.data;
    if (data?.rules) {
      rules.value = rulesFromRemote(data.rules);
    }
    ready.value = Boolean(data?.ready);
    duty.value = data?.duty || "";
    fromHour.value = data?.from_hour || "";
    toHour.value = data?.to_hour || "";
    // 直接用 yield-alerts（后端按 LIM 机台线汇总判红），不再本地重判
    const nextAlerts = data?.alerts || [];
    alerts.value = nextAlerts;
    notices.value = data?.notices || [];
    if (
      selectedNoticeKey.value &&
      !notices.value.some(item => noticeKey(item) === selectedNoticeKey.value)
    ) {
      selectedNoticeKey.value = "";
    }
    if (!ready.value) hint.value = "还没有 ADS 数据";
  } catch (error) {
    if (!isAbortError(error)) hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  load();
  window.addEventListener("keydown", onPhotoKey);
});
onUnmounted(() => {
  loadAbort?.abort();
  window.removeEventListener("keydown", onPhotoKey);
});
</script>

<template>
  <div class="alert-page" v-loading="loading">
    <PageMetricBar :metrics="summaryMetrics">
      <template #context>
        <strong
          class="alert-duty"
          :class="duty === '夜班' ? 'is-night' : 'is-day'"
        >
          {{ duty || "—" }}
        </strong>
        <span class="alert-chip">{{ windowLabel }}</span>
      </template>
      <template #end>
        <el-button size="small" @click="load()">刷新</el-button>
      </template>
    </PageMetricBar>

    <p v-if="hint" class="alert-banner" :class="{ warn: !ready }">
      <span class="alert-banner__icon">
        <component :is="useRenderIcon('ri/information-line')" />
      </span>
      {{ hint }}
    </p>

    <section class="alert-panel">
      <div class="alert-panel__head">
        <strong>待通知人员</strong>
      </div>
      <p v-if="!notices.length && !loading" class="alert-empty">
        {{
          alerts.length
            ? "有异常机台但排班表没有当班负责人"
            : `${DEFAULT_LIM_HOURS_LABEL}没有 LIM 异常机台`
        }}
      </p>
      <div v-else class="notice-grid">
        <article
          v-for="item in notices"
          :key="noticeKey(item)"
          class="notice-card"
          :class="{ 'is-active': selectedNoticeKey === noticeKey(item) }"
          role="button"
          tabindex="0"
          @click="selectNotice(item)"
          @keydown.enter.prevent="selectNotice(item)"
        >
          <strong>{{ item.name }}</strong>
          <span>{{ item.phone || "无电话" }}</span>
        </article>
      </div>
    </section>

    <section class="alert-panel">
      <div class="alert-panel__head">
        <strong>异常机台明细</strong>
        <span v-if="selectedNotice">
          {{ selectedNotice.name }}
          {{ selectedNotice.phone }} · {{ tableAlerts.length }} 台
        </span>
        <span v-else-if="unassigned.length">
          {{ unassigned.length }} 台未排到当前班次
        </span>
        <el-button
          v-if="selectedNotice"
          class="alert-copy"
          type="primary"
          size="small"
          @click="copyNotice(selectedNotice)"
        >
          复制通知
        </el-button>
      </div>
      <el-table
        class="alert-table"
        :data="tableAlerts"
        border
        :header-cell-style="headerCellStyle"
        empty-text="没有 LIM 异常机台"
      >
        <el-table-column
          prop="project_name"
          label="项目"
          width="108"
          align="center"
          header-align="center"
          show-overflow-tooltip
        />
        <el-table-column
          prop="machine"
          label="机台"
          width="56"
          align="center"
          header-align="center"
        />
        <el-table-column
          label="不良率"
          width="76"
          align="center"
          header-align="center"
        >
          <template #default="{ row }">
            <span class="num is-rate">{{ rateText(row.rate_pct) }}</span>
          </template>
        </el-table-column>
        <el-table-column
          label="产量"
          width="64"
          align="center"
          header-align="center"
        >
          <template #default="{ row }">
            <span class="num">{{ Number(row.qty || 0).toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column
          label="异常说明"
          min-width="240"
          align="left"
          header-align="center"
          class-name="is-issue"
        >
          <template #default="{ row }">
            <span class="issue-text" :class="{ 'is-rate': Number(row.ng || 0) > 0 }">
              {{ machineIssueText(row) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column
          label="图片"
          width="124"
          align="center"
          header-align="center"
        >
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              size="small"
              @click="openPhotos(row, 'mold')"
            >
              注塑机
            </el-button>
            <el-button
              link
              type="primary"
              size="small"
              @click="openPhotos(row, 'appearance')"
            >
              外观机
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog
      v-model="photoOpen"
      class="photo-dialog"
      width="94vw"
      align-center
      append-to-body
      destroy-on-close
      :show-close="true"
    >
      <template #header>
        <div class="photo-dialog__head">
          <strong>{{ photoTitle }}</strong>
          <el-select
            v-if="photoCavities.length"
            v-model="photoCavity"
            class="photo-dialog__select"
            size="small"
            placeholder="模穴"
            @change="onPhotoCavityChange"
          >
            <el-option
              v-for="letter in photoCavities"
              :key="letter"
              :label="`${letter}穴`"
              :value="letter"
            />
          </el-select>
          <el-select
            v-model="photoDate"
            class="photo-dialog__select photo-dialog__select--date"
            size="small"
            placeholder="日期"
            @change="onPhotoDateChange"
          >
            <el-option
              v-for="day in photoDates"
              :key="day"
              :label="photoDateLabel(day)"
              :value="day"
            />
          </el-select>
          <el-select
            v-if="photoSource === 'appearance'"
            v-model="photoCamera"
            class="photo-dialog__select photo-dialog__select--camera"
            size="small"
            placeholder="视角"
            @change="onPhotoCameraChange"
          >
            <el-option
              v-for="item in photoCameraOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
          <span v-if="photoCurrent" class="photo-dialog__file">
            {{ photoCurrent.filename }}
          </span>
          <span v-if="photoImages.length" class="photo-dialog__count">
            {{ photoIndex + 1 }} / {{ photoImages.length }}
          </span>
        </div>
      </template>
      <div class="photo-stage" v-loading="photoLoading">
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
          <ZoomableImage
            :src="photoCurrent.view_url"
            :alt="photoCurrent.filename"
          />
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
    </el-dialog>
  </div>
</template>

<style scoped>
.alert-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-sizing: border-box;
  min-height: calc(100vh - var(--la-chrome-total));
  margin: 0 !important;
  padding: 10px 12px 12px;
  background: color-mix(in srgb, var(--el-fill-color-light) 65%, var(--el-bg-color));
}

.alert-page :deep(.page-metric-bar) {
  column-gap: 8px;
}

.alert-page :deep(.page-metric-bar__metrics) {
  gap: 8px;
}

.alert-page :deep(.page-metric-bar__metric),
.alert-page :deep(.page-metric-bar__end .el-button) {
  box-sizing: border-box;
  width: 76px;
  height: 44px;
  min-width: 76px;
  margin: 0;
  padding: 0;
  border-radius: 6px;
}

.alert-page :deep(.page-metric-bar__end) {
  margin-left: 0;
}

.alert-page :deep(.page-metric-bar__end .el-button) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-color: var(--la-border-default);
  background: var(--la-surface-sunken);
  color: var(--la-text-body);
  font-size: 13px;
  font-weight: 650;
}

.alert-page :deep(.page-metric-bar__end .el-button:hover) {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
  background: var(--la-success-weak);
}

.alert-duty {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  line-height: 24px;
  letter-spacing: 0.02em;
}

.alert-duty.is-day {
  color: var(--la-warning-text);
  background: var(--la-warning-weak);
}

.alert-duty.is-night {
  color: var(--la-info-text);
  background: var(--la-info-weak);
}

.alert-chip {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 8px;
  border: 1px solid var(--la-border-default);
  border-radius: 6px;
  color: var(--la-text-muted);
  background: var(--la-surface-sunken);
  font-size: 12px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  line-height: 22px;
  white-space: nowrap;
}

.alert-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 8px 12px;
  font-size: 13px;
  line-height: 1.45;
  color: var(--la-text-body);
  background: var(--la-surface-card);
  border: 1px solid var(--la-border-default);
}

.alert-banner.warn {
  color: var(--la-warning-text);
  background: var(--la-warning-weak);
  border-color: color-mix(in oklab, var(--el-color-warning) 40%, transparent);
}

.alert-banner__icon {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  font-size: 14px;
  color: var(--el-color-warning);
}

.alert-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--la-surface-card);
  border: 1px solid var(--la-border-default);
}

.alert-panel__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--la-border-subtle);
}

.alert-copy {
  margin-left: auto;
}

.alert-panel__head strong {
  color: var(--la-success-text);
  font-size: 13px;
  font-weight: 700;
}

.alert-panel__head span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.alert-empty {
  margin: 0;
  padding: 28px 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  text-align: center;
}

.notice-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px;
}

.notice-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-width: 132px;
  padding: 10px 16px;
  background: color-mix(in srgb, var(--el-color-danger) 8%, var(--el-bg-color));
  border: 1px solid color-mix(in srgb, var(--el-color-danger) 24%, var(--el-border-color));
  border-radius: 10px;
  text-align: center;
  cursor: pointer;
}

.notice-card:hover,
.notice-card:focus-visible {
  border-color: color-mix(in srgb, var(--el-color-danger) 50%, var(--el-border-color));
  background: color-mix(in srgb, var(--el-color-danger) 12%, var(--el-bg-color));
  outline: none;
}

.notice-card.is-active {
  background: color-mix(in srgb, var(--el-color-danger) 18%, var(--el-bg-color));
  border-color: color-mix(in srgb, var(--el-color-danger) 58%, var(--el-border-color));
}

.notice-card strong {
  color: var(--el-text-color-primary);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.2;
}

.notice-card span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  line-height: 1.3;
}

.alert-table {
  flex: none;
  --el-table-border-color: var(--la-border-default);
  --el-table-header-bg-color: var(--el-color-primary);
  --el-table-header-text-color: var(--el-color-white);
  --el-table-row-hover-bg-color: var(--el-fill-color-light);
  font-family: Calibri, "Microsoft YaHei", "Segoe UI", sans-serif;
  font-size: 12px;
}

.alert-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.alert-table :deep(.el-table__header-wrapper th.el-table__cell) {
  padding: 0;
  height: 30px;
  background: var(--el-color-primary) !important;
  color: var(--el-color-white);
  border-color: var(--el-color-primary-dark-2);
}

.alert-table :deep(td.el-table__cell) {
  height: auto;
  min-height: 26px;
  padding: 0;
  border-color: var(--la-border-default);
}

.alert-table :deep(.el-table__cell .cell) {
  padding: 0 8px;
  line-height: 26px;
}

.alert-table :deep(th.el-table__cell .cell) {
  padding: 0 6px;
}

.alert-table :deep(td.el-table__cell.is-right .cell) {
  padding-right: 10px;
}

.alert-table :deep(td.el-table__cell.is-issue .cell) {
  padding: 4px 10px;
  line-height: 1.4;
}

.alert-table :deep(td .issue-text) {
  line-height: 1.4;
}

.num {
  display: inline-block;
  min-width: 100%;
  text-align: center;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

.issue-text {
  display: block;
  text-align: left;
  line-height: 1.4;
  white-space: normal;
  word-break: break-word;
}

.is-rate {
  color: var(--la-danger-text);
  font-weight: 700;
}

.photo-dialog__head {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding-right: 28px;
}

.photo-dialog__head strong {
  flex: none;
  color: var(--la-media-text);
  font-size: 16px;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.photo-dialog__select {
  flex: none;
  width: 112px;
}

.photo-dialog__select--date {
  width: 128px;
}

.photo-dialog__select--camera {
  width: 148px;
}

.photo-dialog__select :deep(.el-select__wrapper) {
  background: var(--la-media-field, rgba(255, 255, 255, 0.08));
  box-shadow: 0 0 0 1px var(--la-media-field-ring, rgba(255, 255, 255, 0.14))
    inset;
}

.photo-dialog__select :deep(.el-select__placeholder),
.photo-dialog__select :deep(.el-select__selected-item) {
  color: var(--la-media-text, #f4f4f5);
}

.photo-dialog__file {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: rgba(244, 244, 245, 0.62);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.photo-dialog__count {
  flex: none;
  padding: 2px 8px;
  border-radius: 999px;
  color: var(--la-media-text);
  background: rgba(255, 255, 255, 0.1);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  font-weight: 650;
}

.photo-stage {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  height: calc(90vh - 64px);
  min-height: 560px;
  background: var(--la-media-bg);
}

.photo-stage :deep(.zoomable-image) {
  inset: 12px 64px;
}

.photo-empty {
  margin: 0;
  color: rgba(244, 244, 245, 0.72);
  font-size: 14px;
}

.photo-nav {
  position: absolute;
  top: 50%;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  color: var(--la-media-text);
  background: rgba(18, 20, 26, 0.72);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  cursor: pointer;
  transform: translateY(-50%);
}

.photo-nav.is-prev {
  left: 16px;
}

.photo-nav.is-next {
  right: 16px;
}

.photo-nav:hover:not(:disabled) {
  background: rgba(33, 115, 70, 0.92);
}

.photo-nav:focus-visible {
  outline: 2px solid var(--el-color-success);
  outline-offset: 2px;
}

.photo-nav:disabled {
  opacity: 0.28;
  cursor: default;
}

.photo-nav :deep(svg) {
  width: 22px;
  height: 22px;
}
</style>

<style>
.photo-dialog.el-dialog {
  --el-dialog-bg-color: var(--la-media-head);
  --el-dialog-padding-primary: 0;
  max-width: 1480px;
  margin-top: 3vh !important;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 28px 64px rgba(0, 0, 0, 0.48);
}

.photo-dialog .el-dialog__header {
  margin: 0;
  padding: 14px 18px 12px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.photo-dialog .el-dialog__headerbtn {
  top: 14px;
  right: 14px;
  width: 28px;
  height: 28px;
}

.photo-dialog .el-dialog__close {
  color: rgba(244, 244, 245, 0.72);
}

.photo-dialog .el-dialog__body {
  padding: 0;
}

.photo-dialog .el-loading-mask {
  background: rgba(11, 12, 16, 0.55);
}
</style>
