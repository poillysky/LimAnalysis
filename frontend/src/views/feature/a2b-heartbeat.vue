<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import {
  getA2bHeartbeatStatus,
  type A2bHeartbeatSlot,
  type A2bHeartbeatStatus,
  type A2bPresence
} from "@/api/modules/a2bHeartbeat";
import { backendErrorHint } from "@/api/http";
import PageTabs from "@/components/PageTabs/index.vue";
import PageMetricBar from "@/components/PageMetricBar/index.vue";

defineOptions({
  name: "FeatureA2bHeartbeat"
});

type Mode = "mold" | "appearance";

type MachineCard = {
  key: string;
  projectId: string;
  projectName: string;
  machine: string;
  stations: A2bHeartbeatSlot[];
  /** 机台级汇总色调（取最差工站；外观机未齐站时不会是 ok） */
  tone: string;
  onlineCount: number;
  /** 外观：两工站都在线才算正常；注塑：本机在线 */
  healthy: boolean;
};

type ProjectGroup = {
  projectId: string;
  projectName: string;
  machines: MachineCard[];
};

const mode = ref<Mode>("mold");
const loading = ref(false);
const hint = ref("");
const status = ref<A2bHeartbeatStatus | null>(null);
let timer: ReturnType<typeof setInterval> | null = null;

const summary = computed(() => status.value?.summary);
const slots = computed(() => status.value?.slots ?? []);
const unregistered = computed(() => status.value?.unregistered ?? []);

/** 外观机：两工站都 presence=online 才算机台正常 */
function isAppearanceHealthy(stations: A2bHeartbeatSlot[]) {
  return (
    stations.length >= 2 && stations.every(s => s.presence === "online")
  );
}

/** 机台卡片色调：离线 > 告警 > 同步 > 从未 > 在线；外观未齐站时压掉 ok */
function machineTone(stations: A2bHeartbeatSlot[], appearance: boolean) {
  const rank: Record<string, number> = {
    off: 5,
    warn: 4,
    sync: 3,
    never: 2,
    ok: 1
  };
  let best = "never";
  let score = 0;
  for (const s of stations) {
    const t = statusTone(s);
    if ((rank[t] || 0) > score) {
      score = rank[t] || 0;
      best = t;
    }
  }
  if (appearance && best === "ok" && !isAppearanceHealthy(stations)) {
    return stations.some(s => s.presence === "offline") ? "off" : "never";
  }
  return best;
}

function presenceLabel(p: A2bPresence | string) {
  if (p === "online") return "在线";
  if (p === "offline") return "离线";
  return "从未";
}

function statusTone(slot: A2bHeartbeatSlot) {
  if (slot.presence === "online") {
    if (slot.client_status === "异常" || slot.paused) return "warn";
    if (slot.client_status === "同步中") return "sync";
    return "ok";
  }
  if (slot.presence === "offline") return "off";
  return "never";
}

function shortPath(path: string) {
  const text = (path || "").trim();
  if (!text) return "—";
  if (text.length <= 28) return text;
  return `…${text.slice(-26)}`;
}

function stationLabel(slot: A2bHeartbeatSlot) {
  const st = String(slot.station || "").trim();
  return st ? `工站 ${st}` : "工站";
}

function stationStatusText(slot: A2bHeartbeatSlot) {
  if (slot.presence === "never") return "未上报";
  if (slot.paused) return "已暂停";
  return slot.client_status || presenceLabel(slot.presence);
}

