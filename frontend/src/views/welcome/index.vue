<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  getYieldAlerts,
  listManualNotices,
  type ManualNotice,
  type YieldAlertRow,
  type YieldNotice
} from "@/api/modules/defect";
import {
  getMachineCavityRates,
  getQueryCatalog,
  type MachineCavityRow
} from "@/api/modules/exception";
import {
  getDefectAnalysis,
  getScanBootstrap,
  type DefectAnalysisRow,
  type ScanProject
} from "@/api/modules/scan";
import { backendErrorHint } from "@/api/http";
import { formatQty, formatRate, rateOf } from "@/utils/pivotTable";

defineOptions({
  name: "Welcome"
});

type BroadcastItem = {
  kind: "alert" | "manual" | "idle";
  text: string;
  path: string;
};

type ProjectSummary = {
  project_id: string;
  display_name: string;
  qty: number;
  ng: number;
  machines: number;
  ratePct: number | null;
  fromHour: string;
  toHour: string;
  top: { name: string; ratePct: number | null; ng: number }[];
};

const router = useRouter();
const loading = ref(false);
const hint = ref("");
const nowText = ref("");
const duty = ref("");
const windowLabel = ref("近 3 小时");
const broadcast = ref<BroadcastItem[]>([]);
const activeIdx = ref(0);
const cavityRows = ref<ProjectSummary[]>([]);
const scanRows = ref<ProjectSummary[]>([]);
const cavityWindow = ref("近 3 小时");
const scanWindow = ref("近 12 小时");

let clockTimer: number | null = null;
let rotateTimer: number | null = null;
let pollTimer: number | null = null;
let loadAbort: AbortController | null = null;

const currentBroadcast = computed(() => {
  const list = broadcast.value;
  if (!list.length) {
    return {
      kind: "idle" as const,
      text: "近 3 小时暂无待播报通知",
      path: "/defect/analysis"
    };
  }
  return list[activeIdx.value % list.length];
});

const alertCount = computed(
  () => broadcast.value.filter(i => i.kind === "alert").length
);
const manualCount = computed(
  () => broadcast.value.filter(i => i.kind === "manual").length
);

const boardTone = computed(() => {
  if (currentBroadcast.value.kind === "alert") return "is-alert";
  if (currentBroadcast.value.kind === "manual") return "is-manual";
  return "is-idle";
});

function tickClock() {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  nowText.value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(
    d.getDate()
  )} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function rateText(value: number | null | undefined) {
  return value == null ? "—" : `${Number(value).toFixed(2)}%`;
}

function fmtWindow(fromHour: string, toHour: string, fallback: string) {
  if (fromHour && toHour && fromHour !== toHour) return `${fromHour} ~ ${toHour}`;
  return fromHour || toHour || fallback;
}

function summarizeMachineRows(
  projectId: string,
  displayName: string,
  rows: MachineCavityRow[] | DefectAnalysisRow[],
  fromHour: string,
  toHour: string
): ProjectSummary {
  let qty = 0;
  let ng = 0;
  const byMachine = new Map<string, { qty: number; ng: number }>();
  for (const row of rows) {
    const machine = String(
      ("machine" in row ? row.machine : "") || ""
    ).trim();
    const q = Number(row.qty || 0);
    const n = Number(row.ng || 0);
    qty += q;
    ng += n;
    if (!machine) continue;
    const prev = byMachine.get(machine) || { qty: 0, ng: 0 };
    prev.qty += q;
    prev.ng += n;
    byMachine.set(machine, prev);
  }
  const top = [...byMachine.entries()]
    .map(([name, v]) => ({
      name,
      ng: v.ng,
      ratePct: rateOf(v.qty, v.ng)
    }))
    .filter(item => item.ng > 0)
    .sort((a, b) => (b.ratePct ?? -1) - (a.ratePct ?? -1))
    .slice(0, 3);
  return {
    project_id: projectId,
    display_name: displayName,
    qty,
    ng,
    machines: byMachine.size,
    ratePct: rateOf(qty, ng),
    fromHour,
    toHour,
    top
  };
}

