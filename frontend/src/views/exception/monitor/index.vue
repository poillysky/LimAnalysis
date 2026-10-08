<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { getMetabaseBoard, type BoardOption, type BoardProject } from "@/api/modules/exception";
import {
  getRuntimeStatus,
  type RuntimeStatus,
  type SchedulerStatus
} from "@/api/modules/runtime";
import { backendErrorHint } from "@/api/http";
import { isAbortError } from "@/utils/pivotTable";
import PageTabs from "@/components/PageTabs/index.vue";

defineOptions({
  name: "ExceptionMonitor"
});

type LampTone = "ok" | "warn" | "bad" | "idle";

type RuntimeLamp = {
  key: string;
  label: string;
  tone: LampTone;
  short: string;
  detail: string;
};

const loading = ref(false);
const hint = ref("");
const projects = ref<BoardProject[]>([]);
const projectId = ref("");
const boardKind = ref("");
const boards = ref<BoardOption[]>([]);
const embedUrl = ref("");
const runtime = ref<RuntimeStatus | null>(null);
const runtimeHint = ref("");
const detailOpen = ref(false);
const activeLamp = ref("");
let boardTimer: number | null = null;
let runtimeTimer: number | null = null;
let runtimeAbort: AbortController | null = null;

const projectTabs = computed(() =>
  projects.value.map(item => ({
    value: item.project_id,
    label: item.display_name
  }))
);
const boardTabs = computed(() =>
  boards.value.map(item => ({
    value: item.kind,
    label: item.label
  }))
);

const overallOk = computed(() => runtime.value?.status === "ok");
const workshopOffline = computed(() => !!runtime.value?.workshop?.offline);

function storeOk(key: keyof NonNullable<RuntimeStatus["stores"]>) {
  return !!runtime.value?.stores?.[key]?.ok;
}

function workerLabel(role: "collector" | "agg") {
  const w = runtime.value?.workers?.[role];
  if (!w) return "未知";
  if (w.alive) return w.last_seen ? `在线 · ${w.last_seen.slice(11)}` : "在线";
  if (!w.last_seen) return "未启动";
  return `离线 · 上次 ${w.last_seen.slice(11) || w.last_seen}`;
}

function schedLabel(key: keyof NonNullable<RuntimeStatus["schedulers"]>) {
  const s = runtime.value?.schedulers?.[key] as SchedulerStatus | undefined;
  if (!s) return "—";
  if (key === "sfc" && s.blocked_by_workshop) return "车间离线已停采";
  const active = key === "disk_cleanup" ? s.enabled : s.is_active;
  const st = (s.last_run_status || "").trim();
  const t = (s.last_run_time || "").slice(11);
  if (s.job?.active) return `执行中${t ? ` · ${t}` : ""}`;
  if (!active) return st ? `已停 · ${st}` : "已停";
  if (!st) return "待命";
  return t ? `${st} · ${t}` : st;
}

function schedTone(key: keyof NonNullable<RuntimeStatus["schedulers"]>): LampTone {
  const s = runtime.value?.schedulers?.[key];
  if (!s) return "idle";
  if (key === "sfc" && s.blocked_by_workshop) return "warn";
  if (s.job?.active) return "ok";
  if (s.job?.ok === false) return "bad";
  const active = key === "disk_cleanup" ? s.enabled : s.is_active;
  if (!active) return "idle";
  return "ok";
}

const lamps = computed<RuntimeLamp[]>(() => {
  const storesAll =
    storeOk("meta") && storeOk("raw") && storeOk("dwh") && storeOk("defect");
  const storeBits = (["meta", "raw", "dwh", "defect"] as const)
    .map(k => `${k}=${storeOk(k) ? "通" : "断"}`)
    .join(" · ");

  const collectorAlive = !!runtime.value?.workers?.collector?.alive;
  const aggAlive = !!runtime.value?.workers?.agg?.alive;

  return [
    {
      key: "stores",
      label: "库",
      tone: storesAll ? "ok" : "bad",
      short: storesAll ? "通" : "断",
      detail: storeBits || "未读取"
    },
    {
      key: "collector",
      label: "采集",
      tone: collectorAlive ? "ok" : "bad",
      short: collectorAlive ? "在线" : "离线",
      detail: workerLabel("collector")
    },
    {
      key: "aggWorker",
      label: "聚合",
      tone: aggAlive ? "ok" : "bad",
      short: aggAlive ? "在线" : "离线",
      detail: workerLabel("agg")
    },
    {
      key: "sfc",
      label: "SFC",
      tone: schedTone("sfc"),
      short: shortSched("sfc"),
      detail: schedLabel("sfc")
    },
    {
      key: "etl",
      label: "ETL",
      tone: schedTone("etl"),
      short: shortSched("etl"),
      detail: schedLabel("etl")
    },
    {
      key: "agg",
      label: "ADS",
      tone: schedTone("agg"),
      short: shortSched("agg"),
      detail: schedLabel("agg")
    }
  ];
});

