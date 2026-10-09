<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  clearEtlFields,
  clearEtlLogs,
  ensureEtlModel,
  etlOverview,
  getEtlFieldTypes,
  getEtlModel,
  getSourceColumns,
  getSqlPreview,
  importDirectFields,
  listEtlLogs,
  reanalyzeSourceFields,
  generateEtlFormula,
  previewEtlData,
  runEtl,
  saveEtlFields,
  saveEtlScheduler,
  saveEtlSourceFields,
  updateEtlModel,
  waitForEtlJob,
  type EtlJob,
  type EtlField,
  type EtlFieldTypeOption,
  type EtlModel,
  type EtlProjectRow,
  type EtlRunLog,
  type EtlScheduler,
  type EtlSourceField,
  type SourceColumn
} from "@/api/modules/etl";
import { backendErrorHint } from "@/api/http";
import { switchValue } from "@/utils/switchValue";
import PageTabs from "@/components/PageTabs/index.vue";
import {
  addFieldTo,
  moveFieldBy,
  removeFieldAt,
  statusType
} from "@/composables/useFieldList";

defineOptions({
  name: "FeatureEtl"
});

const loading = ref(false);
const running = ref(false);
const saving = ref(false);
const schedulerSaving = ref(false);
const rows = ref<EtlProjectRow[]>([]);
const hint = ref("");
const activeJobId = ref<number | null>(null);
const activeTab = ref("config");
const logs = ref<EtlRunLog[]>([]);
const logsLoading = ref(false);
const scheduler = reactive<EtlScheduler>({
  is_active: false,
  run_interval: 30,
  last_run_time: "",
  last_run_status: "",
  last_run_message: ""
});

const enabledCount = computed(
  () => rows.value.filter(r => r.is_model_enabled && r.can_run).length
);
const configuredCount = computed(
  () => rows.value.filter(r => (r.field_count || 0) > 0 && !r.is_draft).length
);
const totalLastRows = computed(() =>
  rows.value.reduce((sum, r) => sum + (Number(r.last_etl_rows) || 0), 0)
);
const latestLog = computed(() => logs.value[0] || null);
const logsStatus = computed(
  () => latestLog.value?.status || scheduler.last_run_status || ""
);
const logsTime = computed(
  () =>
    latestLog.value?.ended_at ||
    latestLog.value?.started_at ||
    scheduler.last_run_time ||
    ""
);

const editorOpen = ref(false);
const editorLoading = ref(false);
const model = ref<EtlModel | null>(null);
/** 第1页：原表字段类型目录 */
const sourceFields = ref<EtlSourceField[]>([]);
/** 第2页：清洗表字段（手动配置，不自动生成） */
const fields = ref<EtlField[]>([]);
const sourceColumns = ref<SourceColumn[]>([]);
const fieldFilter = ref("");
const typeFilter = ref("all");
/** types=原表类型；mapping=清洗表字段 */
const editorStage = ref<"types" | "mapping">("types");
const sqlOpen = ref(false);
const sqlText = ref("");
const previewOpen = ref(false);
const previewCols = ref<string[]>([]);
const previewRows = ref<Record<string, unknown>[]>([]);

const runBar = reactive({
  visible: false,
  mode: "增量",
  target: "",
  jobId: 0,
  status: "queued",
  percent: 8,
  indeterminate: true,
  text: "",
  done: false
});
const runElapsed = ref("0 秒");
let runElapsedTimer: ReturnType<typeof setInterval> | null = null;
let runBarHideTimer: ReturnType<typeof setTimeout> | null = null;

const mappingOptions = [
  { label: "直接映射", value: "direct" },
  { label: "派生公式", value: "derived" },
  { label: "固定值", value: "constant" }
];

const fieldTypeOptions = ref<EtlFieldTypeOption[]>([
  { value: "text", label: "文本" },
  { value: "integer", label: "整数" },
  { value: "decimal", label: "小数" },
  { value: "percent", label: "百分比" },
  { value: "datetime", label: "时间" },
  { value: "boolean", label: "布尔" }
]);

const typeFilterTabs = computed(() => {
  if (editorStage.value === "types") {
    return [
      { value: "all", label: "全部" },
      ...fieldTypeOptions.value.map(opt => ({
        value: opt.value,
        label: opt.label
      }))
    ];
  }
  return [
    { value: "all", label: "全部" },
    { value: "direct", label: "直映" },
    { value: "derived", label: "派生" },
    { value: "constant", label: "常量" }
  ];
});