function mapYieldBroadcast(
  notices: YieldNotice[],
  alerts: YieldAlertRow[],
  dutyName: string,
  when: string
): BroadcastItem[] {
  const items: BroadcastItem[] = [];
  for (const item of notices) {
    const machines = item.machines
      .map(m =>
        m.project_name ? `${m.project_name} ${m.machine}` : m.machine
      )
      .filter(Boolean);
    const rates = item.machines
      .map(m => rateText(m.rate_pct))
      .filter(r => r !== "—");
    items.push({
      kind: "alert",
      text: `【良率预警】${dutyName || "当前班次"} ${when} · 通知 ${item.name}${
        item.phone ? ` ${item.phone}` : ""
      } · ${machines.join("、") || "机台"}${
        rates.length ? ` · 不良率 ${rates.join(" / ")}` : ""
      }`,
      path: "/defect/analysis"
    });
  }
  const seen = new Set<string>();
  for (const row of alerts) {
    if (row.contacts.length) continue;
    const key = `${row.project_id || ""}:${row.machine}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const name = row.project_name
      ? `${row.project_name} ${row.machine}`
      : row.machine;
    items.push({
      kind: "alert",
      text: `【未排班】${dutyName || "当前班次"} ${when} · ${name} 不良率 ${rateText(
        row.machine_rate_pct ?? row.rate_pct
      )}，未排到人`,
      path: "/defect/analysis"
    });
  }
  return items;
}

function mapManualBroadcast(items: ManualNotice[]): BroadcastItem[] {
  return items.slice(0, 12).map(item => {
    const people = item.recipients
      .map(r => r.name || r.department)
      .filter(Boolean)
      .join("、");
    return {
      kind: "manual" as const,
      text: `【人工通知】${item.topic || "部门沟通"}${
        item.from_dept ? ` · ${item.from_dept}` : ""
      }${people ? ` → ${people}` : ""}${item.body ? ` · ${item.body}` : ""}`,
      path: "/defect/manual"
    };
  });
}

async function loadNotices(signal?: AbortSignal) {
  const [yieldRes, manualRes] = await Promise.allSettled([
    getYieldAlerts({ hours: 3 }, signal),
    listManualNotices(signal)
  ]);
  const yieldData =
    yieldRes.status === "fulfilled" ? yieldRes.value?.data : null;
  const manuals =
    manualRes.status === "fulfilled"
      ? manualRes.value?.data?.notices || []
      : [];
  duty.value = yieldData?.duty || "";
  windowLabel.value = fmtWindow(
    yieldData?.from_hour || "",
    yieldData?.to_hour || "",
    "近 3 小时"
  );
  const next = [
    ...mapYieldBroadcast(
      yieldData?.notices || [],
      yieldData?.alerts || [],
      yieldData?.duty || "",
      windowLabel.value
    ),
    ...mapManualBroadcast(manuals)
  ];
  broadcast.value = next;
  if (activeIdx.value >= next.length) activeIdx.value = 0;
}

async function loadCavitySummaries(signal?: AbortSignal) {
  const catalog = await getQueryCatalog(undefined, {}, signal).catch(() => null);
  const projects = catalog?.data?.projects || [];
  if (!projects.length) {
    cavityRows.value = [];
    return;
  }
  const results = await Promise.all(
    projects.map(async p => {
      try {
        const res = await getMachineCavityRates(
          p.project_id,
          3,
          "appearance",
          signal
        );
        const data = res?.data;
        return summarizeMachineRows(
          p.project_id,
          p.display_name,
          data?.rows || [],
          data?.from_hour || "",
          data?.to_hour || ""
        );
      } catch {
        return summarizeMachineRows(p.project_id, p.display_name, [], "", "");
      }
    })
  );
  cavityRows.value = results;
  const first = results[0];
  if (first) {
    cavityWindow.value = fmtWindow(first.fromHour, first.toHour, "近 3 小时");
  }
}

async function loadScanSummaries(signal?: AbortSignal) {
  const boot = await getScanBootstrap(undefined, signal).catch(() => null);
  const projects: ScanProject[] = boot?.data?.projects || [];
  if (!projects.length) {
    scanRows.value = [];
    return;
  }
  const results = await Promise.all(
    projects.map(async p => {
      try {
        const res = await getDefectAnalysis(
          { project_id: p.project_id, hours: 12 },
          signal
        );
        const data = res?.data;
        return summarizeMachineRows(
          p.project_id,
          p.display_name,
          data?.machines || [],
          data?.from_hour || "",
          data?.to_hour || ""
        );
      } catch {
        return summarizeMachineRows(p.project_id, p.display_name, [], "", "");
      }
    })
  );
  scanRows.value = results;
  const first = results[0];
  if (first) {
    scanWindow.value = fmtWindow(first.fromHour, first.toHour, "近 12 小时");
  }
}

async function load() {
  loadAbort?.abort();
  loadAbort = new AbortController();
  const signal = loadAbort.signal;
  loading.value = true;
  hint.value = "";
  try {
    await Promise.all([
      loadNotices(signal),
      loadCavitySummaries(signal),
      loadScanSummaries(signal)
    ]);
  } catch (error) {
    hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

function openBroadcast() {
  router.push(currentBroadcast.value.path);
}

function goCavity() {
  router.push("/exception/cavity");
}

function goScan() {
  router.push("/scan/analysis");
}

onMounted(() => {
  tickClock();
  clockTimer = window.setInterval(tickClock, 1000);
  rotateTimer = window.setInterval(() => {
    if (broadcast.value.length <= 1) return;
    activeIdx.value = (activeIdx.value + 1) % broadcast.value.length;
  }, 5000);
  pollTimer = window.setInterval(() => {
    void load();
  }, 60_000);
  void load();
});

onUnmounted(() => {
  if (clockTimer != null) window.clearInterval(clockTimer);
  if (rotateTimer != null) window.clearInterval(rotateTimer);
  if (pollTimer != null) window.clearInterval(pollTimer);
  loadAbort?.abort();
});
</script>

<template>
  <div class="home main-content" v-loading="loading">
    <section
      class="home-board"
      :class="boardTone"
      role="button"
      tabindex="0"
      @click="openBroadcast"
      @keydown.enter="openBroadcast"
    >
      <div class="home-board__meta">
        <strong>通知播报</strong>
        <span>{{ duty || "—" }} · {{ windowLabel }}</span>
        <span class="home-board__counts">
          预警 {{ alertCount }} · 人工 {{ manualCount }}
        </span>
        <time>{{ nowText }}</time>
      </div>
      <p class="home-board__text">{{ currentBroadcast.text }}</p>
      <div v-if="broadcast.length > 1" class="home-board__dots">
        <i
          v-for="(_, i) in broadcast"
          :key="i"
          :class="{ 'is-on': i === activeIdx % broadcast.length }"
        />
      </div>
    </section>

    <el-alert
      v-if="hint"
      class="home-hint"
      type="warning"
      :closable="false"
      :title="hint"
    />

    <section class="home-block">
      <header class="home-block__head">
        <div>
          <h2>机台模穴良率</h2>
          <p>自动外观 · {{ cavityWindow }}</p>
        </div>
        <button type="button" class="home-more" @click="goCavity">
          查看交叉表
        </button>
      </header>
      <div v-if="cavityRows.length" class="home-cards">
        <article v-for="row in cavityRows" :key="row.project_id" class="home-card">
          <h3>{{ row.display_name }}</h3>
          <div class="home-metrics">
            <div class="home-metric is-accent">
              <strong>{{ formatRate(row.ratePct) || "—" }}</strong>
              <span>不良率</span>
            </div>
            <div class="home-metric">
              <strong>{{ formatQty(row.qty) }}</strong>
              <span>产量</span>
            </div>
            <div class="home-metric">
              <strong>{{ formatQty(row.ng) }}</strong>
              <span>不良</span>
            </div>
            <div class="home-metric">
              <strong>{{ row.machines }}</strong>
              <span>机台</span>
            </div>
          </div>
          <p v-if="row.top.length" class="home-top">
            偏高
            <template v-for="(item, idx) in row.top" :key="item.name">
              <span v-if="idx"> · </span>
              {{ item.name }} {{ formatRate(item.ratePct) || "—" }}
            </template>
          </p>
          <p v-else class="home-top is-muted">暂无偏高机台</p>
        </article>
      </div>
      <p v-else class="home-empty">暂无项目数据</p>
    </section>

    <section class="home-block">
      <header class="home-block__head">
        <div>
          <h2>扫码次品</h2>
          <p>全部次品 · {{ scanWindow }}</p>
        </div>
        <button type="button" class="home-more" @click="goScan">
          查看交叉表
        </button>
      </header>
      <div v-if="scanRows.length" class="home-cards">
        <article v-for="row in scanRows" :key="row.project_id" class="home-card">
          <h3>{{ row.display_name }}</h3>
          <div class="home-metrics">
            <div class="home-metric is-accent">
              <strong>{{ formatRate(row.ratePct) || "—" }}</strong>
              <span>不良率</span>
            </div>
            <div class="home-metric">
              <strong>{{ formatQty(row.qty) }}</strong>
              <span>产量</span>
            </div>
            <div class="home-metric">
              <strong>{{ formatQty(row.ng) }}</strong>
              <span>次品</span>
            </div>
            <div class="home-metric">
              <strong>{{ row.machines }}</strong>
              <span>机台</span>
            </div>
          </div>
          <p v-if="row.top.length" class="home-top">
            偏高
            <template v-for="(item, idx) in row.top" :key="item.name">
              <span v-if="idx"> · </span>
              {{ item.name }} {{ formatRate(item.ratePct) || "—" }}
            </template>
          </p>
          <p v-else class="home-top is-muted">暂无偏高机台</p>
        </article>
      </div>
      <p v-else class="home-empty">暂无项目数据</p>
    </section>
  </div>
</template>

<style scoped>
.home {
  box-sizing: border-box;
  min-height: calc(100vh - 96px);
  padding: 16px 20px 28px;
  background: color-mix(
    in srgb,
    var(--el-fill-color-light) 55%,
    var(--el-bg-color)
  );
}

.home-board {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 132px;
  margin-bottom: 16px;
  padding: 16px 20px 18px;
  overflow: hidden;
  cursor: pointer;
  color: #fff;
  background: #1e4e79;
  border-radius: var(--la-radius-md, 8px);
  box-shadow: var(--la-shadow-sm, 0 1px 2px rgb(16 24 40 / 6%));
}

.home-board.is-alert {
  background: linear-gradient(135deg, #7f1d1d 0%, #b91c1c 55%, #9a3412 100%);
}

.home-board.is-manual {
  background: linear-gradient(135deg, #1e3a5f 0%, #1e4e79 60%, #0f766e 100%);
}

.home-board.is-idle {
  background: linear-gradient(135deg, #334155 0%, #475569 100%);
}

.home-board__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px 14px;
  font-size: 12px;
  opacity: 0.92;
}

.home-board__meta strong {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.home-board__counts {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.home-board__meta time {
  font-variant-numeric: tabular-nums;
}

.home-board__text {
  margin: 0;
  font-size: 22px;
  font-weight: 650;
  line-height: 1.35;
  letter-spacing: -0.01em;
}

.home-board__dots {
  display: flex;
  gap: 6px;
}

.home-board__dots i {
  width: 6px;
  height: 6px;
  background: rgb(255 255 255 / 35%);
  border-radius: 99px;
}

.home-board__dots i.is-on {
  background: #fff;
}

.home-board:focus-visible {
  outline: 2px solid #fff;
  outline-offset: 2px;
}

.home-hint {
  margin-bottom: 12px;
}

.home-block + .home-block {
  margin-top: 14px;
}

.home-block__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.home-block__head h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.home-block__head p {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.home-more {
  padding: 0;
  font-size: 12px;
  color: var(--el-color-primary);
  background: none;
  border: 0;
  cursor: pointer;
}

.home-more:hover {
  text-decoration: underline;
}

.home-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.home-card {
  padding: 14px 16px 12px;
  background: var(--la-surface-card, var(--el-bg-color));
  border: 1px solid var(--la-border-default, var(--el-border-color-lighter));
  border-radius: var(--la-radius-md, 8px);
}

.home-card h3 {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 650;
  color: var(--el-text-color-primary);
}

.home-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.home-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.home-metric strong {
  font-size: 20px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
  color: var(--el-text-color-primary);
}

.home-metric.is-accent strong {
  color: var(--el-color-danger);
}

.home-metric span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.home-top {
  margin: 12px 0 0;
  padding-top: 10px;
  border-top: 1px solid
    color-mix(in srgb, var(--el-border-color) 50%, transparent);
  font-size: 12px;
  line-height: 1.45;
  color: var(--el-text-color-regular);
  font-variant-numeric: tabular-nums;
}

.home-top.is-muted {
  color: var(--el-text-color-secondary);
}

.home-empty {
  margin: 0;
  padding: 24px 16px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  text-align: center;
  background: var(--la-surface-card, var(--el-bg-color));
  border: 1px solid var(--la-border-default, var(--el-border-color-lighter));
  border-radius: var(--la-radius-md, 8px);
}

@media (max-width: 900px) {
  .home-cards {
    grid-template-columns: 1fr;
  }

  .home-board__text {
    font-size: 18px;
  }

  .home-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