function shortSched(key: keyof NonNullable<RuntimeStatus["schedulers"]>) {
  const s = runtime.value?.schedulers?.[key];
  if (!s) return "—";
  if (key === "sfc" && s.blocked_by_workshop) return "停采";
  if (s.job?.active) return "执行";
  if (s.job?.ok === false) return "失败";
  const active = key === "disk_cleanup" ? s.enabled : s.is_active;
  if (!active) return "停";
  return "开";
}

const activeDetail = computed(() => {
  if (!activeLamp.value) return null;
  return lamps.value.find(item => item.key === activeLamp.value) || null;
});

const badCount = computed(
  () => lamps.value.filter(item => item.tone === "bad").length
);

function openLamp(key: string) {
  if (activeLamp.value === key && detailOpen.value) {
    detailOpen.value = false;
    return;
  }
  activeLamp.value = key;
  detailOpen.value = true;
}

function toggleDetail() {
  detailOpen.value = !detailOpen.value;
  if (detailOpen.value && !activeLamp.value) {
    activeLamp.value = lamps.value.find(item => item.tone === "bad")?.key || "stores";
  }
}

async function loadBoard(id?: string, kind?: string) {
  loading.value = true;
  hint.value = "";
  try {
    const res = await getMetabaseBoard(id, kind);
    const data = res?.data;
    projects.value = data?.projects || [];
    const current = data?.current;
    if (current?.project_id) projectId.value = current.project_id;
    else if (projects.value.length && !projectId.value) {
      projectId.value = projects.value[0].project_id;
    }
    boards.value = current?.boards || [];
    boardKind.value = current?.board || boards.value[0]?.kind || "";
    embedUrl.value = current?.embed_url || "";
    hint.value = data?.error || "";
  } catch (error) {
    embedUrl.value = "";
    hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

async function loadRuntime() {
  runtimeAbort?.abort();
  runtimeAbort = new AbortController();
  try {
    const res = await getRuntimeStatus(runtimeAbort.signal);
    runtime.value = res?.data || null;
    runtimeHint.value = "";
  } catch (error) {
    if (!isAbortError(error)) runtimeHint.value = backendErrorHint(error);
  }
}

function onProjectChange(id: string) {
  boardKind.value = "";
  loadBoard(id);
}

function onBoardChange(kind: string) {
  loadBoard(projectId.value, kind);
}

onMounted(() => {
  loadBoard();
  loadRuntime();
  boardTimer = window.setInterval(() => {
    if (projectId.value) loadBoard(projectId.value, boardKind.value || undefined);
  }, 45 * 60 * 1000);
  runtimeTimer = window.setInterval(() => {
    loadRuntime();
  }, 15 * 1000);
});

onUnmounted(() => {
  if (boardTimer) window.clearInterval(boardTimer);
  if (runtimeTimer) window.clearInterval(runtimeTimer);
  runtimeAbort?.abort();
});
</script>

<template>
  <div class="board-page" v-loading="loading">
    <section class="runtime-bar" :class="overallOk ? 'is-ok' : 'is-degraded'">
      <button
        type="button"
        class="runtime-summary"
        :title="overallOk ? '运行正常' : '运行降级'"
        @click="toggleDetail"
      >
        <span class="lamp" :class="overallOk ? 'ok' : 'warn'" />
        <span class="runtime-summary__text">
          {{ overallOk ? "正常" : "降级" }}
          <template v-if="badCount"> · {{ badCount }}</template>
        </span>
        <el-tag v-if="workshopOffline" size="small" type="warning" effect="plain">
          离线
        </el-tag>
      </button>

      <div class="runtime-lamps" role="list">
        <button
          v-for="item in lamps"
          :key="item.key"
          type="button"
          class="runtime-lamp"
          :class="[{ active: detailOpen && activeLamp === item.key }, item.tone]"
          role="listitem"
          :title="`${item.label}：${item.detail}`"
          @click="openLamp(item.key)"
        >
          <span class="lamp" :class="item.tone" />
          <span class="runtime-lamp__label">{{ item.label }}</span>
        </button>
      </div>

      <button type="button" class="runtime-refresh" title="刷新" @click="loadRuntime">
        刷新
      </button>
    </section>

    <div v-if="detailOpen" class="runtime-detail">
      <div v-if="runtimeHint" class="runtime-detail__err">{{ runtimeHint }}</div>
      <template v-else-if="activeDetail">
        <div class="runtime-detail__head">
          <span class="lamp" :class="activeDetail.tone" />
          <strong>{{ activeDetail.label }}</strong>
          <span class="runtime-detail__short">{{ activeDetail.short }}</span>
          <button type="button" class="runtime-detail__close" @click="detailOpen = false">
            收起
          </button>
        </div>
        <p class="runtime-detail__body">{{ activeDetail.detail }}</p>
      </template>
      <div v-else class="runtime-detail__err">正在读取运行状态…</div>
    </div>

    <div class="board-bar">
      <PageTabs
        v-if="projectTabs.length"
        :model-value="projectId"
        :options="projectTabs"
        aria-label="项目"
        @change="onProjectChange"
      />
      <PageTabs
        v-if="boardTabs.length > 1"
        :model-value="boardKind"
        :options="boardTabs"
        aria-label="看板"
        @change="onBoardChange"
      />
    </div>
    <el-alert
      v-if="hint"
      class="board-hint"
      type="warning"
      :closable="false"
      :title="hint"
    />
    <iframe
      v-if="embedUrl"
      class="board-frame"
      :key="embedUrl"
      :src="embedUrl"
      title="数据看板"
      allow="fullscreen"
    />
    <div v-else class="board-empty">
      {{
        hint ||
        "看板不可用：请确认局域网 Metabase 已启动，或到「外部连接」检查配置"
      }}
    </div>
  </div>
</template>

<style scoped>
.board-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 52px);
  min-height: 520px;
  margin: 0 !important;
  padding: 8px;
}