/** 外观：按项目 → 机台聚合，每机两工站；注塑：一机一槽 */
const groupedMachines = computed((): ProjectGroup[] => {
  const map = new Map<string, ProjectGroup>();

  if (mode.value === "appearance") {
    const byMachine = new Map<string, A2bHeartbeatSlot[]>();
    for (const slot of slots.value) {
      const mk = `${slot.project_id}::${slot.machine}`;
      const list = byMachine.get(mk) || [];
      list.push(slot);
      byMachine.set(mk, list);
    }
    for (const [, list] of byMachine) {
      list.sort((a, b) =>
        String(a.station).localeCompare(String(b.station), undefined, {
          numeric: true
        })
      );
      const head = list[0];
      const projectId = head.project_id || "_";
      let group = map.get(projectId);
      if (!group) {
        group = {
          projectId,
          projectName: head.project_name || projectId || "未命名项目",
          machines: []
        };
        map.set(projectId, group);
      }
      const onlineCount = list.filter(s => s.presence === "online").length;
      const healthy = isAppearanceHealthy(list);
      group.machines.push({
        key: `${projectId}:${head.machine}`,
        projectId,
        projectName: group.projectName,
        machine: head.machine,
        stations: list,
        tone: machineTone(list, true),
        onlineCount,
        healthy
      });
    }
  } else {
    for (const slot of slots.value) {
      const projectId = slot.project_id || "_";
      let group = map.get(projectId);
      if (!group) {
        group = {
          projectId,
          projectName: slot.project_name || projectId || "未命名项目",
          machines: []
        };
        map.set(projectId, group);
      }
      const online = slot.presence === "online";
      group.machines.push({
        key: slot.slot_key,
        projectId,
        projectName: group.projectName,
        machine: slot.machine || slot.title,
        stations: [slot],
        tone: statusTone(slot),
        onlineCount: online ? 1 : 0,
        healthy: online
      });
    }
  }

  return [...map.values()];
});

const allMachines = computed(() =>
  groupedMachines.value.flatMap(g => g.machines)
);

/** 顶栏 / Tab：外观按「机台是否双站在线」汇总，不再用工站数 */
const viewSummary = computed(() => {
  const machines = allMachines.value;
  const total = machines.length;
  const healthy = machines.filter(m => m.healthy).length;
  const abnormal = total - healthy;
  const unreg = unregistered.value.length;
  return { total, healthy, abnormal, unreg };
});

const tabs = computed(() => {
  const vs = viewSummary.value;
  const ready = status.value != null;
  if (mode.value === "appearance") {
    return [
      {
        value: "mold",
        label: "注塑机",
        hint: "单机心跳"
      },
      {
        value: "appearance",
        label: "外观机",
        hint: ready
          ? `${vs.total} 台 · ${vs.healthy} 正常（双站）`
          : "双工站都在线才正常",
        status: ready
          ? {
              ok: vs.abnormal === 0,
              label: vs.abnormal ? `${vs.abnormal} 异常` : "正常"
            }
          : undefined
      }
    ];
  }
  const s = summary.value;
  const offline = (s?.offline ?? 0) + (s?.never ?? 0);
  return [
    {
      value: "mold",
      label: "注塑机",
      hint: ready
        ? `${vs.total} 台 · ${vs.healthy} 在线`
        : "单机心跳",
      status: ready
        ? {
            ok: offline === 0,
            label: offline ? `${offline} 离线` : "正常"
          }
        : undefined
    },
    {
      value: "appearance",
      label: "外观机",
      hint: "双站都在线才正常"
    }
  ];
});

const summaryMetrics = computed(() => {
  const vs = viewSummary.value;
  if (!status.value) return [];
  if (mode.value === "appearance") {
    return [
      { value: vs.healthy, label: "正常", accent: true },
      { value: vs.abnormal, label: "异常", alert: vs.abnormal > 0 },
      ...(vs.unreg
        ? [{ value: vs.unreg, label: "未登记", alert: true }]
        : []),
      { value: vs.total, label: "机台" }
    ];
  }
  const s = summary.value!;
  return [
    { value: s.online, label: "在线", accent: true },
    { value: s.offline, label: "离线", alert: s.offline > 0 },
    { value: s.never, label: "从未" },
    ...(s.unregistered
      ? [{ value: s.unregistered, label: "未登记", alert: true }]
      : []),
    { value: s.total_slots, label: "槽位" }
  ];
});

function appearanceRatioText(card: MachineCard) {
  if (card.healthy) return "正常";
  if (card.onlineCount === 0) return "未在线";
  return `${card.onlineCount}/${card.stations.length} 在线`;
}

async function load(silent = false) {
  if (!silent) loading.value = true;
  try {
    const res = await getA2bHeartbeatStatus(mode.value);
    status.value = res?.data ?? null;
    hint.value = "";
  } catch (error) {
    if (!silent) {
      status.value = null;
      hint.value = backendErrorHint(error);
    }
  } finally {
    if (!silent) loading.value = false;
  }
}