const formulaTemplates = [
  { key: "mid567", label: "提取第5–7位", need: "one" },
  { key: "mid1314", label: "提取第13–14位", need: "one" },
  { key: "trim", label: "去空格", need: "one" },
  { key: "upper", label: "转大写", need: "one" },
  { key: "okng", label: "OK → 合格 / 否则不合格", need: "one" },
  { key: "bool01", label: "1 → 不良 / 0 → 良", need: "one" },
  { key: "concat", label: "拼接两列（横杠）", need: "two" },
  { key: "any01", label: "有1为1（2～8 列）", need: "many" }
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
const formulaAssistSuggestLevel = ref(1);
const formulaAssistTarget = ref<EtlField | null>(null);
const formulaAssistField = ref("");
const formulaAssistField2 = ref("");
const formulaAssistManyFields = ref<string[]>([]);
const assistEditorEl = ref<HTMLElement | null>(null);
const assistComposing = ref(false);

const formulaAssistFieldOptions = computed(() => {
  const typeLabel = (ft: string) =>
    fieldTypeOptions.value.find(t => t.value === ft)?.label || ft || "文本";
  const seen = new Set<string>();
  const out: { value: string; label: string }[] = [];
  for (const f of sourceFields.value) {
    const name = String(f.source_field || "").trim();
    if (!name || seen.has(name)) continue;
    seen.add(name);
    out.push({
      value: name,
      label: `${name}（${typeLabel(f.field_type)}）`
    });
  }
  for (const f of fields.value) {
    const name = String(f.target_field || "").trim();
    if (!name || seen.has(name)) continue;
    seen.add(name);
    out.push({
      value: name,
      label: `${name}（清洗列）`
    });
  }
  return out;
});

const canEnable = computed(
  () =>
    !!model.value &&
    !model.value.is_draft &&
    !!model.value.sql_path &&
    fields.value.length > 0
);

const stepIndex = computed(() => {
  // 0 导入 → 1 原表类型页 → 2 清洗表字段页 → 3 已生成SQL/启用
  if (!sourceFields.value.length) return 0;
  if (editorStage.value === "types") return 1;
  if (!model.value || model.value.is_draft || !model.value.sql_path) return 2;
  return 3;
});

const typeCounts = computed(() => {
  const c: Record<string, number> = {};
  for (const f of sourceFields.value) {
    const t = f.field_type || "text";
    c[t] = (c[t] || 0) + 1;
  }
  return c;
});

const sourceTypeMap = computed(() => {
  const map: Record<string, string> = {};
  for (const f of sourceFields.value) {
    map[f.source_field] = f.field_type || "text";
  }
  return map;
});

const typeCountText = computed(() => {
  return fieldTypeOptions.value
    .map(opt => {
      const n = typeCounts.value[opt.value] || 0;
      return n ? `${opt.label}${n}` : "";
    })
    .filter(Boolean)
    .join(" / ");
});

const uniqueKeyOptions = computed(() => {
  const fromFields = fields.value.map(f => f.target_field).filter(Boolean);
  const fromSource = sourceFields.value.map(f => f.source_field);
  return Array.from(
    new Set([...fromFields, ...fromSource, model.value?.unique_key || ""])
  ).filter(Boolean);
});

const incrementalFieldOptions = computed(() => {
  const times = sourceFields.value
    .filter(f => f.field_type === "datetime" || /time|date|at$/i.test(f.source_field))
    .map(f => f.source_field);
  return Array.from(
    new Set([
      "ingested_at",
      ...times,
      model.value?.incremental_field || ""
    ])
  ).filter(Boolean);
});

const filteredSourceFields = computed(() => {
  const q = fieldFilter.value.trim().toLowerCase();
  return sourceFields.value
    .map((f, index) => ({ f, index }))
    .filter(({ f }) => {
      if (typeFilter.value !== "all" && f.field_type !== typeFilter.value) {
        return false;
      }
      if (!q) return true;
      return f.source_field.toLowerCase().includes(q);
    });
});

const filteredFields = computed(() => {
  const q = fieldFilter.value.trim().toLowerCase();
  return fields.value
    .map((f, index) => ({ f, index }))
    .filter(({ f }) => {
      if (typeFilter.value !== "all" && f.mapping_type !== typeFilter.value) {
        return false;
      }
      if (!q) return true;
      return (
        f.target_field.toLowerCase().includes(q) ||
        f.source_field.toLowerCase().includes(q) ||
        f.formula.toLowerCase().includes(q) ||
        f.constant_value.toLowerCase().includes(q)
      );
    });
});

function emptyField(order: number): EtlField {
  return {
    source_field: "",
    target_field: "",
    field_type: "text",
    mapping_type: "direct",
    derive_level: 1,
    formula: "",
    constant_value: "",
    sort_order: order,
    is_required: false,
    description: ""
  };
}

function setAllFieldType(ftype: string) {
  if (!sourceFields.value.length) return;
  sourceFields.value = sourceFields.value.map(f => ({ ...f, field_type: ftype }));
  ElMessage.success(
    `已将全部原表列设为「${fieldTypeOptions.value.find(t => t.value === ftype)?.label || ftype}」`
  );
}

function applyScheduler(data?: Partial<EtlScheduler> | null) {
  if (!data) return;
  scheduler.is_active = !!data.is_active;
  scheduler.run_interval = Number(data.run_interval) || 30;
  scheduler.last_run_time = data.last_run_time || "";
  scheduler.last_run_status = data.last_run_status || "";
  scheduler.last_run_message = data.last_run_message || "";
}

async function load(silent = false) {
  if (!silent) loading.value = true;
  hint.value = "";
  try {
    const res = await etlOverview();
    rows.value = res?.data?.projects || [];
    activeJobId.value = res?.data?.active_job?.id ?? null;
    applyScheduler(res?.data?.scheduler);
    if (activeTab.value === "logs") await loadLogs(true);
  } catch (error) {
    if (!silent) hint.value = backendErrorHint(error);
  } finally {
    if (!silent) loading.value = false;
  }
}

async function loadLogs(silent = false) {
  if (!silent) logsLoading.value = true;
  try {
    const res = await listEtlLogs(50);
    logs.value = res?.data?.logs || [];
  } catch (error) {
    if (!silent) ElMessage.error(backendErrorHint(error));
  } finally {
    if (!silent) logsLoading.value = false;
  }
}

async function onClearLogs() {
  if (!logs.value.length) return;
  try {
    await ElMessageBox.confirm(
      "清除全部运行日志？进行中的记录会保留。",
      "清除日志",
      { type: "warning" }
    );
  } catch {
    return;
  }
  try {
    const res = await clearEtlLogs();
    ElMessage.success(`已清除 ${res?.data?.deleted ?? 0} 条`);
    await loadLogs();
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  }
}

function dash(value: unknown) {
  const text = String(value ?? "").trim();
  return text || "—";
}

function modeLabel(mode: string) {
  if (mode === "full") return "全量";
  if (mode === "incremental") return "增量";
  return mode || "—";
}

function triggerLabel(trigger: string) {
  if (trigger === "auto") return "自动";
  if (trigger === "manual") return "手动";
  return trigger || "—";
}

function formatDuration(sec: number) {
  const n = Number(sec) || 0;
  if (n < 1) return `${Math.round(n * 1000)} ms`;
  if (n < 60) return `${n.toFixed(1)} 秒`;
  const m = Math.floor(n / 60);
  const s = Math.round(n % 60);
  return `${m} 分 ${s} 秒`;
}

function onTabChange(name: string | number) {
  if (name === "logs") void loadLogs();
}

async function onSaveScheduler() {
  schedulerSaving.value = true;
  try {
    const res = await saveEtlScheduler({
      is_active: scheduler.is_active,
      run_interval: scheduler.run_interval
    });
    applyScheduler(res.data);
    ElMessage.success(
      scheduler.is_active
        ? `已开启自动清洗，每 ${scheduler.run_interval} 分钟投递已启用模型`
        : "已关闭自动清洗"
    );
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    schedulerSaving.value = false;
  }
}

async function loadSourceColumns(modelId: number) {
  try {
    const res = await getSourceColumns(modelId);
    sourceColumns.value = res.data.columns || [];
  } catch {
    sourceColumns.value = [];
  }
}

async function openEditor(row: EtlProjectRow) {
  editorOpen.value = true;
  editorLoading.value = true;
  sqlText.value = "";
  fieldFilter.value = "";
  typeFilter.value = "all";
  editorStage.value = "types";
  try {
    let mid = row.model_id;
    if (!mid) {
      const created = await ensureEtlModel(row.project_id);
      mid = created.data.id;
    }
    const [res] = await Promise.all([
      getEtlModel(mid!),
      loadSourceColumns(mid!)
    ]);
    model.value = {
      ...res.data,
      incremental_field: res.data.incremental_field || "ingested_at"
    };
    sourceFields.value = (res.data.source_fields || []).map((f, i) => ({
      source_field: f.source_field,
      field_type: f.field_type || "text",
      sort_order: f.sort_order ?? i
    }));
    fields.value = (res.data.fields || []).map((f, i) => ({
      ...f,
      sort_order: f.sort_order ?? i
    }));
    // 有清洗映射则停在第2页，否则第1页
    editorStage.value = fields.value.length ? "mapping" : "types";
    if (res.data.sql_path) {
      try {
        const sqlRes = await getSqlPreview(mid!);
        sqlText.value = sqlRes.data.sql || "";
      } catch {
        sqlText.value = "";
      }
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
  sourceFields.value = [];
  fields.value = [];
  sourceColumns.value = [];
  sqlText.value = "";
  editorStage.value = "types";
}

async function goMappingStage() {
  if (!sourceFields.value.length) {
    ElMessage.warning("请先导入原表字段并配置类型");
    return;
  }
  if (!model.value) return;
  saving.value = true;
  try {
    // 先落原表类型，再进入清洗表页（不自动生成清洗列）
    const res = await saveEtlSourceFields(
      model.value.id,
      sourceFields.value.map((f, i) => ({
        source_field: f.source_field,
        field_type: f.field_type || "text",
        sort_order: i
      }))
    );
    model.value = res.data;
    sourceFields.value = res.data.source_fields || sourceFields.value;
    // 清洗表字段保持现状：已有则显示，没有则空着让用户自己加
    fields.value = res.data.fields || fields.value;
    editorStage.value = "mapping";
    typeFilter.value = "all";
    fieldFilter.value = "";
    if (!fields.value.length) {
      ElMessage.info("请手动添加清洗表字段，并选择对应的原表字段");
    }
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    saving.value = false;
  }
}

function goTypesStage() {
  editorStage.value = "types";
  typeFilter.value = "all";
  fieldFilter.value = "";
}

function addField() {
  addFieldTo(fields, emptyField);
}

function onCleanSourcePick(row: EtlField, col: string) {
  row.source_field = col;
  if (!row.target_field) row.target_field = "";
  row.field_type = sourceTypeMap.value[col] || row.field_type || "text";
}

function removeField(index: number) {
  removeFieldAt(fields, index);
}

function moveField(index: number, delta: number) {
  moveFieldBy(fields, index, delta);
}

function onSourcePick(row: EtlField, col: string) {
  row.source_field = col;
  if (!row.target_field) row.target_field = col;
}

function onMappingChange(row: EtlField) {
  if (row.mapping_type === "direct") {
    row.formula = "";
    row.constant_value = "";
    row.derive_level = 1;
    if (!row.source_field && row.target_field) row.source_field = row.target_field;
  } else if (row.mapping_type === "derived") {
    row.constant_value = "";
    if (!row.derive_level) row.derive_level = 1;
  } else if (row.mapping_type === "constant") {
    row.formula = "";
    row.source_field = "";
    row.derive_level = 1;
  }
}

async function openFormulaAssist(row: EtlField) {
  formulaAssistTarget.value = row;
  formulaAssistTab.value = "ai";
  formulaAssistPrompt.value = "";
  formulaAssistResult.value = row.formula || "";
  formulaAssistExplain.value = "";
  formulaAssistError.value = "";
  formulaAssistSource.value = "";
  formulaAssistSuggestLevel.value = 1;
  formulaAssistField.value = "";
  formulaAssistField2.value = "";
  formulaAssistManyFields.value = [];
  formulaAssistVisible.value = true;
  try {
    const { getAiConfig } = await import("@/api/modules/ai");
    const res = await getAiConfig();
    formulaAssistAiReady.value = !!res.data?.ready;
  } catch {
    formulaAssistAiReady.value = false;
  }
}

function fieldToken(name: string) {
  const col = (name || "").trim();
  if (!col) return "";
  return `[${col}]`;
}

function escapeAssistHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function assistTokenStyle() {
  return [
    "display:inline-flex",
    "align-items:center",
    "gap:6px",
    "margin:0 3px",
    "padding:0 9px 0 7px",
    "height:24px",
    "border-radius:6px",
    "background:#0f766e",
    "color:#fff",
    "border:2px solid #115e59",
    "box-shadow:0 0 0 1px #99f6e4",
    "font-size:12px",
    "font-weight:700",
    "line-height:20px",
    "vertical-align:middle",
    "user-select:none"
  ].join(";");
}

function promptToAssistHtml(text: string) {
  const re = /\[[^[\]]+\]/g;
  let last = 0;
  let html = "";
  let match: RegExpExecArray | null;
  while ((match = re.exec(text))) {
    html += escapeAssistHtml(text.slice(last, match.index));
    const name = match[0].slice(1, -1);
    html += `<span class="etl-assist-token" contenteditable="false" data-field="${escapeAssistHtml(name)}" style="${assistTokenStyle()}"><i class="etl-assist-token__mark" style="width:6px;height:6px;border-radius:50%;background:#5eead4;flex-shrink:0"></i>${escapeAssistHtml(name)}</span>`;
    last = match.index + match[0].length;
  }
  html += escapeAssistHtml(text.slice(last));
  return html;
}

function assistEditorToPrompt(root: HTMLElement) {
  let out = "";
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      out += (node.textContent || "").replace(/\u00a0/g, " ");
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const el = node as HTMLElement;
    if (el.classList.contains("etl-assist-token")) {
      const name = (el.dataset.field || el.textContent || "").trim();
      if (name) out += `[${name}]`;
      return;
    }
    if (el.tagName === "BR") {
      out += "\n";
      return;
    }
    el.childNodes.forEach(walk);
  };
  root.childNodes.forEach(walk);
  return out.replace(/[ \t]+\n/g, "\n").replace(/\s+$/g, "");
}

function syncAssistEmpty(el: HTMLElement) {
  el.toggleAttribute("data-empty", !assistEditorToPrompt(el).trim());
}

function renderAssistEditor() {
  const el = assistEditorEl.value;
  if (!el) return;
  el.innerHTML = promptToAssistHtml(formulaAssistPrompt.value);
  syncAssistEmpty(el);
}

function onAssistEditorInput() {
  if (assistComposing.value) return;
  const el = assistEditorEl.value;
  if (!el) return;
  formulaAssistPrompt.value = assistEditorToPrompt(el);
  syncAssistEmpty(el);
}

function onAssistEditorPaste(event: ClipboardEvent) {
  event.preventDefault();
  const pasted = event.clipboardData?.getData("text/plain") || "";
  document.execCommand("insertText", false, pasted);
  const el = assistEditorEl.value;
  if (!el) return;
  formulaAssistPrompt.value = assistEditorToPrompt(el);
  renderAssistEditor();
}

function placeCaretAfter(node: Node) {
  const sel = window.getSelection();
  if (!sel) return;
  const range = document.createRange();
  range.setStartAfter(node);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
}

function insertChipInEditor(name: string) {
  const el = assistEditorEl.value;
  if (!el) return false;
  el.focus();
  const span = document.createElement("span");
  span.className = "etl-assist-token";
  span.contentEditable = "false";
  span.dataset.field = name;
  span.setAttribute("style", assistTokenStyle());
  span.innerHTML = `<i class="etl-assist-token__mark" style="width:6px;height:6px;border-radius:50%;background:#5eead4;flex-shrink:0"></i>`;
  span.append(document.createTextNode(name));
  const space = document.createTextNode(" ");
  const sel = window.getSelection();
  if (sel && sel.rangeCount && el.contains(sel.anchorNode)) {
    const range = sel.getRangeAt(0);
    range.deleteContents();
    range.insertNode(space);
    range.insertNode(span);
  } else {
    el.appendChild(span);
    el.appendChild(space);
  }
  placeCaretAfter(space);
  formulaAssistPrompt.value = assistEditorToPrompt(el);
  syncAssistEmpty(el);
  return true;
}

function onAssistEditorKeydown(event: KeyboardEvent) {
  if (event.key !== "Backspace" && event.key !== "Delete") return;
  const sel = window.getSelection();
  if (!sel || !sel.isCollapsed || !sel.rangeCount) return;
  const range = sel.getRangeAt(0);
  const node = range.startContainer;
  if (event.key === "Backspace") {
    let target: Node | null = null;
    if (node.nodeType === Node.TEXT_NODE && range.startOffset === 0) {
      target = node.previousSibling;
    } else if (node.nodeType === Node.ELEMENT_NODE && range.startOffset > 0) {
      target = (node as HTMLElement).childNodes[range.startOffset - 1];
    } else if (node.nodeType === Node.TEXT_NODE && range.startOffset > 0) {
      return;
    } else {
      target = node.previousSibling;
    }
    if (
      target instanceof HTMLElement &&
      target.classList.contains("etl-assist-token")
    ) {
      event.preventDefault();
      target.remove();
      onAssistEditorInput();
    }
    return;
  }
  let next: Node | null = null;
  if (node.nodeType === Node.TEXT_NODE && range.startOffset === (node.textContent || "").length) {
    next = node.nextSibling;
  } else if (node.nodeType === Node.ELEMENT_NODE) {
    next = (node as HTMLElement).childNodes[range.startOffset] || null;
  }
  if (next instanceof HTMLElement && next.classList.contains("etl-assist-token")) {
    event.preventDefault();
    next.remove();
    onAssistEditorInput();
  }
}

watch(formulaAssistVisible, visible => {
  if (!visible) return;
  nextTick(() => {
    if (formulaAssistTab.value === "ai") renderAssistEditor();
  });
});

watch(formulaAssistTab, tab => {
  if (tab === "ai") nextTick(() => renderAssistEditor());
});

function insertAssistField(name?: string) {
  const col = (name || formulaAssistField.value || "").trim();
  const token = fieldToken(col);
  if (!token) {
    ElMessage.warning("请先选择原表字段");
    return;
  }
  if (formulaAssistPrompt.value.includes(token)) return;
  if (insertChipInEditor(col)) return;
  const cur = formulaAssistPrompt.value;
  formulaAssistPrompt.value = cur.trim()
    ? `${cur}${/\s$/.test(cur) ? "" : " "}${token}`
    : token;
  nextTick(() => renderAssistEditor());
}

function syncTemplateFieldsFromChips() {
  const cols = formulaAssistManyFields.value;
  formulaAssistField.value = cols[0] || "";
  formulaAssistField2.value = cols[1] || "";
}

/** 模板页：选字段加入绿色卡片（与 AI 芯片同款） */
function onTemplateFieldPick(name?: string) {
  const col = String(name || "").trim();
  if (!col) return;
  const list = formulaAssistManyFields.value;
  if (list.includes(col)) {
    ElMessage.info(`「${col}」已在已选字段中`);
    return;
  }
  if (list.length >= 8) {
    ElMessage.warning("最多选 8 列");
    return;
  }
  formulaAssistManyFields.value = [...list, col];
  syncTemplateFieldsFromChips();
  formulaAssistExplain.value = `已选 ${formulaAssistManyFields.value.length} 列，再点上方模板生成公式`;
  formulaAssistSource.value = "template";
  formulaAssistError.value = "";
}

function removeTemplateField(name: string) {
  formulaAssistManyFields.value = formulaAssistManyFields.value.filter(
    c => c !== name
  );
  syncTemplateFieldsFromChips();
}

/** 全空→空；任一为 1→1；否则 0（支持 2～8 列） */
function buildAnyOneFormula(cols: string[]): string {
  const emptyParts = cols.map(
    c => `(NULLIF(TRIM(CAST([${c}] AS TEXT)), '') IS NULL)`
  );
  const oneParts = cols.map(
    c => `NULLIF(TRIM(CAST([${c}] AS TEXT)), '') = '1'`
  );
  return (
    `CASE WHEN ${emptyParts.join(" AND ")} THEN NULL ` +
    `WHEN ${oneParts.join(" OR ")} THEN 1 ELSE 0 END`
  );
}

function applyFormulaTemplate(key: string) {
  const a = (formulaAssistField.value || "").trim();
  const b = (formulaAssistField2.value || "").trim();
  const qa = a ? `[${a}]` : "";
  const qb = b ? `[${b}]` : "";

  if (key === "any01") {
    const cols = Array.from(
      new Set(
        (formulaAssistManyFields.value.length
          ? formulaAssistManyFields.value
          : [a, b]
        )
          .map(c => String(c || "").trim())
          .filter(Boolean)
      )
    );
    if (cols.length < 2) {
      ElMessage.warning("请先在上方至少选 2 个字段（绿色卡片）");
      return;
    }
    if (cols.length > 8) {
      ElMessage.warning("最多支持 8 列");
      return;
    }
    formulaAssistResult.value = buildAnyOneFormula(cols);
    formulaAssistExplain.value = `模板：${cols.join(
      "、"
    )} 全空→空；任一为1→1；否则→0`;
    formulaAssistSource.value = "template";
    formulaAssistSuggestLevel.value = 1;
    formulaAssistError.value = "";
    return;
  }

  if (key === "concat") {
    if (!a || !b) {
      ElMessage.warning("拼接请先选两列");
      return;
    }
    formulaAssistResult.value = `${qa} || '-' || ${qb}`;
    formulaAssistExplain.value = `模板：拼接「${a}」与「${b}」，中间横杠`;
    formulaAssistSource.value = "template";
    formulaAssistSuggestLevel.value = 1;
    formulaAssistError.value = "";
    return;
  }

  // 单列模板：主列为空时可用「再选一列」
  const col = a || b;
  if (!col) {
    ElMessage.warning("请先选择原表字段");
    return;
  }
  if (!a && b) {
    formulaAssistField.value = b;
  }
  const qcol = `[${col}]`;

  const map: Record<string, { formula: string; explain: string }> = {
    mid567: {
      formula: `SUBSTRING(${qcol} FROM 5 FOR 3)`,
      explain: `模板：提取「${col}」第 5、6、7 位`
    },
    mid1314: {
      formula: `SUBSTRING(${qcol} FROM 13 FOR 2)`,
      explain: `模板：提取「${col}」第 13、14 位`
    },
    trim: {
      formula: `TRIM(${qcol})`,
      explain: `模板：去掉「${col}」首尾空格`
    },
    upper: {
      formula: `UPPER(${qcol})`,
      explain: `模板：「${col}」转大写`
    },
    okng: {
      formula: `CASE WHEN UPPER(TRIM(${qcol})) = 'OK' THEN '合格' ELSE '不合格' END`,
      explain: `模板：「${col}」为 OK→合格，否则不合格`
    },
    bool01: {
      formula: `CASE WHEN NULLIF(TRIM(${qcol}), '') = '1' THEN '不良' WHEN NULLIF(TRIM(${qcol}), '') = '0' THEN '良' ELSE NULL END`,
      explain: `模板：「${col}」1→不良，0→良`
    }
  };
  const hit = map[key];
  if (!hit) return;
  formulaAssistResult.value = hit.formula;
  formulaAssistExplain.value = hit.explain;
  formulaAssistSource.value = "template";
  formulaAssistSuggestLevel.value = 1;
  formulaAssistError.value = "";
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
    const available = [
      ...sourceFields.value.map(f => f.source_field),
      ...fields.value.map(f => f.target_field).filter(Boolean)
    ];
    const res = await generateEtlFormula(model.value.id, {
      prompt: formulaAssistPrompt.value.trim(),
      hint_field:
        formulaAssistField.value ||
        formulaAssistTarget.value?.source_field ||
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
      formulaAssistSuggestLevel.value = Number(data.suggest_level) || 1;
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
  row.mapping_type = "derived";
  row.formula = formulaAssistResult.value;
  row.derive_level = formulaAssistSuggestLevel.value === 2 ? 2 : 1;
  if (!row.target_field) row.target_field = "derived_col";
  formulaAssistVisible.value = false;
  ElMessage.success("已填入公式，可再微调");
}

async function onClearFields() {
  if (!model.value) return;
  if (!fields.value.length) {
    ElMessage.info("当前没有字段配置");
    return;
  }
  try {
    await ElMessageBox.confirm(
      "将清空全部字段映射，模型恢复为草稿并停用。可再「从源表导入」重新配置。",
      "清空配置",
      { type: "warning", confirmButtonText: "清空", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  saving.value = true;
  try {
    const res = await clearEtlFields(model.value.id);
    model.value = res.data;
    sourceFields.value = [];
    fields.value = [];
    sqlText.value = "";
    fieldFilter.value = "";
    typeFilter.value = "all";
    editorStage.value = "types";
    ElMessage.success("已清空，可重新配置");
    await load(true);
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    saving.value = false;
  }
}

async function onImportDirect() {
  if (!model.value) return;
  if (fields.value.length) {
    try {
      await ElMessageBox.confirm(
        "将用源表全部原始字段名覆盖当前配置（仅导入字段信息，不生成 SQL）。请再逐列设置类型后保存。",
        "从源表导入",
        { type: "warning" }
      );
    } catch {
      return;
    }
  }
  saving.value = true;
  try {
    const res = await importDirectFields(model.value.id);
    model.value = res.data;
    sourceFields.value = (res.data.source_fields || []).map((f, i) => ({
      source_field: f.source_field,
      field_type: f.field_type || "text",
      sort_order: f.sort_order ?? i
    }));
    fields.value = []; // 清洗表不自动生成
    sqlText.value = "";
    editorStage.value = "types";
    typeFilter.value = "all";
    await loadSourceColumns(model.value.id);
    ElMessage.success(
      `已导入 ${sourceFields.value.length} 个原表字段。配好类型后点「下一步」手动配置清洗表字段`
    );
    await load(true);
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    saving.value = false;
  }
}

async function onReanalyzeTypes() {
  if (!model.value) return;
  saving.value = true;
  try {
    const res = await reanalyzeSourceFields(model.value.id);
    model.value = res.data;
    sourceFields.value = (res.data.source_fields || []).map((f, i) => ({
      source_field: f.source_field,
      field_type: f.field_type || "text",
      sort_order: f.sort_order ?? i
    }));
    typeFilter.value = "all";
    ElMessage.success(
      `已按列名+采样重新识别 ${sourceFields.value.length} 列类型（线体等维度为文本，0/1 结果为布尔）`
    );
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    saving.value = false;
  }
}

async function onSaveAll() {
  if (!model.value) return;
  if (!fields.value.length) {
    ElMessage.warning("请先手动添加清洗表字段");
    return;
  }
  saving.value = true;
  try {
    // 同步原表类型
    await saveEtlSourceFields(
      model.value.id,
      sourceFields.value.map((f, i) => ({
        source_field: f.source_field,
        field_type: f.field_type || "text",
        sort_order: i
      }))
    );
    await updateEtlModel(model.value.id, {
      unique_key: model.value.unique_key,
      incremental_field: model.value.incremental_field || "ingested_at",
      name: model.value.name
    });
    const payload = fields.value.map((f, i) => {
      const source = (f.source_field || "").trim();
      const target = (f.target_field || "").trim();
      if (f.mapping_type === "direct" && !source) {
        throw new Error(`第 ${i + 1} 列：直接映射必须选择原表字段`);
      }
      if (!target) {
        throw new Error(`第 ${i + 1} 列：请填写清洗表字段名`);
      }
      return {
        ...f,
        sort_order: i,
        source_field: source,
        target_field: target,
        field_type:
          f.field_type ||
          sourceTypeMap.value[source] ||
          "text",
        derive_level:
          f.mapping_type === "derived" ? Number(f.derive_level) || 1 : 1
      };
    });
    const res = await saveEtlFields(model.value.id, payload);
    model.value = res.data;
    fields.value = res.data.fields || [];
    sourceFields.value = res.data.source_fields || sourceFields.value;
    // 保存瞬间即重写 sql 文件；改公式只改页面，点本按钮才落盘
    sqlText.value = res.data.sql_preview || "";
    if (!sqlText.value && model.value?.id) {
      try {
        const sqlRes = await getSqlPreview(model.value.id);
        sqlText.value = sqlRes.data.sql || "";
      } catch {
        /* 预览失败不挡保存成功 */
      }
    }
    ElMessage.success(
      sqlText.value
        ? "已保存字段，SQL 已立即更新"
        : "已保存字段并生成 SQL"
    );
    await load(true);
  } catch (error) {
    ElMessage.error(
      error instanceof Error ? error.message : backendErrorHint(error)
    );
  } finally {
    saving.value = false;
  }
}

async function onToggleEnable(enabled: boolean) {
  if (!model.value) return;
  saving.value = true;
  try {
    const res = await updateEtlModel(model.value.id, {
      is_enabled: enabled,
      unique_key: model.value.unique_key,
      incremental_field: model.value.incremental_field || "ingested_at"
    });
    model.value = { ...res.data, fields: fields.value };
    ElMessage.success(enabled ? "已启用，可执行清洗" : "已停用");
    await load(true);
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    saving.value = false;
  }
}

async function onPreviewSql() {
  if (!model.value) return;
  try {
    if (fields.value.length && (model.value.is_draft || !sqlText.value)) {
      ElMessage.info("建议先点「保存并生成 SQL」，当前展示已保存版本");
    }
    const res = await getSqlPreview(model.value.id);
    sqlText.value = res.data.sql || "";
    if (!sqlText.value) {
      ElMessage.warning("暂无 SQL，请先保存字段");
      return;
    }
    sqlOpen.value = true;
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  }
}

async function onPreviewData() {
  if (!model.value) return;
  editorLoading.value = true;
  try {
    const res = await previewEtlData(model.value.id, 50);
    previewCols.value = res.data.columns || [];
    previewRows.value = res.data.rows || [];
    sqlText.value = res.data.sql || sqlText.value;
    previewOpen.value = true;
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    editorLoading.value = false;
  }
}

function formatElapsed(ms: number) {
  const sec = Math.max(0, Math.floor(ms / 1000));
  if (sec < 60) return `${sec} 秒`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m} 分 ${s} 秒`;
}

function runTargetLabel(opts?: { projectId?: string; modelId?: number }) {
  if (!opts?.projectId && !opts?.modelId) return "全部已启用模型";
  const row = rows.value.find(
    r =>
      (opts.projectId && r.project_id === opts.projectId) ||
      (opts.modelId && r.model_id === opts.modelId)
  );
  return (
    row?.display_name ||
    model.value?.display_name ||
    model.value?.name ||
    opts.projectId ||
    "当前模型"
  );
}

function stopRunTimers() {
  if (runElapsedTimer) {
    clearInterval(runElapsedTimer);
    runElapsedTimer = null;
  }
  if (runBarHideTimer) {
    clearTimeout(runBarHideTimer);
    runBarHideTimer = null;
  }
}

function startRunBar(mode: string, target: string) {
  stopRunTimers();
  const started = Date.now();
  runBar.visible = true;
  runBar.mode = mode;
  runBar.target = target;
  runBar.jobId = 0;
  runBar.status = "queued";
  runBar.percent = 8;
  runBar.indeterminate = true;
  runBar.done = false;
  runBar.text = "正在提交任务…";
  runElapsed.value = "0 秒";
  runElapsedTimer = setInterval(() => {
    runElapsed.value = formatElapsed(Date.now() - started);
  }, 1000);
}

function applyJobToBar(job: EtlJob) {
  runBar.jobId = job.id;
  runBar.status = job.status;
  const result = job.result || {};
  const msg = String(result.message || job.message || "").trim();
  if (job.status === "queued") {
    runBar.percent = 22;
    runBar.indeterminate = true;
    runBar.done = false;
    runBar.text = "已排队，等待 Worker 领取…";
    return;
  }
  if (job.status === "running") {
    runBar.percent = 68;
    runBar.indeterminate = true;
    runBar.done = false;
    runBar.text = msg || "Worker 正在清洗并写入…";
    return;
  }
  runBar.indeterminate = false;
  runBar.done = true;
  runBar.percent = 100;
  if (job.status === "success") {
    const total = Number(result.total_rows ?? result.rows ?? 0) || 0;
    runBar.text =
      msg ||
      (total ? `清洗完成，写入 ${total.toLocaleString()} 行` : "清洗完成");
  } else {
    runBar.text = msg || "清洗失败";
  }
}

function finishRunBar(ok: boolean, text?: string) {
  stopRunTimers();
  runBar.indeterminate = false;
  runBar.done = true;
  runBar.percent = 100;
  if (text) runBar.text = text;
  if (!runBar.status || runBar.status === "queued" || runBar.status === "running") {
    runBar.status = ok ? "success" : "failed";
  }
  if (ok) {
    runBarHideTimer = setTimeout(() => {
      runBar.visible = false;
    }, 8000);
  }
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
    const res = await runEtl(opts);
    const data = res?.data;
    if (!data?.accepted || !data.job_id) {
      finishRunBar(false, data?.message || "无法入队");
      ElMessage.warning(data?.message || "无法入队");
      return;
    }
    runBar.jobId = data.job_id;
    runBar.text = `任务 #${data.job_id} 已提交，等待 Worker…`;
    const job = await waitForEtlJob(data.job_id, {
      onUpdate: applyJobToBar
    });
    applyJobToBar(job);
    if (job.status === "success") {
      const result = job.result || {};
      const total = Number(result.total_rows ?? result.rows ?? 0) || 0;
      const doneText =
        String(result.message || "") ||
        (total
          ? `清洗完成，写入 ${total.toLocaleString()} 行`
          : job.message || "清洗完成");
      finishRunBar(true, doneText);
      ElMessage.success(doneText);
    } else {
      finishRunBar(false, job.message || "清洗失败");
      ElMessage.error(job.message || "清洗失败");
    }
    await load(true);
    if (activeTab.value === "logs") await loadLogs(true);
    if (model.value && opts?.modelId === model.value.id) {
      const refreshed = await getEtlModel(model.value.id);
      model.value = { ...refreshed.data, fields: fields.value };
    }
  } catch (error) {
    finishRunBar(false, backendErrorHint(error));
    ElMessage.error(backendErrorHint(error));
  } finally {
    running.value = false;
    await load(true);
    if (activeTab.value === "logs") await loadLogs(true);
  }
}

async function onRunFull(opts?: { projectId?: string; modelId?: number }) {
  try {
    await ElMessageBox.confirm(
      "将删除并重建清洗表，处理原表全部数据。日常请用增量清洗。",
      "全量重建",
      { type: "warning", confirmButtonText: "全量重建", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  await onRun({ ...opts, fullRefresh: true });
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    success: "成功",
    failed: "失败",
    running: "进行中",
    queued: "已排队",
    busy: "忙碌",
    skipped: "已跳过",
    partial: "部分成功"
  };
  return map[status] || status || "—";
}

function formatEtlMessage(row: EtlProjectRow) {
  const raw = String(row.last_etl_message || "").trim();
  const table = row.target_table || "";
  const n = Number(row.last_etl_rows) || 0;
  const count = n ? `${n.toLocaleString()} 行` : "";
  if (!raw) {
    if (row.last_etl_status === "success" && table) {
      return count ? `已写入 ${table}（${count}）` : `已写入 ${table}`;
    }
    return "—";
  }
  const okArrow = raw.match(/^ok\s*→\s*(.+)$/i);
  if (okArrow) {
    const dest = okArrow[1].trim();
    return count ? `已写入 ${dest}（${count}）` : `已写入 ${dest}`;
  }
  if (/^ok\b/i.test(raw) && table) {
    return count ? `已写入 ${table}（${count}）` : `已写入 ${table}`;
  }
  return raw;
}

onMounted(async () => {
  try {
    const res = await getEtlFieldTypes();
    if (res.data?.types?.length) fieldTypeOptions.value = res.data.types;
  } catch {
    /* keep defaults */
  }
  await load();
});

onUnmounted(() => {
  stopRunTimers();
});
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
        <el-button
          v-if="runBar.done"
          link
          type="info"
          @click="runBar.visible = false"
        >
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
        <h2>数据清洗</h2>
        <p>默认只处理原表更新，按唯一键写入 lim_dwh；映射变更后请全量重建。</p>
      </div>
      <div class="etl-head__actions">
        <el-button :loading="running" @click="onRunFull()">全量重建全部</el-button>
        <el-button type="primary" :loading="running" @click="onRun()">
          增量清洗全部
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
      :title="`当前有清洗任务 #${activeJobId} 排队或执行中`"
      show-icon
      class="etl-alert"
    />

    <template v-if="!editorOpen">
      <el-tabs
        v-model="activeTab"
        class="etl-tabs"
        @tab-change="onTabChange"
      >
        <el-tab-pane label="清洗配置" name="config">
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
          <span class="etl-stat__label">最近写入合计</span>
          <strong>{{ totalLastRows.toLocaleString() }}</strong>
        </div>
      </section>

      <section class="etl-panel etl-schedule">
        <div class="etl-schedule__head">
          <div>
            <h3>自动运行</h3>
            <p>开启后 Worker 按间隔投递「全部已启用模型」清洗任务（需保持 worker 运行）。</p>
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
            <span>启用自动清洗</span>
            <el-switch v-model="scheduler.is_active" />
          </div>
          <div class="etl-schedule__item">
            <span>间隔（分钟）</span>
            <el-input-number
              v-model="scheduler.run_interval"
              :min="1"
              :max="1440"
              :step="5"
            />
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
        <div v-if="scheduler.last_run_time || scheduler.last_run_message" class="etl-schedule__meta">
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
            <p>自动运行与「增量」只处理原表更新；改映射后请点「全量」。</p>
          </div>
        </div>
        <el-table
          :data="rows"
          border
          stripe
          empty-text="暂无项目"
          class="etl-list-table"
        >
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
          <el-table-column label="映射" width="96" align="center">
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
          <el-table-column label="最近清洗" min-width="200">
            <template #default="{ row }">
              <div class="etl-run-cell">
                <el-tag
                  v-if="row.last_etl_status"
                  size="small"
                  :type="statusType(row.last_etl_status)"
                  effect="light"
                >
                  {{ statusLabel(row.last_etl_status) }}
                </el-tag>
                <span class="etl-run-cell__time">{{
                  row.last_etl_time || "尚未清洗"
                }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="结果" min-width="260">
            <template #default="{ row }">
              <span class="etl-result-text">{{ formatEtlMessage(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="210" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEditor(row)">
                配置
              </el-button>
              <el-button
                link
                type="primary"
                :disabled="!row.can_run || running"
                @click="
                  onRun({ projectId: row.project_id, modelId: row.model_id })
                "
              >
                增量
              </el-button>
              <el-button
                link
                :disabled="!row.can_run || running"
                @click="
                  onRunFull({
                    projectId: row.project_id,
                    modelId: row.model_id
                  })
                "
              >
                全量
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
        </el-tab-pane>

        <el-tab-pane label="运行日志" name="logs">
          <section class="etl-panel etl-logs-hero">
            <div class="etl-panel__head">
              <div>
                <h2>运行状态</h2>
                <p>查看最近清洗结果，或立即发起一轮</p>
              </div>
              <div class="etl-panel__actions">
                <el-button
                  type="primary"
                  :loading="running"
                  :disabled="!enabledCount"
                  @click="onRun()"
                >
                  增量清洗全部
                </el-button>
                <el-button
                  :loading="running"
                  :disabled="!enabledCount"
                  @click="onRunFull()"
                >
                  全量重建全部
                </el-button>
                <el-button :loading="logsLoading" @click="loadLogs()">
                  刷新
                </el-button>
              </div>
            </div>
            <div class="etl-stats etl-logs-stats">
              <div
                class="etl-stat"
                :class="running || activeJobId ? 'is-busy' : 'is-idle'"
              >
                <span class="etl-stat__label">当前状态</span>
                <strong>{{
                  running || activeJobId ? "清洗中" : "空闲"
                }}</strong>
                <span class="etl-stat__hint">
                  {{
                    scheduler.is_active
                      ? `定时每 ${scheduler.run_interval} 分钟`
                      : "定时关闭"
                  }}
                </span>
              </div>
              <div class="etl-stat">
                <span class="etl-stat__label">上次结果</span>
                <strong class="etl-stat__tag">
                  <el-tag
                    v-if="logsStatus"
                    size="small"
                    :type="statusType(logsStatus)"
                    effect="light"
                    round
                  >
                    {{ statusLabel(logsStatus) }}
                  </el-tag>
                  <span v-else class="muted">尚未运行</span>
                </strong>
                <span class="etl-stat__hint">最近一轮清洗</span>
              </div>
              <div class="etl-stat">
                <span class="etl-stat__label">上次时间</span>
                <strong class="etl-stat__time">{{
                  dash(logsTime)
                }}</strong>
                <span class="etl-stat__hint">完成或失败时间</span>
              </div>
              <div class="etl-stat">
                <span class="etl-stat__label">可自动跑</span>
                <strong>
                  {{ enabledCount }}
                  <span class="etl-stat__unit">模型</span>
                </strong>
                <span class="etl-stat__hint">已启用且可执行</span>
              </div>
            </div>
          </section>

          <section class="etl-panel" v-loading="logsLoading">
            <div class="etl-panel__head">
              <div>
                <h2>运行日志</h2>
                <p>展开行可查看逐步明细（触发方式、模式、写入行数与耗时）</p>
              </div>
              <div class="etl-panel__actions">
                <span class="etl-count">{{ logs.length }} 条记录</span>
                <el-button :disabled="!logs.length" @click="onClearLogs">
                  清除日志
                </el-button>
              </div>
            </div>

            <div v-if="!logs.length" class="etl-logs-empty">
              <div class="etl-logs-empty__mark" aria-hidden="true">
                <span /><span /><span />
              </div>
              <div class="etl-logs-empty__title">还没有运行记录</div>
              <div class="etl-logs-empty__desc">
                发起一轮清洗，或开启自动清洗后，这里会按时间列出每次结果
              </div>
              <div class="etl-logs-empty__actions">
                <el-button
                  type="primary"
                  :loading="running"
                  :disabled="!enabledCount"
                  @click="onRun()"
                >
                  增量清洗全部
                </el-button>
                <el-button
                  :loading="running"
                  :disabled="!enabledCount"
                  @click="onRunFull()"
                >
                  全量重建全部
                </el-button>
              </div>
              <p v-if="!enabledCount" class="etl-logs-empty__tip">
                暂无已启用模型：先到「清洗配置」完成字段映射并启用
              </p>
            </div>

            <el-table v-else :data="logs" class="etl-list-table etl-logs-table">
              <el-table-column type="expand">
                <template #default="{ row }">
                  <div
                    v-if="row.detail?.lines?.length"
                    class="etl-log-lines"
                  >
                    <div
                      v-for="(line, idx) in row.detail.lines"
                      :key="idx"
                      class="etl-log-line"
                      :class="`is-${line.level || 'info'}`"
                    >
                      <span class="etl-log-time">{{ dash(line.time) }}</span>
                      <span class="etl-log-level">{{
                        line.level || "info"
                      }}</span>
                      <span class="etl-log-msg">{{
                        dash(line.message)
                      }}</span>
                    </div>
                  </div>
                  <div v-else class="muted etl-log-empty">无明细</div>
                </template>
              </el-table-column>
              <el-table-column label="开始" min-width="160">
                <template #default="{ row }">
                  <span class="etl-time-cell">{{
                    dash(row.started_at)
                  }}</span>
                </template>
              </el-table-column>
              <el-table-column label="结束" min-width="160">
                <template #default="{ row }">
                  <span class="etl-time-cell">{{
                    dash(row.ended_at)
                  }}</span>
                </template>
              </el-table-column>
              <el-table-column label="来源" width="96" align="center">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain" round>
                    {{ triggerLabel(row.trigger) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="模式" width="96" align="center">
                <template #default="{ row }">
                  <el-tag
                    size="small"
                    :type="row.run_mode === 'full' ? 'warning' : 'primary'"
                    effect="light"
                    round
                  >
                    {{ modeLabel(row.run_mode) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100" align="center">
                <template #default="{ row }">
                  <el-tag
                    size="small"
                    :type="statusType(row.status)"
                    effect="light"
                    round
                  >
                    {{ statusLabel(row.status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="写入行数" width="110" align="right">
                <template #default="{ row }">
                  <span class="etl-num-cell">{{
                    Number(row.rows_affected || 0).toLocaleString()
                  }}</span>
                </template>
              </el-table-column>
              <el-table-column label="耗时" width="100" align="right">
                <template #default="{ row }">
                  <span class="etl-num-cell">{{
                    formatDuration(row.duration)
                  }}</span>
                </template>
              </el-table-column>
              <el-table-column label="说明" min-width="220">
                <template #default="{ row }">
                  <span class="msg-cell">{{ dash(row.message) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>
      </el-tabs>
    </template>

    <section v-else class="etl-panel etl-editor" v-loading="editorLoading">
      <header class="etl-panel__head">
        <div>
          <h2>{{ model?.display_name || model?.name || "字段映射" }}</h2>
          <p>
            {{ model?.source_table }} → {{ model?.target_table }}
            <el-tag
              v-if="model"
              size="small"
              class="ml-2"
              :type="model.is_draft ? 'warning' : 'success'"
            >
              {{ model.is_draft ? "草稿" : "已生成 SQL" }}
            </el-tag>
            <span class="etl-count">
              原表 {{ sourceFields.length }} 列
              <template v-if="typeCountText">（{{ typeCountText }}）</template>
              · 清洗表 {{ fields.length }} 列
            </span>
          </p>
        </div>
        <div class="etl-panel__actions">
          <el-button @click="closeEditor">返回列表</el-button>
          <el-button
            type="primary"
            :loading="running"
            :disabled="!model?.can_run"
            @click="onRun({ modelId: model?.id, projectId: model?.project_id })"
          >
            增量清洗
          </el-button>
          <el-button
            :loading="running"
            :disabled="!model?.can_run"
            @click="
              onRunFull({ modelId: model?.id, projectId: model?.project_id })
            "
          >
            全量重建
          </el-button>
        </div>
      </header>

      <ol class="etl-steps">
        <li :class="{ active: stepIndex === 0, done: stepIndex > 0 }">
          1. 导入原表字段
        </li>
        <li :class="{ active: stepIndex === 1, done: stepIndex > 1 }">
          2. 配置原表类型
        </li>
        <li :class="{ active: stepIndex === 2, done: stepIndex > 2 }">
          3. 配置清洗表字段
        </li>
        <li :class="{ active: stepIndex >= 3, done: stepIndex > 3 }">
          4. 生成 SQL / 启用清洗
        </li>
      </ol>

      <!-- 页1：原表类型；页2：清洗表字段（点下一步才进入） -->
      <div class="etl-config-bar" v-if="model && editorStage === 'mapping'">
        <el-form label-position="top" class="etl-meta-form" @submit.prevent>
          <div class="etl-grid">
            <el-form-item label="模型名称">
              <el-input v-model="model.name" />
            </el-form-item>
            <el-form-item label="表路径" class="etl-meta-path">
              <div class="etl-meta-path__flow" :title="`${model.source_table} → ${model.target_table}`">
                <code class="etl-meta-path__table">{{ model.source_table }}</code>
                <span class="etl-meta-path__arrow" aria-hidden="true">→</span>
                <code class="etl-meta-path__table">{{ model.target_table }}</code>
              </div>
            </el-form-item>
            <el-form-item label="唯一键（清洗表）">
              <el-select
                v-model="model.unique_key"
                filterable
                allow-create
                default-first-option
                placeholder="增量写入必填"
                style="width: 100%"
              >
                <el-option
                  v-for="col in uniqueKeyOptions"
                  :key="col"
                  :label="col"
                  :value="col"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="增量水位（原表）">
              <el-select
                v-model="model.incremental_field"
                filterable
                allow-create
                default-first-option
                placeholder="ingested_at"
                style="width: 100%"
              >
                <el-option
                  v-for="col in incrementalFieldOptions"
                  :key="col"
                  :label="col === 'ingested_at' ? 'ingested_at（入库时间）' : col"
                  :value="col"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="启用模型">
              <div class="etl-enable">
                <el-switch
                  :model-value="model.is_enabled"
                  :disabled="!canEnable && !model.is_enabled"
                  @change="v => onToggleEnable(switchValue(v))"
                />
                <span class="muted">
                  {{
                    canEnable || model.is_enabled
                      ? "启用后才能清洗"
                      : "请先保存并生成 SQL"
                  }}
                </span>
              </div>
            </el-form-item>
          </div>
        </el-form>
      </div>

      <div class="etl-toolbar sticky">
        <div class="etl-toolbar__left">
          <template v-if="editorStage === 'types'">
            <el-button
              type="primary"
              plain
              :loading="saving"
              @click="onImportDirect"
            >
              {{ sourceFields.length ? "重新导入字段名" : "从源表导入字段名" }}
            </el-button>
            <el-button
              plain
              :loading="saving"
              :disabled="!sourceFields.length"
              @click="onReanalyzeTypes"
            >
              重新识别类型
            </el-button>
            <el-button
              type="danger"
              plain
              :loading="saving"
              :disabled="!sourceFields.length"
              @click="onClearFields"
            >
              清空
            </el-button>
            <el-dropdown
              v-if="sourceFields.length"
              trigger="click"
              @command="(cmd: string) => setAllFieldType(cmd)"
            >
              <el-button>批量设类型</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="opt in fieldTypeOptions"
                    :key="opt.value"
                    :command="opt.value"
                  >
                    全部设为{{ opt.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
          <template v-else>
            <el-button @click="goTypesStage">上一步</el-button>
            <el-button type="primary" plain @click="addField">
              添加清洗列
            </el-button>
          </template>
          <el-input
            v-model="fieldFilter"
            clearable
            placeholder="搜索字段…"
            class="etl-search"
          />
          <PageTabs
            v-model="typeFilter"
            :options="typeFilterTabs"
            size="small"
            aria-label="字段筛选"
          />
        </div>
        <div class="etl-toolbar__right">
          <template v-if="editorStage === 'types'">
            <el-button
              type="primary"
              :loading="saving"
              :disabled="!sourceFields.length"
              @click="goMappingStage"
            >
              下一步：配置清洗表字段
            </el-button>
          </template>
          <template v-else>
            <el-button @click="onPreviewSql">SQL</el-button>
            <el-button @click="onPreviewData">预览数据</el-button>
            <el-button
              type="primary"
              :loading="saving"
              :disabled="!fields.length"
              @click="onSaveAll"
            >
              保存并生成 SQL
            </el-button>
          </template>
        </div>
      </div>

      <div v-if="editorStage === 'types' && !sourceFields.length" class="etl-empty">
        <p>
          第 1 页：导入原表字段名并配置类型。完成后点「下一步」——清洗表字段需你自己添加，不会自动生成。
        </p>
        <el-button type="primary" :loading="saving" @click="onImportDirect">
          从源表导入字段名
        </el-button>
      </div>

      <div
        v-else-if="editorStage === 'mapping' && !fields.length"
        class="etl-empty"
      >
        <p>
          清洗表字段不会自动生成。请点「添加清洗列」，选择原表字段并填写清洗表字段名。
        </p>
        <el-button type="primary" @click="addField">添加清洗列</el-button>
      </div>

      <!-- ① 原表类型：两列网格，避免单列过宽 -->
      <div
        v-else-if="editorStage === 'types'"
        class="etl-type-grid-wrap"
      >
        <div v-if="!filteredSourceFields.length" class="etl-empty-inline">
          无匹配字段
        </div>
        <div v-else class="etl-type-grid">
          <div
            v-for="row in filteredSourceFields"
            :key="row.index"
            class="etl-type-card"
          >
            <span class="etl-type-card__idx">{{ row.index + 1 }}</span>
            <code class="etl-src-name" :title="row.f.source_field">{{
              row.f.source_field
            }}</code>
            <el-select v-model="row.f.field_type" size="small" class="etl-type-card__select">
              <el-option
                v-for="opt in fieldTypeOptions"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
          </div>
        </div>
      </div>

      <!-- ② 清洗表字段表 -->
      <div v-else class="etl-table-wrap">
      <el-table
        :data="filteredFields"
        border
        stripe
        height="100%"
        row-key="index"
        empty-text="无匹配字段"
        class="etl-fields-table"
      >
        <el-table-column label="#" width="52" align="center">
          <template #default="{ row }">
            <span class="muted">{{ row.index + 1 }}</span>
          </template>
        </el-table-column>
        <el-table-column label="清洗表字段" width="140">
          <template #default="{ row }">
            <el-input
              v-model="row.f.target_field"
              size="small"
              placeholder="写入 dwd 的列名"
            />
          </template>
        </el-table-column>
        <el-table-column label="映射方式" width="110">
          <template #default="{ row }">
            <el-select
              v-model="row.f.mapping_type"
              size="small"
              @change="onMappingChange(row.f)"
            >
              <el-option
                v-for="opt in mappingOptions"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="原表字段" width="160">
          <template #default="{ row }">
            <el-select
              v-if="row.f.mapping_type === 'direct'"
              v-model="row.f.source_field"
              size="small"
              filterable
              clearable
              placeholder="选择原表字段"
              style="width: 100%"
              @change="(v: string) => onCleanSourcePick(row.f, v)"
            >
              <el-option
                v-for="col in sourceFields"
                :key="col.source_field"
                :label="`${col.source_field}（${fieldTypeOptions.find(t => t.value === col.field_type)?.label || col.field_type}）`"
                :value="col.source_field"
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
        <el-table-column label="公式 / 固定值" min-width="360">
          <template #default="{ row }">
            <div v-if="row.f.mapping_type === 'derived'" class="etl-formula">
              <el-input
                v-model="row.f.formula"
                size="small"
                placeholder='如 LEFT([FCoverSN], 3)'
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
            <el-input
              v-else-if="row.f.mapping_type === 'constant'"
              v-model="row.f.constant_value"
              size="small"
              placeholder="固定值"
            />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="层级" width="80">
          <template #default="{ row }">
            <el-select
              v-model="row.f.derive_level"
              size="small"
              :disabled="row.f.mapping_type !== 'derived'"
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

      <p class="etl-tip">
        <template v-if="editorStage === 'types'">
          第 1 页只配置原表字段类型。点「下一步」进入清洗表配置——不会自动带入列，需手动添加。
        </template>
        <template v-else>
          第 2 页请手动「添加清洗列」：选原表字段、填清洗表字段名，可选派生公式。配好后点「保存并生成 SQL」。
        </template>
      </p>
    </section>

    <el-dialog v-model="sqlOpen" title="生成的 SQL" width="720px" destroy-on-close>
      <pre class="etl-sql-dialog">{{ sqlText }}</pre>
    </el-dialog>

    <el-dialog v-model="previewOpen" title="数据预览（前 50 行）" width="80%">
      <el-table
        :data="previewRows"
        border
        stripe
        max-height="480"
        empty-text="无数据"
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

    <el-dialog
      v-model="formulaAssistVisible"
      class="etl-assist-dialog"
      width="640px"
      destroy-on-close
      append-to-body
      align-center
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
        <el-tab-pane label="AI 描述" name="ai" lazy>
          <template v-if="formulaAssistTab === 'ai'">
            <p class="etl-assist-lead">
              选字段写入描述，用中文说明需求。已配置 AI 时优先由模型生成。
              <router-link class="etl-assist-link" to="/feature/ai-model">
                去配置 AI 模型
              </router-link>
            </p>
            <div class="etl-assist-fields">
              <div class="etl-assist-field">
                <span class="etl-assist-label">原表字段</span>
                <el-select
                  v-model="formulaAssistField"
                  filterable
                  clearable
                  teleported
                  placement="bottom-start"
                  popper-class="etl-assist-select-popper"
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
                  teleported
                  placement="bottom-start"
                  popper-class="etl-assist-select-popper"
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
            <div
              ref="assistEditorEl"
              class="etl-assist-editor"
              contenteditable="true"
              spellcheck="false"
              data-placeholder="先点上方字段插入芯片，再写「取前3位」这类中文。退格会整块删除字段。"
              data-empty="true"
              @input="onAssistEditorInput"
              @keydown="onAssistEditorKeydown"
              @paste="onAssistEditorPaste"
              @compositionstart="assistComposing = true"
              @compositionend="
                assistComposing = false;
                onAssistEditorInput();
              "
              @blur="renderAssistEditor"
            ></div>
            <div class="etl-assist-actions">
              <el-button
                type="primary"
                :loading="formulaAssistLoading"
                @click="runFormulaAssist"
              >
                {{ formulaAssistAiReady ? "AI 生成公式" : "生成公式" }}
              </el-button>
            </div>
          </template>
        </el-tab-pane>

        <el-tab-pane label="模板" name="template" lazy>
          <template v-if="formulaAssistTab === 'template'">
            <p class="etl-assist-lead">
              选字段加入绿色卡片（最多 8 个），再点模板填出公式。「有1为1」用卡片里全部列。
            </p>
            <div class="etl-assist-fields">
              <div class="etl-assist-field">
                <span class="etl-assist-label">添加字段</span>
                <el-select
                  filterable
                  clearable
                  teleported
                  placement="bottom-start"
                  popper-class="etl-assist-select-popper"
                  placeholder="选择后加入已选卡片"
                  style="width: 100%"
                  :model-value="''"
                  @change="onTemplateFieldPick"
                >
                  <el-option
                    v-for="opt in formulaAssistFieldOptions"
                    :key="`t-${opt.value}`"
                    :label="opt.label"
                    :value="opt.value"
                    :disabled="formulaAssistManyFields.includes(opt.value)"
                  />
                </el-select>
              </div>
              <div class="etl-assist-field">
                <span class="etl-assist-label">再加一列</span>
                <el-select
                  filterable
                  clearable
                  teleported
                  placement="bottom-start"
                  popper-class="etl-assist-select-popper"
                  placeholder="继续添加"
                  style="width: 100%"
                  :model-value="''"
                  @change="onTemplateFieldPick"
                >
                  <el-option
                    v-for="opt in formulaAssistFieldOptions"
                    :key="`t2-${opt.value}`"
                    :label="opt.label"
                    :value="opt.value"
                    :disabled="formulaAssistManyFields.includes(opt.value)"
                  />
                </el-select>
              </div>
            </div>
            <div class="etl-assist-chips">
              <span class="etl-assist-label">已选字段</span>
              <div
                class="etl-assist-editor etl-assist-chips__box"
                :data-empty="formulaAssistManyFields.length ? null : 'true'"
                data-placeholder="从上方选择字段，会出现绿色卡片"
              >
                <span
                  v-for="name in formulaAssistManyFields"
                  :key="name"
                  class="etl-assist-token etl-assist-token--chip"
                >
                  <i class="etl-assist-token__mark" />
                  <span class="etl-assist-token__name">{{ name }}</span>
                  <button
                    type="button"
                    class="etl-assist-token__x"
                    :aria-label="`移除 ${name}`"
                    :title="`移除 ${name}`"
                    @click.stop="removeTemplateField(name)"
                  >
                    ×
                  </button>
                </span>
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
                <span class="etl-assist-template__need">
                  {{
                    tip.need === "two"
                      ? "两列"
                      : tip.need === "many"
                        ? "2～8"
                        : "一列"
                  }}
                </span>
              </button>
            </div>
          </template>
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
      <div
        v-if="formulaAssistTab === 'template' || formulaAssistResult"
        class="etl-assist-result"
      >
        <span class="etl-assist-label">公式预览（可改）</span>
        <p v-if="formulaAssistExplain" class="etl-assist-explain">
          <el-tag size="small" style="margin-right: 6px">
            {{
              formulaAssistSource === "template"
                ? "模板"
                : formulaAssistSource === "ai"
                  ? "AI"
                  : formulaAssistSource === "rules"
                    ? "规则"
                    : "公式"
            }}
          </el-tag>
          {{ formulaAssistExplain }}
        </p>
        <el-input
          v-model="formulaAssistResult"
          type="textarea"
          :rows="formulaAssistTab === 'template' ? 4 : 5"
          :placeholder="
            formulaAssistTab === 'template'
              ? '先选字段，再点模板（如「转大写」）生成公式'
              : '生成后可手改'
          "
        />
      </div>
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
@use "./etl.styles/scoped.scss" as *;
</style>

<style lang="scss">
/* teleported 到 body，需非 scoped：避免下拉左边框被 dialog/tabs 裁切 */
.etl-assist-dialog.el-dialog,
.etl-assist-dialog .el-dialog__body {
  overflow: visible;
}

.etl-assist-dialog .el-tabs__content,
.etl-assist-dialog .el-tab-pane {
  overflow: visible;
}
</style>