.runtime-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 32px;
  margin-bottom: 6px;
  padding: 4px 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}

.runtime-bar.is-degraded {
  border-color: color-mix(in srgb, var(--el-color-warning) 40%, var(--el-border-color-lighter));
}

.runtime-summary,
.runtime-lamp,
.runtime-refresh,
.runtime-detail__close {
  border: 0;
  background: transparent;
  padding: 0;
  cursor: pointer;
  font: inherit;
  color: inherit;
}

.runtime-summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding: 2px 4px;
  border-radius: 6px;
}

.runtime-summary:hover,
.runtime-lamp:hover,
.runtime-refresh:hover,
.runtime-detail__close:hover {
  background: var(--el-fill-color-light);
}

.runtime-summary__text {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.runtime-lamps {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 1;
  min-width: 0;
  overflow-x: auto;
}

.runtime-lamp {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 7px;
  border-radius: 999px;
  white-space: nowrap;
  transition:
    background 0.15s ease,
    box-shadow 0.15s ease;
}

.runtime-lamp.active {
  background: var(--el-fill-color);
  box-shadow: inset 0 0 0 1px var(--el-border-color);
}

.runtime-lamp__label {
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.runtime-refresh {
  flex-shrink: 0;
  padding: 2px 6px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--el-color-primary);
}

.lamp {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--el-text-color-disabled);
  box-shadow: inset 0 0 0 1px rgb(0 0 0 / 8%);
}

.lamp.ok {
  background: var(--el-color-success);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--el-color-success) 22%, transparent);
}

.lamp.warn {
  background: var(--el-color-warning);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--el-color-warning) 22%, transparent);
}

.lamp.bad {
  background: var(--el-color-danger);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--el-color-danger) 22%, transparent);
  animation: lamp-pulse 1.4s ease-in-out infinite;
}

.lamp.idle {
  background: var(--el-text-color-disabled);
}

@keyframes lamp-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}

.runtime-detail {
  margin: 0 0 8px;
  padding: 8px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}

.runtime-detail__head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.runtime-detail__head strong {
  font-size: 12px;
  font-weight: 600;
}

.runtime-detail__short {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.runtime-detail__close {
  margin-left: auto;
  padding: 2px 6px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.runtime-detail__body,
.runtime-detail__err {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-regular);
}

.runtime-detail__err {
  color: var(--el-text-color-secondary);
}

.board-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.board-hint {
  margin-bottom: 12px;
}

.board-frame {
  flex: 1;
  width: 100%;
  min-height: 0;
  border: 0;
  border-radius: 0;
  background: var(--el-bg-color);
}

.board-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  border: 1px dashed var(--el-border-color);
  border-radius: 12px;
}
</style>
