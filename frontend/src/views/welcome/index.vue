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
  eyebrow?: string;
  person?: string;
  lines?: string[];
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
let noticeTimer: number | null = null;
let summaryTimer: number | null = null;
let loadAbort: AbortController | null = null;
let summaryAbort: AbortController | null = null;

const currentBroadcast = computed(() => {
  const list = broadcast.value;
  if (!list.length) {
    return {
      kind: "idle" as const,
      text: "近 3 小时暂无待播报通知",
      path: "/defect/analysis",
      eyebrow: "值守空闲",
      person: "",
      lines: ["近 3 小时暂无待播报通知"]
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
  // 人员层级：一人一条；机台各占一行
  for (const item of notices) {
    const person = `通知 ${item.name}${item.phone ? ` ${item.phone}` : ""}`;
    const machineLines: string[] = [];
    for (const m of item.machines) {
      const name = m.project_name
        ? `${m.project_name} ${m.machine}`
        : m.machine;
      machineLines.push(
        `${name} · 不良率 ${rateText(m.rate_pct)}（产量 ${Number(
          m.qty || 0
        ).toLocaleString()}）`
      );
    }
    if (!machineLines.length) machineLines.push("暂无机台明细");
    const eyebrow = `【良率预警】${dutyName || "当前班次"} ${when}`;
    items.push({
      kind: "alert",
      eyebrow,
      person,
      lines: machineLines,
      text: [eyebrow, person, ...machineLines].join("\n"),
      path: "/defect/analysis"
    });
  }
  // 未排到人：仍按机台各一条
  const seen = new Set<string>();
  for (const row of alerts) {
    if (row.contacts.length) continue;
    const key = `${row.project_id || ""}:${row.machine}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const name = row.project_name
      ? `${row.project_name} ${row.machine}`
      : row.machine;
    const eyebrow = `【未排班】${dutyName || "当前班次"} ${when}`;
    const machineLine = `${name} · 不良率 ${rateText(
      row.machine_rate_pct ?? row.rate_pct
    )}`;
    items.push({
      kind: "alert",
      eyebrow,
      person: "未排到人",
      lines: [machineLine],
      text: [eyebrow, machineLine, "未排到人"].join("\n"),
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
    const eyebrow = `【人工通知】${item.topic || "部门沟通"}`;
    const person = [
      item.from_dept ? `来自 ${item.from_dept}` : "",
      people ? `→ ${people}` : ""
    ]
      .filter(Boolean)
      .join(" ");
    const body = String(item.body || "").trim();
    return {
      kind: "manual" as const,
      eyebrow,
      person,
      lines: body ? [body] : [],
      text: `【人工通知】${item.topic || "部门沟通"}${
        item.from_dept ? ` · ${item.from_dept}` : ""
      }${people ? ` → ${people}` : ""}${body ? ` · ${body}` : ""}`,
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

async function loadSummaries() {
  summaryAbort?.abort();
  summaryAbort = new AbortController();
  const signal = summaryAbort.signal;
  try {
    await Promise.all([
      loadCavitySummaries(signal),
      loadScanSummaries(signal)
    ]);
  } catch (error) {
    hint.value = backendErrorHint(error);
  }
}

async function load() {
  loadAbort?.abort();
  loadAbort = new AbortController();
  const signal = loadAbort.signal;
  loading.value = true;
  hint.value = "";
  try {
    await loadNotices(signal);
    await loadSummaries();
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
  // 时钟 30s 即可；通知 60s；交叉表摘要 5 分钟（避免每分钟打满查询）
  clockTimer = window.setInterval(tickClock, 30_000);
  rotateTimer = window.setInterval(() => {
    if (broadcast.value.length <= 1) return;
    activeIdx.value = (activeIdx.value + 1) % broadcast.value.length;
  }, 5000);
  noticeTimer = window.setInterval(() => {
    void loadNotices();
  }, 60_000);
  summaryTimer = window.setInterval(() => {
    void loadSummaries();
  }, 300_000);
  void load();
});

onUnmounted(() => {
  if (clockTimer != null) window.clearInterval(clockTimer);
  if (rotateTimer != null) window.clearInterval(rotateTimer);
  if (noticeTimer != null) window.clearInterval(noticeTimer);
  if (summaryTimer != null) window.clearInterval(summaryTimer);
  loadAbort?.abort();
  summaryAbort?.abort();
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
        <span class="home-board__label">通知播报</span>
        <span class="home-board__meta-line">
          {{ duty || "—" }}
          <i aria-hidden="true">·</i>
          {{ windowLabel }}
          <i aria-hidden="true">·</i>
          预警 {{ alertCount }}
          <i aria-hidden="true">·</i>
          人工 {{ manualCount }}
        </span>
        <time>{{ nowText }}</time>
      </div>

      <div :key="`${currentBroadcast.kind}-${activeIdx}`" class="home-board__body">
        <p v-if="currentBroadcast.person" class="home-board__person">
          {{ currentBroadcast.person }}
        </p>
        <ul
          v-if="currentBroadcast.lines?.length"
          class="home-board__lines"
        >
          <li v-for="(line, i) in currentBroadcast.lines" :key="i">
            {{ line }}
          </li>
        </ul>
        <p v-else class="home-board__fallback">
          {{ currentBroadcast.text }}
        </p>
      </div>

      <div class="home-board__foot">
        <div v-if="broadcast.length > 1" class="home-board__dots">
          <i
            v-for="(_, i) in broadcast"
            :key="i"
            :class="{ 'is-on': i === activeIdx % broadcast.length }"
          />
        </div>
        <span class="home-board__hint">详情</span>
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
          交叉表
        </button>
      </header>
      <div v-if="cavityRows.length" class="home-cards">
        <article v-for="row in cavityRows" :key="row.project_id" class="home-card">
          <div class="home-card__head">
            <h3>{{ row.display_name }}</h3>
            <strong class="home-card__rate">{{
              formatRate(row.ratePct) || "—"
            }}</strong>
          </div>
          <p class="home-card__stats">
            产量 {{ formatQty(row.qty) }}
            <i aria-hidden="true">·</i>
            不良 {{ formatQty(row.ng) }}
            <i aria-hidden="true">·</i>
            机台 {{ row.machines }}
          </p>
          <p v-if="row.top.length" class="home-top">
            <span class="home-top__label">偏高</span>
            <template v-for="(item, idx) in row.top" :key="item.name">
              <span v-if="idx" class="home-top__sep">·</span>
              <span class="home-top__item"
                >{{ item.name }} {{ formatRate(item.ratePct) || "—" }}</span
              >
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
          交叉表
        </button>
      </header>
      <div v-if="scanRows.length" class="home-cards">
        <article v-for="row in scanRows" :key="row.project_id" class="home-card">
          <div class="home-card__head">
            <h3>{{ row.display_name }}</h3>
            <strong class="home-card__rate">{{
              formatRate(row.ratePct) || "—"
            }}</strong>
          </div>
          <p class="home-card__stats">
            产量 {{ formatQty(row.qty) }}
            <i aria-hidden="true">·</i>
            次品 {{ formatQty(row.ng) }}
            <i aria-hidden="true">·</i>
            机台 {{ row.machines }}
          </p>
          <p v-if="row.top.length" class="home-top">
            <span class="home-top__label">偏高</span>
            <template v-for="(item, idx) in row.top" :key="item.name">
              <span v-if="idx" class="home-top__sep">·</span>
              <span class="home-top__item"
                >{{ item.name }} {{ formatRate(item.ratePct) || "—" }}</span
              >
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
  --home-ink: #15233a;
  --home-mute: #5c6b7a;
  --home-paper: #f4f6f8;
  --home-card: #ffffff;
  --home-rate: #b42318;
  box-sizing: border-box;
  min-height: calc(100vh - var(--la-chrome-total) - var(--la-content-inset) * 2);
  padding: var(--la-space-xl) var(--la-space-2xl) var(--la-space-3xl);
  color: var(--home-ink);
  background: var(--home-paper);
}

.home-board {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 140px;
  margin-bottom: var(--la-space-xl);
  padding: var(--la-space-xl) var(--la-space-2xl) var(--la-space-lg);
  cursor: pointer;
  color: #f7f8fa;
  background: var(--home-ink);
  border-radius: 4px;
  transition: background 180ms ease;
}

.home-board:hover {
  background: #1a2c46;
}

.home-board.is-alert {
  background: #6b1d1d;
}

.home-board.is-alert:hover {
  background: #7a2424;
}

.home-board.is-manual {
  background: #16384f;
}

.home-board.is-manual:hover {
  background: #1c4560;
}

.home-board.is-idle {
  background: #3a4450;
}

.home-board.is-idle:hover {
  background: #45515e;
}

.home-board__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px 16px;
  font-size: 13px;
  color: rgb(247 248 250 / 72%);
  font-variant-numeric: tabular-nums;
}

.home-board__label {
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgb(247 248 250 / 88%);
}

.home-board__meta-line {
  flex: 1 1 auto;
  min-width: 0;
}

.home-board__meta-line i,
.home-card__stats i {
  margin: 0 0.35em;
  font-style: normal;
  opacity: 0.55;
}

.home-board__meta time {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  color: rgb(247 248 250 / 58%);
}

.home-board__body {
  animation: home-board-in 320ms cubic-bezier(0.22, 1, 0.36, 1);
}

.home-board__person {
  margin: 0 0 8px;
  font-size: var(--la-text-2xl);
  font-weight: 650;
  letter-spacing: -0.03em;
  line-height: 1.2;
}

.home-board__lines {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.home-board__lines li {
  font-size: 17px;
  font-weight: 500;
  line-height: 1.45;
  font-variant-numeric: tabular-nums;
  color: rgb(247 248 250 / 94%);
}

.home-board__fallback {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.4;
}

.home-board__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: auto;
  padding-top: 4px;
  border-top: 1px solid rgb(247 248 250 / 12%);
}

.home-board__dots {
  display: flex;
  gap: 8px;
}

.home-board__dots i {
  width: 18px;
  height: 2px;
  background: rgb(247 248 250 / 28%);
  transition: background 160ms ease;
}

.home-board__dots i.is-on {
  background: #f7f8fa;
}

.home-board__hint {
  margin-left: auto;
  font-size: 12px;
  letter-spacing: 0.08em;
  color: rgb(247 248 250 / 48%);
}

.home-board:focus-visible {
  outline: 2px solid #f7f8fa;
  outline-offset: 3px;
}

@keyframes home-board-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.home-hint {
  margin-bottom: 16px;
}

.home-block + .home-block {
  margin-top: 28px;
}

.home-block__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid #dde3e8;
}

.home-block__head h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
  letter-spacing: -0.03em;
  color: var(--home-ink);
}

.home-block__head p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--home-mute);
  font-variant-numeric: tabular-nums;
}

.home-more {
  padding: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--home-ink);
  background: transparent;
  border: 0;
  border-bottom: 1px solid transparent;
  cursor: pointer;
  transition: border-color 160ms ease;
}

.home-more:hover {
  border-bottom-color: var(--home-ink);
}

.home-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.home-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 18px 18px 16px;
  background: var(--home-card);
  border: 1px solid #dde3e8;
  border-radius: 4px;
  transition: border-color 160ms ease;
}

.home-card:hover {
  border-color: #b8c2cc;
}

.home-card__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.home-card h3 {
  margin: 0;
  min-width: 0;
  overflow: hidden;
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.02em;
  color: var(--home-ink);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-card__rate {
  flex: none;
  font-size: 28px;
  font-weight: 650;
  letter-spacing: -0.04em;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  color: var(--home-rate);
}

.home-card__stats {
  margin: 0;
  font-size: 12px;
  color: var(--home-mute);
  font-variant-numeric: tabular-nums;
}

.home-top {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 6px;
  margin: 0;
  padding-top: 10px;
  border-top: 1px solid #edf1f4;
  font-size: 12px;
  line-height: 1.4;
  color: var(--home-ink);
  font-variant-numeric: tabular-nums;
}

.home-top__label {
  font-weight: 650;
  color: var(--home-mute);
}

.home-top__sep {
  color: #a8b3bd;
}

.home-top__item {
  color: var(--home-ink);
}

.home-top.is-muted {
  color: var(--home-mute);
}

.home-empty {
  margin: 0;
  padding: 28px 12px;
  font-size: 13px;
  color: var(--home-mute);
  text-align: center;
  background: transparent;
  border: 1px dashed #cfd7de;
  border-radius: 4px;
}

@media (max-width: 1400px) {
  .home-cards {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 1100px) {
  .home-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .home {
    padding: 18px 16px 28px;
  }

  .home-board {
    padding: 22px 20px 18px;
  }

  .home-cards {
    grid-template-columns: 1fr 1fr;
  }

  .home-board__person {
    font-size: 22px;
  }

  .home-board__lines li {
    font-size: 15px;
  }

  .home-board__meta time {
    margin-left: 0;
    width: 100%;
  }
}

@media (max-width: 640px) {
  .home-cards {
    grid-template-columns: 1fr;
  }

  .home-card__rate {
    font-size: 24px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .home-board,
  .home-card,
  .home-board__body,
  .home-board__dots i {
    transition: none;
    animation: none;
  }
}
</style>
