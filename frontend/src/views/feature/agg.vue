<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  aggOverview,
  ensureAggModel,
  getAggSqlPreview,
  generateAggFormula,
  getAggSourceColumns,
  previewAggData,
  runAgg,
  saveAggConfig,
  saveAggScheduler,
  suggestAggFields,
  waitForAggJob,
  type AggField,
  type AggJob,
  type AggModel,
  type AggProjectRow,
  type AggScheduler
} from "@/api/modules/agg";
import { backendErrorHint } from "@/api/http";
import type { SourceColumn } from "@/api/modules/etl";
import PageTabs from "@/components/PageTabs/index.vue";
import {
  addFieldTo,
  moveFieldBy,
  removeFieldAt,
  statusType
} from "@/composables/useFieldList";

defineOptions({
  name: "FeatureAgg"
});

const loading = ref(false);
const running = ref(false);
const saving = ref(false);
const schedulerSaving = ref(false);
const rows = ref<AggProjectRow[]>([]);
const hint = ref("");
const activeJobId = ref<number | null>(null);
const scheduler = reactive<AggScheduler>({
  is_active: false,
  last_run_time: "",
  last_run_status: "",
  last_run_message: ""
});

const editorOpen = ref(false);
const editorLoading = ref(false);
const model = ref<AggModel | null>(null);
const fields = ref<AggField[]>([]);
const sourceColumns = ref<SourceColumn[]>([]);
const timeField = ref("ServerTime");
const granularity = ref("hour");
const lookbackHours = ref(1);
const backfillHours = ref(12);
const enabled = ref(false);

const previewOpen = ref(false);
const previewLive = ref(false);
const previewCols = ref<string[]>([]);
const previewRows = ref<Record<string, unknown>[]>([]);
const previewMeta = ref("");
const sqlOpen = ref(false);
const sqlText = ref("");

const runBar = reactive({
  visible: false,
  status: "running",
  mode: "增量",
  target: "",
  text: "",
  jobId: 0,
  percent: 20,
  indeterminate: true,
  done: false,
  startedAt: 0
});
const runElapsed = ref("0s");
let runTick: number | null = null;

const enabledCount = computed(
  () => rows.value.filter(r => r.is_model_enabled && r.can_run).length
);
const configuredCount = computed(
  () => rows.value.filter(r => (r.field_count || 0) > 0 && !r.is_draft).length
);
const fieldFilter = ref("");
const categoryFilter = ref("all");
const categoryOptions = [
  { label: "维度", value: "dimension" },
  { label: "度量", value: "measure" },
  { label: "派生", value: "derived" }
];
const categoryFilterTabs = [
  { value: "all", label: "全部" },
  { value: "dimension", label: "维度" },
  { value: "measure", label: "度量" },
  { value: "derived", label: "派生" }
];
const fieldTypeOptions = [
  { value: "text", label: "文本" },
  { value: "integer", label: "整数" },
  { value: "decimal", label: "小数" },
  { value: "percent", label: "百分比" },
  { value: "datetime", label: "时间" },
  { value: "boolean", label: "布尔" }
];
const aggregateOptions = [
  { label: "计数", value: "COUNT" },
  { label: "求和", value: "SUM" },
  { label: "平均", value: "AVG" },
  { label: "最大", value: "MAX" },
  { label: "最小", value: "MIN" },
  { label: "去重计数", value: "COUNT_DISTINCT" }
];
const formulaTemplates = [
  { key: "rate", label: "不良率 = A / B", need: "two" },
  { key: "pct", label: "百分比 = A / B * 100", need: "two" },
  { key: "safe_div", label: "安全除法（分母为0→空）", need: "two" },
  { key: "sum2", label: "两列相加", need: "two" },
  { key: "diff", label: "两列相减 A - B", need: "two" }
] as const;

const formulaAssistVisible = ref(false);
const formulaAssistTab = ref<"ai" | "template">("ai");
const formulaAssistPrompt = ref("");
const formulaAssistLoading = ref(false);
const formulaAssistResult = ref("");
const formulaAssistExplain = ref("");
const formulaAssistError = ref("");
const formulaAssistSource = ref("");
const formulaAssistAiReady = ref(false);
const formulaAssistSuggestLevel = ref(2);
const formulaAssistTarget = ref<AggField | null>(null);
const formulaAssistField = ref("");
const formulaAssistField2 = ref("");
const sourceNames = computed(() =>
  sourceColumns.value.map(c => c.column_name).filter(Boolean)
);
const formulaAssistFieldOptions = computed(() => {
  const names = [
    ...fields.value.map(f => f.target_field).filter(Boolean),
    ...sourceNames.value
  ];
  return Array.from(new Set(names)).map(value => ({ value, label: value }));
});
const filteredFields = computed(() => {
  const q = fieldFilter.value.trim().toLowerCase();
  return fields.value
    .map((f, index) => ({
      f,
      index
    }))
    .filter(({ f }) => {
      if (
        categoryFilter.value !== "all" &&
        f.field_category !== categoryFilter.value
      ) {
        return false;
      }
      if (!q) return true;
      return (
        f.target_field.toLowerCase().includes(q) ||
        f.source_field.toLowerCase().includes(q) ||
        f.formula.toLowerCase().includes(q)
      );
    });
});
const fieldStatText = computed(() => {
  const dim = fields.value.filter(f => f.field_category === "dimension").length;
  const mea = fields.value.filter(f => f.field_category === "measure").length;
  const der = fields.value.filter(f => f.field_category === "derived").length;
  return `维度 ${dim} · 度量 ${mea} · 派生 ${der}`;
});
const fieldTableEpoch = ref(0);

