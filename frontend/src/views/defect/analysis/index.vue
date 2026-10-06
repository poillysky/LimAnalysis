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
  getViewerFolders,
  getViewerImages,
  type InspectionImage,
  type PhotoSource
} from "@/api/modules/inspection";
import { backendErrorHint } from "@/api/http";
import { rulesFromRemote } from "@/utils/cavityAlert";
import { isAbortError } from "@/utils/pivotTable";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import PageMetricBar from "@/components/PageMetricBar/index.vue";

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
  return fromHour.value || toHour.value || "近 3 小时";
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

const redCavityCount = computed(() => alerts.value.length);

const summaryMetrics = computed(() => [
  {
    value: redCavityCount.value,
    label: "红模穴",
    alert: redCavityCount.value > 0
  },
  { value: notices.value.length, label: "待通知" }
]);

const headerCellStyle = {
  background: "#1e4e79",
  color: "#fff",
  fontWeight: 600,
  fontSize: "12px",
  borderColor: "#163c5c",
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
  qty: number;
}) {
  const rate = `不良率 ${rateText(row.rate_pct)}（产量 ${Number(row.qty || 0).toLocaleString()}）`;
  return row.project_name
    ? `${row.project_name} ${row.machine} ${rate}`
    : `${row.machine} ${rate}`;
}

function isCavityAlert(row: {
  rate_pct: number | null;
  qty: number;
}) {
  if (row.rate_pct == null) return false;
  if (Number(row.qty) < rules.value.limCavityMinQty) return false;
  return row.rate_pct >= rules.value.limCavityRateAbovePct;
}

const CAMERA_ITEMS = new Set([
  "外长直边",
  "正面硅胶",
  "内长直边",
  "反面烟囱",
  "正面支架",
  "反面边框",
  "硅胶短边"
]);

function cavityIssueText(row: YieldAlertRow) {
  const letter = String(row.cavity || "").trim();
  const raw = String(row.cavity_raw || "").trim();
  const hole = letter ? `${letter}穴` : raw;
  const defects = (row.defects || []).filter(item => {
    const name = String(item.label || item.item || "").trim();
    return name && !CAMERA_ITEMS.has(name);
  });
  let detail = "";
  if (defects.length) {
    detail = defects
      .map(item => {
        const count = Number(item.ng || 0);
        const label = item.label || item.item;
        return count > 0
          ? `${label} ${Number(count).toLocaleString()}pcs`
          : label;
      })
      .join("、");
  } else {
    const reasons = (row.reasons || []).filter(
      name => name && !CAMERA_ITEMS.has(String(name).trim())
    );
    if (reasons.length) {
      detail = reasons.join("、");
    } else if (Number(row.ng || 0) > 0) {
      detail = `外观不良 ${Number(row.ng).toLocaleString()}pcs`;
    } else {
      detail = "窗口内无分项不良";
    }
  }
  return hole ? `${hole}：${detail}` : detail;
}

const photoOpen = ref(false);
const photoLoading = ref(false);
const photoHint = ref("");
const photoTitle = ref("");
const photoImages = ref<InspectionImage[]>([]);
const photoIndex = ref(0);
const photoCurrent = computed(
  () => photoImages.value[photoIndex.value] || null
);

async function collectImages(
  projectId: string,
  machine: string,
  cavity: string,
  source: PhotoSource
) {
  const images: InspectionImage[] = [];
  if (source === "appearance") {
    const folders = await getViewerFolders(projectId, machine).catch(() => null);
    const cameras = folders?.data?.cameras || [];
    const names = cameras.length ? cameras : [cavity];
    for (const camera of names) {
      const dates = await getViewerDates(
        projectId,
        machine,
        "appearance",
        camera
      ).catch(() => null);
      const day = dates?.data?.default_date || dates?.data?.dates?.[0] || "";
      if (!day) continue;
      const res = await getViewerImages({
        project_id: projectId,
        machine,
        cavity: camera,
        date: day,
        source: "appearance"
      }).catch(() => null);
      images.push(...(res?.data?.images || []));
    }
    return images;
  }
  const dates = await getViewerDates(projectId, machine, "mold");
  const day = dates?.data?.default_date || dates?.data?.dates?.[0] || "";
  if (!day) return [];
  const res = await getViewerImages({
    project_id: projectId,
    machine,
    cavity,
    date: day,
    status: "OK",
    source: "mold"
  });
  return res?.data?.images || [];
}