function onTab(value: string) {
  if (value !== "mold" && value !== "appearance") return;
  mode.value = value;
}

function startPoll() {
  stopPoll();
  timer = setInterval(() => load(true), 20000);
}

function stopPoll() {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

watch(mode, () => {
  load();
});

onMounted(() => {
  load();
  startPoll();
});

onUnmounted(stopPoll);
</script>

<template>
  <div class="a2b-page">
    <PageMetricBar :metrics="summaryMetrics">
      <template #context>
        <strong class="a2b-brand">A2B 心跳</strong>
        <span class="a2b-chip">
          托盘 → <code>/api/heartbeat</code>
          · {{ status?.stale_seconds ?? 90 }}s 离线
        </span>
      </template>
      <template #end>
        <el-button size="small" :loading="loading" @click="load()">
          刷新
        </el-button>
      </template>
    </PageMetricBar>

    <div class="a2b-mode">
      <PageTabs
        :model-value="mode"
        :options="tabs"
        stretch
        aria-label="机台类型"
        @change="onTab"
      />
    </div>

    <p v-if="hint" class="a2b-banner">{{ hint }}</p>

    <div v-loading="loading" class="a2b-body">
      <section
        v-for="group in groupedMachines"
        :key="group.projectId"
        class="a2b-group"
      >
        <header class="a2b-group__head">
          <h3 class="a2b-group__title">{{ group.projectName }}</h3>
          <span class="a2b-group__count">{{ group.machines.length }} 台</span>
        </header>

        <div
          class="a2b-grid"
          :class="{ 'a2b-grid--appearance': mode === 'appearance' }"
        >
          <article
            v-for="card in group.machines"
            :key="card.key"
            class="machine"
            :class="[`machine--${card.tone}`, { 'machine--dual': mode === 'appearance' }]"
          >
            <div class="machine__head">
              <strong class="machine__name">{{ card.machine }}</strong>
              <span
                v-if="mode === 'appearance'"
                class="machine__ratio"
                :class="{ 'is-full': card.healthy, 'is-bad': !card.healthy }"
              >
                {{ appearanceRatioText(card) }}
              </span>
              <span
                v-else
                class="machine__presence"
                :class="`is-${card.tone}`"
              >
                {{ presenceLabel(card.stations[0]?.presence) }}
              </span>
            </div>

            <!-- 外观：两工站监控灯 -->
            <div v-if="mode === 'appearance'" class="lamps">
              <div
                v-for="slot in card.stations"
                :key="slot.slot_key"
                class="lamp"
                :class="`lamp--${statusTone(slot)}`"
              >
                <span class="lamp__dot" aria-hidden="true" />
                <div class="lamp__body">
                  <span class="lamp__label">{{ stationLabel(slot) }}</span>
                  <strong class="lamp__state">{{ stationStatusText(slot) }}</strong>
                  <span class="lamp__meta">
                    {{ slot.last_seen_at || "尚无心跳" }}
                  </span>
                </div>
              </div>
            </div>

            <!-- 注塑：单机详情 -->
            <template v-else>
              <div class="machine__status">
                <span class="lamp__dot" :class="`is-${card.tone}`" aria-hidden="true" />
                <strong>{{ stationStatusText(card.stations[0]) }}</strong>
              </div>
              <dl class="machine__meta">
                <div>
                  <dt>最近心跳</dt>
                  <dd>{{ card.stations[0]?.last_seen_at || "—" }}</dd>
                </div>
                <div>
                  <dt>成功 / 失败</dt>
                  <dd>
                    {{ card.stations[0]?.ok_count ?? 0 }} /
                    {{ card.stations[0]?.fail_count ?? 0 }}
                  </dd>
                </div>
                <div>
                  <dt>源</dt>
                  <dd :title="card.stations[0]?.source">
                    {{ shortPath(card.stations[0]?.source || "") }}
                  </dd>
                </div>
                <div>
                  <dt>目标</dt>
                  <dd :title="card.stations[0]?.target">
                    {{ shortPath(card.stations[0]?.target || "") }}
                  </dd>
                </div>
                <div>
                  <dt>主机</dt>
                  <dd>
                    {{ card.stations[0]?.host_name || "—" }}
                    <template v-if="card.stations[0]?.client_version">
                      · {{ card.stations[0].client_version }}
                    </template>
                  </dd>
                </div>
              </dl>
            </template>
          </article>
        </div>
      </section>

      <div
        v-if="!groupedMachines.length && !unregistered.length && !hint"
        class="a2b-empty"
      >
        {{
          mode === "mold"
            ? "暂无注塑机槽位：请在项目管理中为启用项目配置注塑机"
            : "暂无外观机槽位：请在项目管理中为启用项目配置外观机"
        }}
      </div>

      <section v-if="unregistered.length" class="a2b-group a2b-group--unreg">
        <header class="a2b-group__head">
          <h3 class="a2b-group__title">未登记</h3>
          <span class="a2b-group__count">{{ unregistered.length }}</span>
        </header>
        <p class="a2b-group__hint">有心跳上报，但不在当前项目配置中</p>
        <div class="a2b-grid">
          <article
            v-for="slot in unregistered"
            :key="slot.slot_key"
            class="machine machine--unreg"
            :class="`machine--${statusTone(slot)}`"
          >
            <div class="machine__head">
              <strong class="machine__name">{{ slot.title }}</strong>
              <span class="machine__presence" :class="`is-${statusTone(slot)}`">
                {{ presenceLabel(slot.presence) }}
              </span>
            </div>
            <div class="machine__status">
              <span
                class="lamp__dot"
                :class="`is-${statusTone(slot)}`"
                aria-hidden="true"
              />
              <strong>{{ slot.client_status || "—" }}</strong>
            </div>
            <dl class="machine__meta">
              <div>
                <dt>项目 / 机台</dt>
                <dd>
                  {{ slot.project_name || "—" }} · {{ slot.machine || "—" }}
                  <template v-if="slot.station"> · 工站{{ slot.station }}</template>
                </dd>
              </div>
              <div>
                <dt>最近心跳</dt>
                <dd>{{ slot.last_seen_at || "—" }}</dd>
              </div>
              <div>
                <dt>主机</dt>
                <dd>
                  {{ slot.host_name || "—" }}
                  <template v-if="slot.client_version">
                    · {{ slot.client_version }}
                  </template>
                </dd>
              </div>
            </dl>
          </article>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.a2b-page {
  display: flex;
  flex-direction: column;
  gap: var(--la-space-lg);
  box-sizing: border-box;
  min-height: calc(100vh - var(--la-chrome-total, 84px));
  margin: 0;
  padding: 10px 12px 20px;
  background: color-mix(in srgb, var(--la-surface-sunken, #f2f4f7) 70%, var(--la-surface-page, #f7f8fa));
}

.a2b-page :deep(.page-metric-bar) {
  background: var(--la-surface-card, #fff);
  border-color: var(--la-border-default, #d0d5dd);
}

.a2b-brand {
  font-size: var(--la-text-md, 14px);
  font-weight: 700;
  color: var(--la-text-strong, #1f2733);
  letter-spacing: -0.02em;
}

.a2b-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: var(--la-text-2xs, 11px);
  color: var(--la-text-muted, #667085);
  background: var(--la-surface-sunken, #f2f4f7);
}

.a2b-chip code {
  font-size: 10px;
  padding: 0 3px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--la-text-muted, #667085) 12%, transparent);
}

.a2b-mode {
  width: 100%;
}

.a2b-mode :deep(.page-tabs) {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  width: 100%;
  padding: 5px;
  background: var(--la-surface-card, #fff);
  border: 1px solid var(--la-border-default, #e3e6ec);
  border-radius: 12px;
  box-shadow: 0 1px 2px rgb(16 24 40 / 4%);
}

.a2b-mode :deep(.page-tabs__item) {
  align-items: flex-start;
  min-height: 56px;
  padding: 10px 14px;
  border-radius: 9px;
  color: var(--la-text-muted, #667085);
  transition:
    color 160ms ease,
    background 160ms ease,
    border-color 160ms ease,
    box-shadow 160ms ease,
    transform 160ms ease;
}

.a2b-mode :deep(.page-tabs__item:hover:not(:disabled):not(.is-active)) {
  color: var(--la-text-body, #364152);
  background: var(--la-surface-sunken, #f2f4f7);
}

.a2b-mode :deep(.page-tabs__item.is-active) {
  color: var(--la-text-strong, #1f2733);
  background: color-mix(in srgb, var(--el-color-primary) 8%, var(--la-surface-card, #fff));
  border-color: color-mix(in srgb, var(--el-color-primary) 28%, transparent);
  box-shadow:
    0 1px 2px rgb(16 24 40 / 6%),
    inset 0 0 0 1px color-mix(in srgb, var(--el-color-primary) 10%, transparent);
}

.a2b-mode :deep(.page-tabs__item.is-active .page-tabs__label) {
  color: var(--el-color-primary);
  font-weight: 700;
  letter-spacing: -0.02em;
}

.a2b-mode :deep(.page-tabs__row) {
  width: 100%;
  height: auto;
  min-height: 20px;
  justify-content: space-between;
}

.a2b-mode :deep(.page-tabs__label) {
  height: auto;
  font-size: 14px;
  line-height: 1.25;
}

.a2b-mode :deep(.page-tabs__hint) {
  margin-top: 2px;
  color: var(--la-text-faint, #98a2b3);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.a2b-mode :deep(.page-tabs__item.is-active .page-tabs__hint) {
  color: color-mix(in srgb, var(--el-color-primary) 55%, var(--la-text-muted, #667085));
}

.a2b-mode :deep(.page-tabs__status) {
  height: 18px;
  padding: 0 7px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.a2b-mode :deep(.page-tabs__status.is-ok) {
  color: var(--el-color-success);
  background: color-mix(in srgb, var(--el-color-success) 12%, transparent);
}

.a2b-mode :deep(.page-tabs__status.is-bad) {
  color: var(--el-color-danger);
  background: color-mix(in srgb, var(--el-color-danger) 12%, transparent);
}

.a2b-banner {
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: var(--la-text-sm, 13px);
  color: var(--el-color-warning-dark-2, #b54708);
  background: color-mix(in srgb, var(--el-color-warning) 12%, var(--la-surface-card, #fff));
  border: 1px solid color-mix(in srgb, var(--el-color-warning) 28%, transparent);
}

.a2b-body {
  min-height: 160px;
}

.a2b-group + .a2b-group {
  margin-top: var(--la-space-2xl, 20px);
}

.a2b-group__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
}

.a2b-group__title {
  margin: 0;
  font-size: var(--la-text-md, 14px);
  font-weight: 700;
  color: var(--la-text-strong, #1f2733);
  letter-spacing: -0.02em;
}

.a2b-group__count {
  font-size: var(--la-text-2xs, 11px);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--la-text-muted, #667085);
}

.a2b-group__hint {
  margin: -4px 0 10px;
  font-size: var(--la-text-xs, 12px);
  color: var(--la-text-muted, #667085);
}

.a2b-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}

.a2b-grid--appearance {
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
}

.machine {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 14px 12px;
  border-radius: 12px;
  border: 1px solid var(--la-border-default, #d0d5dd);
  background: var(--la-surface-card, #fff);
  box-shadow: 0 1px 2px rgb(16 24 40 / 4%);
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.machine:hover {
  border-color: color-mix(in srgb, var(--el-color-primary) 28%, var(--la-border-default, #d0d5dd));
  box-shadow: 0 6px 18px rgb(16 24 40 / 7%);
}

.machine--ok {
  --machine-accent: var(--el-color-success);
}

.machine--sync {
  --machine-accent: var(--el-color-primary);
}

.machine--warn {
  --machine-accent: var(--el-color-warning);
}

.machine--off {
  --machine-accent: var(--el-color-danger);
}

.machine--never {
  --machine-accent: var(--la-text-faint, #98a2b3);
}

.machine--unreg {
  background: color-mix(in srgb, var(--el-color-warning) 5%, var(--la-surface-card, #fff));
}

.machine__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.machine__name {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--la-text-strong, #1f2733);
}

.machine__ratio,
.machine__presence {
  flex: none;
  font-size: 11px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  color: var(--la-text-muted, #667085);
}

.machine__ratio.is-full {
  color: var(--el-color-success);
}

.machine__ratio.is-bad {
  color: var(--el-color-danger);
}

.machine__presence.is-ok,
.machine__presence.is-sync {
  color: var(--el-color-success);
}

.machine__presence.is-warn {
  color: var(--el-color-warning);
}

.machine__presence.is-off {
  color: var(--el-color-danger);
}

.machine__status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--la-text-body, #364152);
}

.machine__status strong {
  font-weight: 650;
}

.machine__meta {
  margin: 0;
  display: grid;
  gap: 5px;
}

.machine__meta > div {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 6px;
  font-size: 11px;
  line-height: 1.35;
}

.machine__meta dt {
  margin: 0;
  color: var(--la-text-muted, #667085);
}

.machine__meta dd {
  margin: 0;
  overflow: hidden;
  color: var(--la-text-body, #364152);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* —— 外观双工站灯 —— */
.lamps {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.lamp {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  min-height: 72px;
  padding: 10px;
  border-radius: 10px;
  background: var(--la-surface-sunken, #f2f4f7);
  border: 1px solid transparent;
}

.lamp--ok {
  --lamp-color: var(--el-color-success);
  background: color-mix(in srgb, var(--el-color-success) 9%, var(--la-surface-card, #fff));
  border-color: color-mix(in srgb, var(--el-color-success) 22%, transparent);
}

.lamp--sync {
  --lamp-color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary) 8%, var(--la-surface-card, #fff));
  border-color: color-mix(in srgb, var(--el-color-primary) 22%, transparent);
}

.lamp--warn {
  --lamp-color: var(--el-color-warning);
  background: color-mix(in srgb, var(--el-color-warning) 10%, var(--la-surface-card, #fff));
  border-color: color-mix(in srgb, var(--el-color-warning) 28%, transparent);
}

.lamp--off {
  --lamp-color: var(--el-color-danger);
  background: color-mix(in srgb, var(--el-color-danger) 8%, var(--la-surface-card, #fff));
  border-color: color-mix(in srgb, var(--el-color-danger) 22%, transparent);
}

.lamp--never {
  --lamp-color: var(--la-text-faint, #98a2b3);
}

.lamp__dot {
  flex: none;
  width: 12px;
  height: 12px;
  margin-top: 3px;
  border-radius: 50%;
  background: var(--lamp-color, var(--la-text-faint, #98a2b3));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--lamp-color, #98a2b3) 22%, transparent);
}

.lamp__dot.is-ok,
.lamp__dot.is-sync {
  --lamp-color: var(--el-color-success);
  background: var(--lamp-color);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--lamp-color) 22%, transparent);
}

.lamp__dot.is-warn {
  --lamp-color: var(--el-color-warning);
  background: var(--lamp-color);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--lamp-color) 22%, transparent);
}

.lamp__dot.is-off {
  --lamp-color: var(--el-color-danger);
  background: var(--lamp-color);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--lamp-color) 22%, transparent);
}

.lamp__dot.is-never {
  --lamp-color: var(--la-text-faint, #98a2b3);
  background: var(--lamp-color);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--lamp-color) 18%, transparent);
}

.lamp--ok .lamp__dot,
.lamp--sync .lamp__dot {
  animation: a2b-pulse 2.2s ease-out infinite;
}

.lamp__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.lamp__label {
  font-size: 11px;
  font-weight: 600;
  color: var(--la-text-muted, #667085);
}

.lamp__state {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--la-text-strong, #1f2733);
}

.lamp__meta {
  overflow: hidden;
  font-size: 10px;
  color: var(--la-text-faint, #98a2b3);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.a2b-empty {
  padding: 40px 16px;
  text-align: center;
  font-size: var(--la-text-sm, 13px);
  color: var(--la-text-muted, #667085);
  border: 1px dashed var(--la-border-default, #d0d5dd);
  border-radius: 12px;
  background: var(--la-surface-card, #fff);
}

@keyframes a2b-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--lamp-color) 22%, transparent);
  }
  50% {
    box-shadow: 0 0 0 6px color-mix(in srgb, var(--lamp-color) 8%, transparent);
  }
}

@media (max-width: 720px) {
  .lamps {
    grid-template-columns: 1fr;
  }

  .a2b-grid,
  .a2b-grid--appearance {
    grid-template-columns: 1fr;
  }
}
</style>
