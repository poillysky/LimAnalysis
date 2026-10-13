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

defineOptions({
  name: "FeatureA2bHeartbeat"
});

type Mode = "mold" | "appearance";

const mode = ref<Mode>("mold");
const loading = ref(false);
const hint = ref("");
const status = ref<A2bHeartbeatStatus | null>(null);
let timer: ReturnType<typeof setInterval> | null = null;

const tabs = [
  { value: "mold", label: "注塑机" },
  { value: "appearance", label: "外观机" }
];

const summary = computed(() => status.value?.summary);
const slots = computed(() => status.value?.slots ?? []);
const unregistered = computed(() => status.value?.unregistered ?? []);

const groupedSlots = computed(() => {
  const map = new Map<string, { projectId: string; projectName: string; items: A2bHeartbeatSlot[] }>();
  for (const slot of slots.value) {
    const key = slot.project_id || "_";
    let group = map.get(key);
    if (!group) {
      group = {
        projectId: slot.project_id,
        projectName: slot.project_name || slot.project_id || "未命名项目",
        items: []
      };
      map.set(key, group);
    }
    group.items.push(slot);
  }
  return [...map.values()];
});

function presenceLabel(p: A2bPresence | string) {
  if (p === "online") return "在线";
  if (p === "offline") return "离线";
  return "从未上报";
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
  if (text.length <= 36) return text;
  return `…${text.slice(-34)}`;
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
    <header class="a2b-head">
      <div>
        <h2 class="a2b-title">A2B 心跳</h2>
        <p class="a2b-sub">
          托盘上报至 API
          <code>/api/heartbeat</code>
          · 超过 {{ status?.stale_seconds ?? 90 }}s 视为离线
        </p>
      </div>
      <el-button :loading="loading" @click="load()">刷新</el-button>
    </header>

    <PageTabs
      :model-value="mode"
      :options="tabs"
      stretch
      aria-label="机台类型"
      @change="onTab"
    />

    <el-alert
      v-if="hint"
      type="warning"
      :closable="false"
      :title="hint"
      show-icon
      class="a2b-alert"
    />

    <div v-if="summary" class="a2b-summary">
      <span class="pill pill--ok">在线 {{ summary.online }}</span>
      <span class="pill pill--off">离线 {{ summary.offline }}</span>
      <span class="pill pill--never">从未 {{ summary.never }}</span>
      <span v-if="summary.unregistered" class="pill pill--warn">
        未登记 {{ summary.unregistered }}
      </span>
      <span class="pill pill--muted">槽位 {{ summary.total_slots }}</span>
    </div>

    <div v-loading="loading" class="a2b-body">
      <section
        v-for="group in groupedSlots"
        :key="group.projectId"
        class="a2b-group"
      >
        <h3 class="a2b-group__title">{{ group.projectName }}</h3>
        <div class="a2b-grid">
          <article
            v-for="slot in group.items"
            :key="slot.slot_key"
            class="card"
            :class="`card--${statusTone(slot)}`"
          >
            <div class="card__top">
              <strong class="card__title">{{ slot.title }}</strong>
              <span class="card__presence">{{ presenceLabel(slot.presence) }}</span>
            </div>
            <div class="card__status">
              {{ slot.client_status || (slot.presence === "never" ? "—" : "未知") }}
              <template v-if="slot.paused"> · 已暂停</template>
            </div>
            <dl class="card__meta">
              <div>
                <dt>最近心跳</dt>
                <dd>{{ slot.last_seen_at || "—" }}</dd>
              </div>
              <div>
                <dt>成功 / 失败</dt>
                <dd>{{ slot.ok_count }} / {{ slot.fail_count }}</dd>
              </div>
              <div>
                <dt>源</dt>
                <dd :title="slot.source">{{ shortPath(slot.source) }}</dd>
              </div>
              <div>
                <dt>目标</dt>
                <dd :title="slot.target">{{ shortPath(slot.target) }}</dd>
              </div>
              <div>
                <dt>主机 / 版本</dt>
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

      <div
        v-if="!groupedSlots.length && !unregistered.length && !hint"
        class="a2b-empty"
      >
        {{
          mode === "mold"
            ? "暂无注塑机槽位：请在项目管理中为启用项目配置注塑机"
            : "暂无外观机槽位：请在项目管理中为启用项目配置外观机"
        }}
      </div>

      <section v-if="unregistered.length" class="a2b-group a2b-group--unreg">
        <h3 class="a2b-group__title">未登记</h3>
        <p class="a2b-group__hint">有心跳上报，但不在当前项目配置中</p>
        <div class="a2b-grid">
          <article
            v-for="slot in unregistered"
            :key="slot.slot_key"
            class="card card--unreg"
            :class="`card--${statusTone(slot)}`"
          >
            <div class="card__top">
              <strong class="card__title">{{ slot.title }}</strong>
              <span class="card__presence">{{ presenceLabel(slot.presence) }}</span>
            </div>
            <div class="card__status">{{ slot.client_status || "—" }}</div>
            <dl class="card__meta">
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
                <dt>主机 / 版本</dt>
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
  gap: 12px;
  padding: 4px 2px 24px;
}

.a2b-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.a2b-title {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
  line-height: 1.3;
}

.a2b-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.a2b-sub code {
  font-size: 11px;
  padding: 0 4px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}

.a2b-alert {
  margin: 0;
}

.a2b-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.pill {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-blank);
}

.pill--ok {
  color: var(--el-color-success);
  border-color: color-mix(in srgb, var(--el-color-success) 35%, transparent);
  background: color-mix(in srgb, var(--el-color-success) 10%, transparent);
}

.pill--off {
  color: var(--el-color-danger);
  border-color: color-mix(in srgb, var(--el-color-danger) 35%, transparent);
  background: color-mix(in srgb, var(--el-color-danger) 8%, transparent);
}

.pill--never {
  color: var(--el-text-color-secondary);
}

.pill--warn {
  color: var(--el-color-warning);
  border-color: color-mix(in srgb, var(--el-color-warning) 40%, transparent);
  background: color-mix(in srgb, var(--el-color-warning) 12%, transparent);
}

.pill--muted {
  color: var(--el-text-color-regular);
}

.a2b-body {
  min-height: 160px;
}

.a2b-group {
  margin-top: 8px;
}

.a2b-group + .a2b-group {
  margin-top: 20px;
}

.a2b-group__title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 650;
}

.a2b-group__hint {
  margin: -4px 0 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.a2b-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
}

.card {
  padding: 12px 12px 10px;
  border-radius: 10px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  border-left-width: 4px;
}

.card--ok {
  border-left-color: var(--el-color-success);
}

.card--sync {
  border-left-color: var(--el-color-primary);
}

.card--warn {
  border-left-color: var(--el-color-warning);
}

.card--off {
  border-left-color: var(--el-color-danger);
}

.card--never {
  border-left-color: var(--el-border-color);
  opacity: 0.92;
}

.card--unreg {
  background: color-mix(in srgb, var(--el-color-warning) 4%, var(--el-bg-color));
}

.card__top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.card__title {
  font-size: 14px;
  font-weight: 650;
}

.card__presence {
  font-size: 11px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.card__status {
  margin-top: 4px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.card__meta {
  margin: 10px 0 0;
  display: grid;
  gap: 6px;
}

.card__meta > div {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 6px;
  font-size: 11px;
  line-height: 1.35;
}

.card__meta dt {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.card__meta dd {
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.a2b-empty {
  padding: 36px 12px;
  text-align: center;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  border: 1px dashed var(--el-border-color);
  border-radius: 10px;
}
</style>