async function openPhotos(row: YieldAlertRow, source: PhotoSource) {
  const cavity = row.cavity || "";
  if (!row.project_id || !row.machine || (source === "mold" && !cavity)) {
    ElMessage.warning("缺少机台或穴位，无法打开图片");
    return;
  }
  photoTitle.value = `${source === "mold" ? "注塑机" : "外观机"} · ${row.machine}${
    cavity ? ` · ${cavity}` : ""
  }`;
  photoOpen.value = true;
  photoLoading.value = true;
  photoHint.value = "";
  photoImages.value = [];
  photoIndex.value = 0;
  try {
    const images = await collectImages(
      row.project_id,
      row.machine,
      cavity,
      source
    );
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
    const cavities = alerts.value.filter(
      row =>
        (row.project_id || "") === (machine.project_id || "") &&
        row.machine === machine.machine
    );
    for (const row of cavities) {
      const reason = cavityIssueText(row);
      lines.push(
        `  ${reason}；不良率 ${rateText(row.rate_pct)}（产量 ${Number(
          row.qty || 0
        ).toLocaleString()}）`
      );
    }
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
    const res = await getYieldAlerts({ hours: 3 }, signal);
    const data = res?.data;
    if (data?.rules) {
      rules.value = rulesFromRemote(data.rules);
    }
    ready.value = Boolean(data?.ready);
    duty.value = data?.duty || "";
    fromHour.value = data?.from_hour || "";
    toHour.value = data?.to_hour || "";
    const nextAlerts = (data?.alerts || []).filter(isCavityAlert);
    const allowed = new Set(
      nextAlerts.map(row => `${row.project_id || ""}:${row.machine}`)
    );
    alerts.value = nextAlerts;
    notices.value = (data?.notices || [])
      .map(item => ({
        ...item,
        machines: item.machines.filter(row =>
          allowed.has(`${row.project_id || ""}:${row.machine}`)
        )
      }))
      .filter(item => item.machines.length);
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
        <span class="alert-chip">近 3 小时</span>
        <span class="alert-chip">
          LIM 模穴 ≥ {{ rules.limCavityRateAbovePct }}%
          · 产量 &lt; {{ rules.limCavityMinQty }} 不预警
        </span>
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
        <span>点击姓名筛选下方红模穴；再点一次取消筛选</span>
      </div>
      <p v-if="!notices.length && !loading" class="alert-empty">
        {{
          alerts.length
            ? "有红模穴但排班表没有当班负责人"
            : "近 3 小时没有 LIM 红线模穴"
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
        <strong>红模穴明细</strong>
        <span v-if="selectedNotice">
          {{ selectedNotice.name }}
          {{ selectedNotice.phone }} · {{ tableAlerts.length }} 穴
        </span>
        <span v-else>
          一个穴位一行，含溢胶 / 缺胶等不良项
          <template v-if="unassigned.length">
            · {{ unassigned.length }} 台未排到当前班次
          </template>
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
        empty-text="没有 LIM 红线模穴"
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
          align="right"
          header-align="center"
        >
          <template #default="{ row }">
            <span class="num is-rate">{{ rateText(row.rate_pct) }}</span>
          </template>
        </el-table-column>
        <el-table-column
          label="产量"
          width="64"
          align="right"
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
              {{ cavityIssueText(row) }}
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
          <img
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
  min-height: calc(100vh - 86px);
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
  border-color: #e5e7eb;
  background: #fafafa;
  color: #374151;
  font-size: 13px;
  font-weight: 650;
}

.alert-page :deep(.page-metric-bar__end .el-button:hover) {
  border-color: #1e4e79;
  color: #1e4e79;
  background: #f3faf6;
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
  color: #8a5a00;
  background: #fff3d6;
}

.alert-duty.is-night {
  color: #1d4e89;
  background: #dceafb;
}

.alert-chip {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 8px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  color: #4b5563;
  background: #f9fafb;
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
  color: #374151;
  background: #fff;
  border: 1px solid #c6c6c6;
}

.alert-banner.warn {
  color: #92400e;
  background: #fffbeb;
  border-color: #f0d48a;
}

.alert-banner__icon {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  font-size: 14px;
  color: #d97706;
}

.alert-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fff;
  border: 1px solid #c6c6c6;
}

.alert-panel__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid #e4ece6;
}

.alert-copy {
  margin-left: auto;
}

.alert-panel__head strong {
  color: #1f3d2e;
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
  background: color-mix(in srgb, #f56c6c 8%, var(--el-bg-color));
  border: 1px solid color-mix(in srgb, #f56c6c 24%, var(--el-border-color));
  border-radius: 10px;
  text-align: center;
  cursor: pointer;
}

.notice-card:hover,
.notice-card:focus-visible {
  border-color: color-mix(in srgb, #f56c6c 50%, var(--el-border-color));
  background: color-mix(in srgb, #f56c6c 12%, var(--el-bg-color));
  outline: none;
}

.notice-card.is-active {
  background: color-mix(in srgb, #f56c6c 18%, var(--el-bg-color));
  border-color: color-mix(in srgb, #f56c6c 58%, var(--el-border-color));
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
  --el-table-border-color: #c6c6c6;
  --el-table-header-bg-color: #1e4e79;
  --el-table-header-text-color: #fff;
  --el-table-row-hover-bg-color: #f5f5f5;
  font-family: Calibri, "Microsoft YaHei", "Segoe UI", sans-serif;
  font-size: 12px;
}

.alert-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.alert-table :deep(.el-table__header-wrapper th.el-table__cell) {
  padding: 0;
  height: 30px;
  background: #1e4e79 !important;
  color: #fff;
  border-color: #163c5c;
}

.alert-table :deep(td.el-table__cell) {
  height: auto;
  min-height: 26px;
  padding: 0;
  border-color: #c6c6c6;
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
  color: #9c0006;
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
  color: #f4f4f5;
  font-size: 16px;
  font-weight: 650;
  letter-spacing: -0.02em;
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
  color: #f4f4f5;
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
  background: #0b0c10;
}

.photo-stage img {
  max-width: calc(100% - 128px);
  max-height: calc(90vh - 88px);
  object-fit: contain;
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
  color: #f4f4f5;
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
  outline: 2px solid #69b889;
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
  --el-dialog-bg-color: #12141a;
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