function emptyField(order: number): AggField {
  return {
    source_field: "",
    target_field: "",
    field_type: "text",
    field_category: "dimension",
    aggregate_func: "",
    derive_level: 1,
    formula: "",
    sort_order: order,
    description: ""
  };
}

function stopRunTimers() {
  if (runTick != null) {
    window.clearInterval(runTick);
    runTick = null;
  }
}

function fmtElapsed(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

function startRunBar(mode: string, target: string) {
  stopRunTimers();
  runBar.visible = true;
  runBar.status = "queued";
  runBar.mode = mode;
  runBar.target = target;
  runBar.text = "正在提交任务…";
  runBar.jobId = 0;
  runBar.percent = 12;
  runBar.indeterminate = true;
  runBar.done = false;
  runBar.startedAt = Date.now();
  runElapsed.value = "0s";
  runTick = window.setInterval(() => {
    runElapsed.value = fmtElapsed(Date.now() - runBar.startedAt);
  }, 500);
}

function applyJobToBar(job: AggJob) {
  runBar.status = job.status || runBar.status;
  runBar.jobId = job.id;
  if (job.status === "queued") {
    runBar.text = `任务 #${job.id} 排队中，等待聚合服务…`;
    runBar.percent = 20;
  } else if (job.status === "running") {
    runBar.text = job.message || `任务 #${job.id} 正在聚合`;
    runBar.percent = 55;
  }
}

function finishRunBar(ok: boolean, text: string) {
  runBar.status = ok ? "success" : "failed";
  runBar.text = text;
  runBar.percent = 100;
  runBar.indeterminate = false;
  runBar.done = true;
  stopRunTimers();
  runElapsed.value = fmtElapsed(Date.now() - runBar.startedAt);
}

function assignScheduler(data?: Partial<AggScheduler> | null) {
  scheduler.is_active = Boolean(data?.is_active);
  scheduler.last_run_time = data?.last_run_time || "";
  scheduler.last_run_status = data?.last_run_status || "";
  scheduler.last_run_message = data?.last_run_message || "";
}

async function load() {
  loading.value = true;
  hint.value = "";
  try {
    const res = await aggOverview();
    rows.value = res.data?.projects || [];
    assignScheduler(res.data?.scheduler);
    const job = res.data?.active_job;
    activeJobId.value =
      job && (job.status === "queued" || job.status === "running")
        ? job.id
        : null;
  } catch (error) {
    hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

async function onSaveScheduler() {
  schedulerSaving.value = true;
  try {
    const res = await saveAggScheduler({
      is_active: scheduler.is_active
    });
    assignScheduler(res.data);
    ElMessage.success("已保存自动聚合");
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    schedulerSaving.value = false;
  }
}

function applyModel(data: AggModel) {
  model.value = data;
  fields.value = (data.fields || []).map((f, i) => ({
    ...emptyField(i),
    ...f,
    sort_order: f.sort_order ?? i
  }));
  timeField.value = data.time_field || "ServerTime";
  granularity.value = data.granularity || "hour";
  lookbackHours.value = data.lookback_hours || 1;
  backfillHours.value = data.backfill_hours || 12;
  enabled.value = Boolean(data.is_enabled);
}

function aggData<T>(res: { data?: T } | T): T {
  if (res && typeof res === "object" && "data" in res && res.data != null) {
    return res.data;
  }
  return res as T;
}

async function openEditor(row: AggProjectRow) {
  editorOpen.value = true;
  editorLoading.value = true;
  try {
    const ensured = await ensureAggModel(row.project_id);
    const data = aggData(ensured);
    applyModel(data);
    const cols = await getAggSourceColumns(data.id);
    sourceColumns.value = aggData(cols).columns || [];
    if (!fields.value.length) {
      await onSuggest();
    }
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
    editorOpen.value = false;
  } finally {
    editorLoading.value = false;
  }
}

function closeEditor() {
  editorOpen.value = false;
  model.value = null;
  fields.value = [];
  fieldFilter.value = "";
  categoryFilter.value = "all";
}

async function onSuggest() {
  if (!model.value) return;
  editorLoading.value = true;
  try {
    const res = await suggestAggFields(model.value.id);
    const data = aggData(res);
    if (!data?.fields?.length) {
      throw new Error("初始化未返回字段");
    }
    timeField.value = data.time_field || timeField.value;
    granularity.value = data.granularity || "hour";
    lookbackHours.value = data.lookback_hours || 1;
    backfillHours.value = data.backfill_hours || 12;
    categoryFilter.value = "all";
    fieldFilter.value = "";
    fields.value = data.fields.map((f, i) => ({
      ...emptyField(i),
      ...f,
      sort_order: i
    }));
    fieldTableEpoch.value += 1;
    ElMessage.success("已初始化字段");
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    editorLoading.value = false;
  }
}

function fieldRowClass({ row }: { row: { f: AggField } }) {
  return `agg-row agg-row--${row.f.field_category}`;
}

function addField() {
  addFieldTo(fields, emptyField);
}

function onSourcePick(row: AggField, col: string) {
  row.source_field = col;
  if (!row.target_field && col && col !== "*") row.target_field = col;
}

function onCategoryChange(row: AggField) {
  if (row.field_category === "dimension") {
    row.aggregate_func = "";
    row.formula = "";
    row.derive_level = 1;
    if (row.source_field === "*") row.source_field = "";
  } else if (row.field_category === "measure") {
    row.formula = "";
    row.derive_level = 1;
    if (!row.aggregate_func) row.aggregate_func = "COUNT";
    if (!row.source_field) row.source_field = "*";
    if (!row.target_field) row.target_field = "注塑机总产量";
    if (row.field_type === "text") row.field_type = "integer";
  } else {
    row.aggregate_func = "";
    row.source_field = "";
    if (!row.derive_level) row.derive_level = 2;
    if (!row.field_type || row.field_type === "text") {
      row.field_type = "decimal";
    }
  }
}

function removeField(index: number) {
  removeFieldAt(fields, index);
}

function moveField(index: number, delta: number) {
  moveFieldBy(fields, index, delta);
}

async function openFormulaAssist(row: AggField) {
  formulaAssistTarget.value = row;
  formulaAssistTab.value = "ai";
  formulaAssistPrompt.value = "";
  formulaAssistResult.value = row.formula || "";
  formulaAssistExplain.value = "";
  formulaAssistError.value = "";
  formulaAssistSource.value = "";
  formulaAssistSuggestLevel.value = 2;
  formulaAssistField.value =
    row.source_field ||
    fields.value.find(f => f.target_field === "注塑机总产量")?.target_field ||
    fields.value.find(f => f.field_category === "measure")?.target_field ||
    "";
  formulaAssistField2.value =
    fields.value.find(f => f.target_field === "自动外观总不良数")?.target_field ||
    "";
  formulaAssistVisible.value = true;
  try {
    const { getAiConfig } = await import("@/api/modules/ai");
    const res = await getAiConfig();
    formulaAssistAiReady.value = !!res.data?.ready;
  } catch {
    formulaAssistAiReady.value = false;
  }
}

function applyFormulaTemplate(key: string) {
  const a = (formulaAssistField.value || "").trim();
  const b = (formulaAssistField2.value || "").trim();
  if (!a || !b) {
    ElMessage.warning("请先选两列（字段 + 再选一列）");
    return;
  }
  const qa = `[${a}]`;
  const qb = `[${b}]`;
  const map: Record<string, { formula: string; explain: string }> = {
    rate: {
      formula: `${qa} * 1.0 / NULLIF(${qb}, 0)`,
      explain: `模板：不良率 = 「${a}」/「${b}」`
    },
    pct: {
      formula: `${qa} * 100.0 / NULLIF(${qb}, 0)`,
      explain: `模板：百分比 = 「${a}」/「${b}」*100`
    },
    safe_div: {
      formula: `CASE WHEN ${qb} = 0 OR ${qb} IS NULL THEN NULL ELSE ${qa} * 1.0 / ${qb} END`,
      explain: `模板：安全除法「${a}」/「${b}」`
    },
    sum2: {
      formula: `COALESCE(${qa}, 0) + COALESCE(${qb}, 0)`,
      explain: `模板：「${a}」+「${b}」`
    },
    diff: {
      formula: `COALESCE(${qa}, 0) - COALESCE(${qb}, 0)`,
      explain: `模板：「${a}」-「${b}」`
    }
  };
  const hit = map[key];
  if (!hit) return;
  formulaAssistResult.value = hit.formula;
  formulaAssistExplain.value = hit.explain;
  formulaAssistSource.value = "template";
  formulaAssistSuggestLevel.value = 2;
  formulaAssistError.value = "";
}

function insertAssistField(name: string) {
  const token = `[${name}]`;
  const cur = formulaAssistPrompt.value.trim();
  formulaAssistPrompt.value = cur ? `${cur} ${token}` : token;
}

async function runFormulaAssist() {
  if (!model.value || !formulaAssistPrompt.value.trim()) {
    ElMessage.warning("请先用中文描述需求");
    return;
  }
  formulaAssistLoading.value = true;
  formulaAssistError.value = "";
  formulaAssistExplain.value = "";
  formulaAssistSource.value = "";
  try {
    const available = formulaAssistFieldOptions.value.map(o => o.value);
    const res = await generateAggFormula(model.value.id, {
      prompt: formulaAssistPrompt.value.trim(),
      hint_field:
        formulaAssistField.value ||
        formulaAssistTarget.value?.target_field ||
        "",
      available_fields: available,
      mode: "auto"
    });
    const data = res.data;
    formulaAssistAiReady.value = !!data?.ai?.ready;
    if (data?.ok && data.formula) {
      formulaAssistResult.value = data.formula;
      formulaAssistExplain.value = data.explanation || "";
      formulaAssistSource.value = data.source || "";
      formulaAssistSuggestLevel.value = Number(data.suggest_level) || 2;
    } else {
      formulaAssistError.value = data?.error || "未能生成公式";
      formulaAssistResult.value = "";
    }
  } catch (error) {
    formulaAssistError.value = backendErrorHint(error);
  } finally {
    formulaAssistLoading.value = false;
  }
}

function applyFormulaAssist() {
  const row = formulaAssistTarget.value;
  if (!row || !formulaAssistResult.value) {
    ElMessage.warning("请先生成公式");
    return;
  }
  row.field_category = "derived";
  row.formula = formulaAssistResult.value;
  row.derive_level = formulaAssistSuggestLevel.value === 1 ? 1 : 2;
  if (!row.target_field) row.target_field = "派生列";
  onCategoryChange(row);
  formulaAssistVisible.value = false;
  ElMessage.success("已填入公式，可再微调");
}

async function onSave(enableAfter = false) {
  if (!model.value) return;
  saving.value = true;
  try {
    const grain = granularity.value || "hour";
    const res = await saveAggConfig(model.value.id, {
      time_field: timeField.value,
      granularity: grain,
      time_field_name: grain,
      lookback_hours: lookbackHours.value,
      backfill_hours: backfillHours.value,
      is_enabled: enableAfter ? true : enabled.value,
      fields: fields.value.map((f, i) => ({ ...f, sort_order: i }))
    });
    applyModel(res.data);
    enabled.value = Boolean(res.data.is_enabled);
    ElMessage.success(enableAfter ? "已保存并启用" : "已保存聚合配置");
    await load();
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    saving.value = false;
  }
}

function runTargetLabel(opts?: { projectId?: string; modelId?: number }) {
  if (opts?.projectId) {
    const hit = rows.value.find(r => r.project_id === opts.projectId);
    return hit?.display_name || opts.projectId;
  }
  return "全部已启用项目";
}

async function onRun(opts?: {
  projectId?: string;
  modelId?: number;
  fullRefresh?: boolean;
}) {
  const mode = opts?.fullRefresh ? "全量" : "增量";
  startRunBar(mode, runTargetLabel(opts));
  running.value = true;
  try {
    const res = await runAgg(opts);
    const data = res?.data;
    if (!data?.accepted || !data.job_id) {
      finishRunBar(false, data?.message || "无法入队");
      ElMessage.warning(data?.message || "无法入队");
      return;
    }
    runBar.jobId = data.job_id;
    runBar.text = `任务 #${data.job_id} 已提交，等待聚合服务…`;
    const job = await waitForAggJob(data.job_id, { onUpdate: applyJobToBar });
    applyJobToBar(job);
    if (job.status === "success") {
      const result = job.result || {};
      const total = Number(result.total_rows ?? result.rows ?? 0) || 0;
      finishRunBar(true, `完成，写入 ${total.toLocaleString()} 行`);
      ElMessage.success("聚合完成");
    } else {
      finishRunBar(false, job.message || "聚合失败");
      ElMessage.error(job.message || "聚合失败");
    }
    await load();
  } catch (error) {
    finishRunBar(false, backendErrorHint(error));
    ElMessage.error(backendErrorHint(error));
  } finally {
    running.value = false;
  }
}

async function onRunFull(opts?: { projectId?: string; modelId?: number }) {
  try {
    await ElMessageBox.confirm(
      "全量会删除并重建汇总表。日常请用增量（只回算最近若干小时）。",
      "全量重建",
      { type: "warning" }
    );
  } catch {
    return;
  }
  await onRun({ ...opts, fullRefresh: true });
}

async function onPreview(live: boolean) {
  if (!model.value) return;
  editorLoading.value = true;
  try {
    const res = await previewAggData(model.value.id, {
      hours: 1,
      live,
      limit: 300
    });
    previewLive.value = live;
    previewCols.value = res.data?.columns || [];
    previewRows.value = res.data?.rows || [];
    const fromTime = res.data?.from_time || "";
    const toTime = res.data?.to_time || "";
    const span = fromTime && toTime ? `${fromTime} ~ ${toTime}` : "暂无时间";
    previewMeta.value = `${res.data?.source === "ads" ? "汇总表" : "清洗表现算"} · 最新有数据的 1 小时（${span}） · ${res.data?.source_table} · ${previewRows.value.length} 行`;
    previewOpen.value = true;
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    editorLoading.value = false;
  }
}

async function onShowSql() {
  if (!model.value) return;
  try {
    const res = await getAggSqlPreview(model.value.id);
    sqlText.value = res.data?.sql || "";
    sqlOpen.value = true;
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  }
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    success: "成功",
    failed: "失败",
    running: "进行中",
    queued: "已排队",
    busy: "忙碌",
    skipped: "已跳过"
  };
  return map[status] || status || "—";
}

onMounted(load);
onUnmounted(stopRunTimers);
</script>

<template>
  <div class="etl-page" :class="{ 'is-editing': editorOpen }" v-loading="loading">
    <div v-if="runBar.visible" class="etl-runbar" :class="`is-${runBar.status}`">
      <div class="etl-runbar__top">
        <div class="etl-runbar__meta">
          <el-tag
            size="small"
            :type="runBar.mode === '全量' ? 'warning' : 'primary'"
            effect="dark"
          >
            {{ runBar.mode }}
          </el-tag>
          <strong>{{ runBar.target }}</strong>
          <el-tag size="small" :type="statusType(runBar.status)" effect="light">
            {{ statusLabel(runBar.status) }}
          </el-tag>
          <span v-if="runBar.jobId">任务 #{{ runBar.jobId }}</span>
          <span>已用时 {{ runElapsed }}</span>
        </div>
        <el-button v-if="runBar.done" link type="info" @click="runBar.visible = false">
          关闭
        </el-button>
      </div>
      <el-progress
        :percentage="runBar.percent"
        :status="
          runBar.status === 'failed'
            ? 'exception'
            : runBar.status === 'success'
              ? 'success'
              : undefined
        "
        :indeterminate="runBar.indeterminate"
        :stroke-width="10"
      />
      <p class="etl-runbar__text">{{ runBar.text }}</p>
    </div>

    <header v-if="!editorOpen" class="etl-head">
      <div>
        <h2>数据聚合</h2>
        <p>
          清洗表明细按时间细度、再按自动外观线体 / 机台 / 模穴 / 模仁 / 本体等维度写成汇总表。默认按小时一组，增量默认回算最近 12 小时，均可在配置里改。
        </p>
      </div>
      <div class="etl-head__actions">
        <el-button :loading="running" @click="onRunFull()">全量重建全部</el-button>
        <el-button type="primary" :loading="running" @click="onRun()">
          增量聚合全部
        </el-button>
      </div>
    </header>

    <el-alert
      v-if="hint"
      type="warning"
      :closable="false"
      :title="hint"
      show-icon
      class="etl-alert"
    />
    <el-alert
      v-if="activeJobId"
      type="info"
      :closable="false"
      :title="`当前有聚合任务 #${activeJobId} 排队或执行中`"
      show-icon
      class="etl-alert"
    />

    <template v-if="!editorOpen">
      <section class="etl-stats">
        <div class="etl-stat">
          <span class="etl-stat__label">项目</span>
          <strong>{{ rows.length }}</strong>
        </div>
        <div class="etl-stat">
          <span class="etl-stat__label">已配置</span>
          <strong>{{ configuredCount }}</strong>
        </div>
        <div class="etl-stat">
          <span class="etl-stat__label">可自动跑</span>
          <strong>{{ enabledCount }}</strong>
        </div>
        <div class="etl-stat">
          <span class="etl-stat__label">自动节奏</span>
          <strong>整点 / 按配置</strong>
        </div>
      </section>

      <section class="etl-panel etl-schedule">
        <div class="etl-schedule__head">
          <div>
            <h3>自动聚合</h3>
            <p>
              每小时整点跑一轮。细度与回算窗口以各模型配置为准（默认按小时一组、回算最近 12 小时）。请保持聚合服务处于运行状态。
            </p>
          </div>
          <el-tag
            size="small"
            :type="scheduler.is_active ? 'success' : 'info'"
            effect="light"
          >
            {{ scheduler.is_active ? "已开启" : "已关闭" }}
          </el-tag>
        </div>
        <div class="etl-schedule__form">
          <div class="etl-schedule__item">
            <span>启用整点自动聚合</span>
            <el-switch v-model="scheduler.is_active" />
          </div>
          <el-button
            type="primary"
            plain
            :loading="schedulerSaving"
            @click="onSaveScheduler"
          >
            保存调度
          </el-button>
        </div>
        <div
          v-if="scheduler.last_run_time || scheduler.last_run_message"
          class="etl-schedule__meta"
        >
          <el-tag
            v-if="scheduler.last_run_status"
            size="small"
            :type="statusType(scheduler.last_run_status)"
          >
            {{ statusLabel(scheduler.last_run_status) }}
          </el-tag>
          <span>{{ scheduler.last_run_time || "—" }}</span>
          <span class="muted">{{ scheduler.last_run_message }}</span>
        </div>
      </section>

      <section class="etl-panel">
        <div class="etl-panel__head">
          <div>
            <h2>项目列表</h2>
            <p>清洗表 → 按小时汇总表。每小时、每个维度组合一行。</p>
          </div>
        </div>
        <el-table :data="rows" border stripe empty-text="暂无项目" class="etl-list-table">
          <el-table-column prop="display_name" label="项目" min-width="100" />
          <el-table-column label="数据流" min-width="220">
            <template #default="{ row }">
              <div class="etl-flow">
                <code>{{ row.source_table || "—" }}</code>
                <span class="etl-flow__arrow">→</span>
                <code>{{ row.target_table || "—" }}</code>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="配置" width="110" align="center">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.is_draft || !row.field_count ? 'warning' : 'success'"
                effect="light"
              >
                {{
                  row.is_draft || !row.field_count
                    ? "未配置"
                    : `${row.field_count} 列`
                }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="88" align="center">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.is_model_enabled ? 'success' : 'info'"
                effect="plain"
              >
                {{ row.is_model_enabled ? "已启用" : "未启用" }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近聚合" min-width="180">
            <template #default="{ row }">
              <div class="etl-run-cell">
                <el-tag
                  v-if="row.last_agg_status"
                  size="small"
                  :type="statusType(row.last_agg_status)"
                  effect="light"
                >
                  {{ statusLabel(row.last_agg_status) }}
                </el-tag>
                <span class="etl-run-cell__time">{{
                  row.last_agg_time || "尚未聚合"
                }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="结果" min-width="220">
            <template #default="{ row }">
              <span class="etl-result-text">{{
                row.last_agg_message || "—"
              }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="210" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEditor(row)">配置</el-button>
              <el-button
                link
                type="primary"
                :disabled="!row.can_run || running"
                @click="onRun({ projectId: row.project_id, modelId: row.model_id })"
              >
                增量
              </el-button>
              <el-button
                link
                :disabled="!row.can_run || running"
                @click="
                  onRunFull({ projectId: row.project_id, modelId: row.model_id })
                "
              >
                全量
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </template>

    <section v-else class="etl-panel etl-editor" v-loading="editorLoading">
      <header class="etl-panel__head">
        <div class="etl-panel__title">
          <h2>
            {{ model?.display_name || "聚合配置" }}
            <el-tag
              v-if="model"
              size="small"
              :type="model.is_draft ? 'warning' : 'success'"
              effect="light"
            >
              {{ model.is_draft ? "草稿" : "已生成语句" }}
            </el-tag>
          </h2>
          <p class="etl-path">
            <code>{{ model?.source_table }}</code>
            <span class="etl-flow__arrow">→</span>
            <code>{{ model?.target_table }}</code>
            <span class="etl-count">{{ fieldStatText }}</span>
          </p>
        </div>
        <div class="etl-panel__actions">
          <el-button @click="closeEditor">返回列表</el-button>
          <el-button @click="onShowSql">查看语句</el-button>
          <el-button :loading="saving" @click="onSave(false)">保存</el-button>
          <el-button type="primary" :loading="saving" @click="onSave(true)">
            保存并启用
          </el-button>
        </div>
      </header>

      <div class="etl-config-bar">
        <el-form class="etl-meta-form" label-position="top" @submit.prevent>
          <div class="etl-grid">
            <el-form-item label="时间字段">
              <el-select v-model="timeField" filterable allow-create>
                <el-option
                  v-for="name in sourceNames"
                  :key="name"
                  :label="name"
                  :value="name"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="细度">
              <el-select v-model="granularity">
                <el-option label="按小时一组" value="hour" />
                <el-option label="按天一组" value="day" />
                <el-option label="按周一组" value="week" />
                <el-option label="按月一组" value="month" />
              </el-select>
            </el-form-item>
            <el-form-item label="增量回算">
              <el-input-number
                v-model="backfillHours"
                :min="1"
                :max="720"
                controls-position="right"
              />
              <span class="etl-unit">小时</span>
            </el-form-item>
          </div>
        </el-form>
      </div>

      <div class="etl-toolbar sticky">
        <div class="etl-toolbar__left">
          <el-button type="primary" plain @click="addField">添加字段</el-button>
          <el-button @click="onSuggest">初始化</el-button>
          <el-input
            v-model="fieldFilter"
            clearable
            placeholder="搜索字段…"
            class="etl-search"
          />
          <PageTabs
            v-model="categoryFilter"
            :options="categoryFilterTabs"
            size="small"
            aria-label="字段筛选"
          />
        </div>
        <div class="etl-toolbar__right">
          <el-button @click="onPreview(true)">预览</el-button>
          <el-button type="primary" plain @click="onPreview(false)">
            看汇总表
          </el-button>
        </div>
      </div>

      <div v-if="!fields.length" class="etl-empty">
        <p class="etl-empty__title">还没有聚合字段</p>
        <p class="etl-empty__lead">
          添加一行后先选属性：维度用来分组，度量做计数或求和，派生用已有列写公式。
        </p>
        <el-button type="primary" @click="addField">添加字段</el-button>
      </div>

      <div v-else class="etl-table-wrap">
        <el-table
          :key="fieldTableEpoch"
          :data="filteredFields"
          border
          stripe
          height="100%"
          row-key="index"
          empty-text="无匹配字段"
          class="etl-fields-table"
          :row-class-name="fieldRowClass"
        >
          <el-table-column label="#" width="52" align="center">
            <template #default="{ row }">
              <span class="muted">{{ row.index + 1 }}</span>
            </template>
          </el-table-column>
          <el-table-column label="汇总列名" width="140">
            <template #default="{ row }">
              <el-input
                v-model="row.f.target_field"
                size="small"
                placeholder="写入汇总表的列名"
              />
            </template>
          </el-table-column>
          <el-table-column label="属性" width="110">
            <template #default="{ row }">
              <el-select
                v-model="row.f.field_category"
                size="small"
                @change="onCategoryChange(row.f)"
              >
                <el-option
                  v-for="opt in categoryOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="清洗表字段" width="180">
            <template #default="{ row }">
              <el-select
                v-if="row.f.field_category !== 'derived'"
                v-model="row.f.source_field"
                size="small"
                filterable
                allow-create
                default-first-option
                clearable
                placeholder="选择清洗表字段"
                style="width: 100%"
                @change="(v: string) => onSourcePick(row.f, v)"
              >
                <el-option
                  v-if="row.f.field_category === 'measure'"
                  label="*（行数）"
                  value="*"
                />
                <el-option
                  v-if="
                    row.f.source_field &&
                    row.f.source_field !== '*' &&
                    !sourceNames.includes(row.f.source_field)
                  "
                  :label="row.f.source_field"
                  :value="row.f.source_field"
                />
                <el-option
                  v-for="col in sourceColumns"
                  :key="col.column_name"
                  :label="col.column_name"
                  :value="col.column_name"
                />
              </el-select>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="函数" width="120">
            <template #default="{ row }">
              <el-select
                v-if="row.f.field_category === 'measure'"
                v-model="row.f.aggregate_func"
                size="small"
              >
                <el-option
                  v-for="opt in aggregateOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="字段类型" width="100">
            <template #default="{ row }">
              <el-select v-model="row.f.field_type" size="small">
                <el-option
                  v-for="opt in fieldTypeOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="公式" min-width="280">
            <template #default="{ row }">
              <div v-if="row.f.field_category === 'derived'" class="etl-formula">
                <el-input
                  v-model="row.f.formula"
                  size="small"
                  placeholder="用 [列名] 引用其他汇总列"
                />
                <el-button
                  size="small"
                  text
                  type="primary"
                  @click="openFormulaAssist(row.f)"
                >
                  公式生成
                </el-button>
              </div>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="层级" width="80">
            <template #default="{ row }">
              <el-select
                v-model="row.f.derive_level"
                size="small"
                :disabled="row.f.field_category !== 'derived'"
              >
                <el-option :value="1" label="L1" />
                <el-option :value="2" label="L2" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                :disabled="row.index === 0"
                @click="moveField(row.index, -1)"
              >
                ↑
              </el-button>
              <el-button
                link
                :disabled="row.index >= fields.length - 1"
                @click="moveField(row.index, 1)"
              >
                ↓
              </el-button>
              <el-button link type="danger" @click="removeField(row.index)">
                删
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <p class="etl-tip">预览取清洗表里最新有数据的 1 小时，不按当前时刻截断。</p>
    </section>

    <el-dialog v-model="previewOpen" :title="previewLive ? '预览' : '汇总表'" width="86%">
      <p class="etl-tip">{{ previewMeta }}</p>
      <el-table
        :data="previewRows"
        border
        stripe
        max-height="520"
        empty-text="这段时间没有数据"
      >
        <el-table-column
          v-for="col in previewCols"
          :key="col"
          :prop="col"
          :label="col"
          min-width="110"
          show-overflow-tooltip
        />
      </el-table>
    </el-dialog>

    <el-dialog v-model="sqlOpen" title="聚合语句" width="720px">
      <pre class="etl-sql-dialog">{{ sqlText }}</pre>
    </el-dialog>

    <el-dialog
      v-model="formulaAssistVisible"
      width="640px"
      destroy-on-close
    >
      <template #header>
        <div class="etl-assist-title">
          <span>公式生成</span>
          <el-tag
            size="small"
            :type="formulaAssistAiReady ? 'success' : 'info'"
          >
            {{
              formulaAssistAiReady
                ? "AI 已就绪"
                : "AI 未就绪（描述页将用规则生成）"
            }}
          </el-tag>
        </div>
      </template>

      <el-tabs v-model="formulaAssistTab" class="etl-assist-tabs">
        <el-tab-pane label="AI 描述" name="ai">
          <p class="etl-assist-lead">
            先选已有汇总列，再用中文描述。已配置 AI 时优先由模型生成。
            <router-link class="etl-assist-link" to="/feature/ai-model">
              去配置 AI 模型
            </router-link>
          </p>
          <div class="etl-assist-fields">
            <div class="etl-assist-field">
              <span class="etl-assist-label">字段</span>
              <el-select
                v-model="formulaAssistField"
                filterable
                clearable
                placeholder="选择后写入描述"
                style="width: 100%"
                @change="(v: string) => v && insertAssistField(v)"
              >
                <el-option
                  v-for="opt in formulaAssistFieldOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </div>
            <div class="etl-assist-field">
              <span class="etl-assist-label">再选一列（可选）</span>
              <el-select
                v-model="formulaAssistField2"
                filterable
                clearable
                placeholder="需要两列时再选"
                style="width: 100%"
                @change="(v: string) => v && insertAssistField(v)"
              >
                <el-option
                  v-for="opt in formulaAssistFieldOptions"
                  :key="`b-${opt.value}`"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </div>
          </div>
          <el-input
            v-model="formulaAssistPrompt"
            type="textarea"
            :rows="5"
            placeholder="例如：把自动外观总不良数按注塑机总产量换算"
          />
          <div class="etl-assist-actions">
            <el-button
              type="primary"
              :loading="formulaAssistLoading"
              @click="runFormulaAssist"
            >
              {{ formulaAssistAiReady ? "AI 生成公式" : "生成公式" }}
            </el-button>
          </div>
        </el-tab-pane>

        <el-tab-pane label="模板" name="template">
          <p class="etl-assist-lead">
            先选两列，再点模板直接填出公式（不走 AI）。
          </p>
          <div class="etl-assist-fields">
            <div class="etl-assist-field">
              <span class="etl-assist-label">字段 A</span>
              <el-select
                v-model="formulaAssistField"
                filterable
                clearable
                placeholder="分子 / 被减数"
                style="width: 100%"
              >
                <el-option
                  v-for="opt in formulaAssistFieldOptions"
                  :key="`t-${opt.value}`"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </div>
            <div class="etl-assist-field">
              <span class="etl-assist-label">字段 B</span>
              <el-select
                v-model="formulaAssistField2"
                filterable
                clearable
                placeholder="分母 / 减数"
                style="width: 100%"
              >
                <el-option
                  v-for="opt in formulaAssistFieldOptions"
                  :key="`t2-${opt.value}`"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </div>
          </div>
          <div class="etl-assist-templates">
            <button
              v-for="tip in formulaTemplates"
              :key="tip.key"
              type="button"
              class="etl-assist-template"
              @click="applyFormulaTemplate(tip.key)"
            >
              <span class="etl-assist-template__label">{{ tip.label }}</span>
              <span class="etl-assist-template__need">两列</span>
            </button>
          </div>
          <div class="etl-assist-result">
            <span class="etl-assist-label">公式预览（可改）</span>
            <p
              v-if="
                formulaAssistExplain && formulaAssistSource === 'template'
              "
              class="etl-assist-explain"
            >
              <el-tag size="small" style="margin-right: 6px">模板</el-tag>
              {{ formulaAssistExplain }}
            </p>
            <el-input
              v-model="formulaAssistResult"
              type="textarea"
              :rows="4"
              placeholder="点上方模板后出现公式，也可手改"
            />
          </div>
        </el-tab-pane>
      </el-tabs>

      <el-alert
        v-if="formulaAssistError"
        type="warning"
        :closable="false"
        :title="formulaAssistError"
        show-icon
        style="margin-top: 8px"
      />
      <template v-if="formulaAssistTab === 'ai' && formulaAssistResult">
        <p
          v-if="
            formulaAssistExplain && formulaAssistSource !== 'template'
          "
          class="etl-assist-explain"
        >
          <el-tag
            v-if="formulaAssistSource"
            size="small"
            style="margin-right: 6px"
          >
            {{ formulaAssistSource === "ai" ? "AI" : "规则" }}
          </el-tag>
          {{ formulaAssistExplain }}
        </p>
        <el-input v-model="formulaAssistResult" type="textarea" :rows="5" />
      </template>
      <template #footer>
        <el-button @click="formulaAssistVisible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!formulaAssistResult"
          @click="applyFormulaAssist"
        >
          填入公式
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style lang="scss" scoped>
// as *：与原 @import 的全局作用域语义一致
@use "./agg.styles/scoped.scss" as *;
</style>
