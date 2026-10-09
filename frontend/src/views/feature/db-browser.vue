<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { listConnections } from "@/api/modules/connections";
import {
  clearDbTable,
  downloadDbTable,
  getDbTableRows,
  getDbTables,
  type DbTableItem,
  type DbTarget,
  type DbTargetInfo
} from "@/api/modules/db-browser";
import { backendErrorHint } from "@/api/http";
import PageTabs from "@/components/PageTabs/index.vue";

defineOptions({
  name: "FeatureDbBrowser"
});

const TARGETS: { key: DbTarget; label: string; hint: string }[] = [
  {
    key: "meta",
    label: "元数据 SQLite",
    hint: "用户 / 项目 / 连接配置"
  },
  {
    key: "raw",
    label: "原始库",
    hint: "外部连接 · lim_raw"
  },
  {
    key: "dwh",
    label: "ETL 库",
    hint: "外部连接 · lim_dwh"
  },
  {
    key: "defect",
    label: "次品库",
    hint: "外部连接 · lim_defect"
  }
];

const active = ref<DbTarget>("meta");
const loadingTables = ref(false);
const loadingRows = ref(false);
const info = ref<DbTargetInfo | null>(null);
const tables = ref<DbTableItem[]>([]);
const tableFilter = ref("");
const selectedTable = ref("");
const columns = ref<string[]>([]);
const rows = ref<Record<string, string | null>[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const adminerUrl = ref("");
const errorHint = ref("");
const clearing = ref(false);
const downloading = ref(false);
/** 日期控件上的起止时间（未点查询前不生效） */
const timeFrom = ref("");
const timeTo = ref("");
/** 已应用到列表查询的范围 */
const appliedTimeFrom = ref("");
const appliedTimeTo = ref("");
let tablesAbort: AbortController | null = null;
let rowsAbort: AbortController | null = null;

const targetTabs = computed(() =>
  TARGETS.map(item => {
    const live = item.key === active.value && info.value;
    return {
      value: item.key,
      label: item.label,
      hint: live ? info.value.endpoint : item.hint,
      status: live
        ? {
            ok: Boolean(info.value.ok),
            label: info.value.ok ? "已连通" : "不可用"
          }
        : undefined
    };
  })
);

function isAbortError(error: unknown) {
  return (
    (error as { code?: string; name?: string })?.code === "ERR_CANCELED" ||
    (error as { name?: string })?.name === "CanceledError" ||
    (error as { name?: string })?.name === "AbortError"
  );
}

const filteredTables = computed(() => {
  const q = tableFilter.value.trim().toLowerCase();
  if (!q) return tables.value;
  return tables.value.filter(t => t.name.toLowerCase().includes(q));
});

const selectedTableMeta = computed(
  () => tables.value.find(t => t.name === selectedTable.value) || null
);

/** 表含 ServerTime 时显示时间范围（原始库等） */
const showTimeFilter = computed(() => {
  if (!selectedTable.value) return false;
  if (selectedTableMeta.value?.time_column) return true;
  return columns.value.some(
    c => c === "ServerTime" || c.toLowerCase() === "servertime"
  );
});

function rangeParams(
  from: string,
  to: string
): { time_from?: string; time_to?: string } {
  const a = from.trim();
  const b = to.trim();
  if (!a && !b) return {};
  const out: { time_from?: string; time_to?: string } = {};
  if (a) out.time_from = a;
  if (b) out.time_to = b;
  return out;
}

function timeParams(): { time_from?: string; time_to?: string } {
  return rangeParams(appliedTimeFrom.value, appliedTimeTo.value);
}

/** 按字符估算显示宽度（中文约 2 倍宽），用于列宽贴合内容 */
function estimateTextWidth(text: string): number {
  let width = 0;
  for (const ch of String(text)) {
    width += /[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/.test(ch) ? 14 : 7.5;
  }
  return width;
}

type ColMeta = {
  name: string;
  /** 固定贴合内容的列宽 */
  width?: number;
  /** 内容最长列：只设 minWidth，吃掉剩余空间 */
  minWidth?: number;
  flex?: boolean;
};

/** ServerTime 提到 machine / 机台 之前，便于对照时间与机台 */
function orderColumns(cols: string[]): string[] {
  const timeIdx = cols.findIndex(
    c => c === "ServerTime" || c.toLowerCase() === "servertime"
  );
  if (timeIdx < 0) return cols;
  const machineIdx = cols.findIndex(
    c => c === "machine" || c === "机台"
  );
  if (machineIdx < 0 || timeIdx === machineIdx - 1) return cols;
  const next = cols.slice();
  const [timeCol] = next.splice(timeIdx, 1);
  const insertAt = next.findIndex(c => c === "machine" || c === "机台");
  if (insertAt < 0) return cols;
  next.splice(insertAt, 0, timeCol);
  return next;
}

const columnMetas = computed<ColMeta[]>(() => {
  const cols = orderColumns(columns.value);
  if (!cols.length) return [];
  const sample = rows.value.slice(0, 50);
  const scored = cols.map(name => {
    let content = estimateTextWidth(name) + 28;
    for (const row of sample) {
      const value = row[name];
      if (value == null || value === "") continue;
      const text = String(value);
      // 超长只取前 80 字估算，避免 JSON 大字段把列撑爆
      content = Math.max(
        content,
        estimateTextWidth(text.length > 80 ? text.slice(0, 80) : text) + 28
      );
    }
    return { name, content };
  });

  let flexIdx = 0;
  for (let i = 1; i < scored.length; i++) {
    if (scored[i].content > scored[flexIdx].content) flexIdx = i;
  }

  return scored.map((item, index) => {
    if (index === flexIdx) {
      return {
        name: item.name,
        minWidth: Math.min(Math.max(Math.ceil(item.content), 140), 420),
        flex: true
      };
    }
    return {
      name: item.name,
      width: Math.min(Math.max(Math.ceil(item.content), 52), 168),
      flex: false
    };
  });
});

async function loadTables() {
  tablesAbort?.abort();
  tablesAbort = new AbortController();
  const signal = tablesAbort.signal;
  loadingTables.value = true;
  errorHint.value = "";
  tables.value = [];
  selectedTable.value = "";
  columns.value = [];
  rows.value = [];
  total.value = 0;
  info.value = null;
  try {
    const res = await getDbTables(active.value, signal);
    const data = res?.data;
    info.value = data?.info || null;
    tables.value = data?.tables || [];
    if (info.value && !info.value.ok) {
      errorHint.value = info.value.error || "数据源不可用，请先在「连接管理」检查配置";
    } else if (tables.value.length) {
      await selectTable(tables.value[0].name);
    }
  } catch (error) {
    if (!isAbortError(error)) errorHint.value = backendErrorHint(error);
  } finally {
    loadingTables.value = false;
  }
}

async function selectTable(name: string) {
  selectedTable.value = name;
  page.value = 1;
  timeFrom.value = "";
  timeTo.value = "";
  appliedTimeFrom.value = "";
  appliedTimeTo.value = "";
  await loadRows();
}

async function loadRows() {
  if (!selectedTable.value) return;
  rowsAbort?.abort();
  rowsAbort = new AbortController();
  const signal = rowsAbort.signal;
  loadingRows.value = true;
  errorHint.value = "";
  try {
    const offset = (page.value - 1) * pageSize.value;
    const res = await getDbTableRows(
      active.value,
      selectedTable.value,
      {
        limit: pageSize.value,
        offset,
        ...timeParams()
      },
      signal
    );
    const data = res?.data;
    columns.value = data?.columns || [];
    rows.value = data?.rows || [];
    total.value = Number(data?.total || 0);
  } catch (error) {
    if (isAbortError(error)) return;
    errorHint.value = backendErrorHint(error);
    columns.value = [];
    rows.value = [];
    total.value = 0;
  } finally {
    loadingRows.value = false;
  }
}

function onQueryByTime() {
  if (!selectedTable.value) {
    ElMessage.warning("请先选择数据表");
    return;
  }
  const from = timeFrom.value.trim();
  const to = timeTo.value.trim();
  if ((from && !to) || (!from && to)) {
    ElMessage.warning("请选择完整的 ServerTime 起止时间");
    return;
  }
  appliedTimeFrom.value = from;
  appliedTimeTo.value = to;
  page.value = 1;
  loadRows();
}

function switchTarget(key: string) {
  const next = key as DbTarget;
  if (active.value === next) return;
  active.value = next;
  tableFilter.value = "";
  timeFrom.value = "";
  timeTo.value = "";
  appliedTimeFrom.value = "";
  appliedTimeTo.value = "";
  loadTables();
}

function openAdminer() {
  const base =
    adminerUrl.value ||
    String(import.meta.env.VITE_DBWEB_URL || "").replace(/\/$/, "") ||
    `${window.location.protocol}//${window.location.hostname}:18080`;
  window.open(base, "_blank", "noopener");
}

async function onDownloadTable() {
  if (active.value === "dwh") {
    ElMessage.warning("ETL 库禁止下载表");
    return;
  }
  if (!selectedTable.value) {
    ElMessage.warning("请先选择数据表");
    return;
  }
  if (!info.value?.ok) {
    ElMessage.warning("当前库不可用，无法下载");
    return;
  }
  const range = rangeParams(timeFrom.value, timeTo.value);
  if (showTimeFilter.value && (!range.time_from || !range.time_to)) {
    ElMessage.warning("请先选择 ServerTime 起止时间");
    return;
  }
  downloading.value = true;
  try {
    await downloadDbTable(
      active.value,
      selectedTable.value,
      showTimeFilter.value ? range : undefined
    );
    ElMessage.success(
      showTimeFilter.value
        ? `已按时间范围下载「${selectedTable.value}」`
        : `已开始下载「${selectedTable.value}」`
    );
  } catch (error) {
    ElMessage.error(
      error instanceof Error ? error.message : backendErrorHint(error)
    );
  } finally {
    downloading.value = false;
  }
}

async function onClearTable() {
  if (active.value === "meta") {
    ElMessage.warning("元数据库禁止清空表");
    return;
  }
  if (!selectedTable.value) {
    ElMessage.warning("请先选择数据表");
    return;
  }
  if (!info.value?.ok) {
    ElMessage.warning("当前库不可用，无法清空");
    return;
  }
  try {
    await ElMessageBox.confirm(
      `将清空表「${selectedTable.value}」全部数据（保留表结构）。此操作不可撤销。`,
      "清空当前表",
      {
        type: "warning",
        confirmButtonText: "确认清空",
        cancelButtonText: "取消",
        confirmButtonClass: "el-button--danger"
      }
    );
  } catch {
    return;
  }
  clearing.value = true;
  try {
    await clearDbTable(active.value, selectedTable.value);
    ElMessage.success(`已清空「${selectedTable.value}」`);
    await loadRows();
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    clearing.value = false;
  }
}

function onPageChange(next: number) {
  page.value = next;
  loadRows();
}

onMounted(async () => {
  try {
    const res = await listConnections();
    if (res?.data?.dbweb?.url) adminerUrl.value = res.data.dbweb.url;
  } catch {
    /* ignore */
  }
  await loadTables();
});

onUnmounted(() => {
  tablesAbort?.abort();
  rowsAbort?.abort();
});
</script>

<template>
  <div class="db-page">
    <header class="db-head">
      <div>
        <h2>数据浏览</h2>
        <p>
          直接读取项目已配置连接（元数据 SQLite / 原始库 / ETL 库 / 次品库），无需再登录
          Adminer
        </p>
      </div>
      <div class="db-head__actions">
        <el-button :loading="loadingTables" @click="loadTables">刷新</el-button>
        <el-button type="primary" plain @click="openAdminer">
          打开 Adminer
        </el-button>
      </div>
    </header>

    <PageTabs
      :model-value="active"
      :options="targetTabs"
      stretch
      aria-label="数据源"
      @change="switchTarget"
    />

    <el-alert
      v-if="errorHint"
      type="warning"
      :closable="false"
      :title="errorHint"
      show-icon
    />

    <div class="db-body" v-loading="loadingTables">
      <aside class="db-side">
        <el-input
          v-model="tableFilter"
          clearable
          placeholder="筛选表名"
          class="db-side__search"
        />
        <div class="db-side__list">
          <button
            v-for="item in filteredTables"
            :key="item.name"
            type="button"
            class="db-side__item"
            :class="{ 'is-active': selectedTable === item.name }"
            @click="selectTable(item.name)"
          >
            <span class="db-side__name">{{ item.name }}</span>
            <span class="db-side__cols">{{ item.columns }} 列</span>
          </button>
          <div v-if="!filteredTables.length" class="db-empty">暂无表</div>
        </div>
      </aside>

      <section class="db-main" v-loading="loadingRows">
        <div class="db-main__bar">
          <div class="db-main__meta">
            <strong>{{ selectedTable || "未选择表" }}</strong>
            <span v-if="selectedTable">共 {{ total.toLocaleString() }} 行</span>
          </div>
          <div v-if="selectedTable" class="db-main__actions">
            <el-date-picker
              v-if="showTimeFilter"
              v-model="timeFrom"
              type="datetime"
              size="small"
              clearable
              placeholder="起"
              format="YYYY-MM-DD HH:mm:ss"
              value-format="YYYY-MM-DDTHH:mm:ss"
              class="db-main__time"
            />
            <el-date-picker
              v-if="showTimeFilter"
              v-model="timeTo"
              type="datetime"
              size="small"
              clearable
              placeholder="止"
              format="YYYY-MM-DD HH:mm:ss"
              value-format="YYYY-MM-DDTHH:mm:ss"
              class="db-main__time"
            />
            <el-button
              v-if="showTimeFilter"
              size="small"
              type="primary"
              plain
              :loading="loadingRows"
              :disabled="!info?.ok"
              @click="onQueryByTime"
            >
              查询
            </el-button>
            <el-button
              v-if="active !== 'dwh'"
              size="small"
              :loading="downloading"
              :disabled="!info?.ok"
              @click="onDownloadTable"
            >
              {{ showTimeFilter ? "下载" : "下载本表" }}
            </el-button>
            <el-button
              v-if="active !== 'meta'"
              size="small"
              type="danger"
              plain
              :loading="clearing"
              :disabled="!info?.ok"
              @click="onClearTable"
            >
              清空本表
            </el-button>
          </div>
        </div>

        <el-table
          v-if="selectedTable"
          :key="`${active}-${selectedTable}-${columns.join('|')}`"
          :data="rows"
          border
          stripe
          height="100%"
          class="db-table"
          empty-text="无数据"
          table-layout="fixed"
        >
          <el-table-column
            v-for="col in columnMetas"
            :key="col.name"
            :prop="col.name"
            :label="col.name"
            :width="col.flex ? undefined : col.width"
            :min-width="col.flex ? col.minWidth : undefined"
            show-overflow-tooltip
          />
        </el-table>
        <div v-else class="db-empty db-empty--main">从左侧选择一张表查看数据</div>

        <div
          v-if="selectedTable && total > 0"
          class="db-main__pager"
        >
          <el-pagination
            :current-page="page"
            :page-size="pageSize"
            :total="total"
            layout="prev, pager, next"
            small
            background
            @current-change="onPageChange"
          />
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.db-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - var(--la-chrome-total) - var(--la-content-inset) * 2);
  min-height: 480px;
  padding: var(--la-page-pad-y) var(--la-page-pad-x) var(--la-space-xl);
}

.db-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--la-space-md);
}

.db-head h2 {
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: var(--la-page-title);
  font-weight: 650;
}

.db-head p {
  margin: 2px 0 0;
  color: var(--el-text-color-secondary);
  font-size: var(--la-page-desc);
}

.db-head__actions {
  display: flex;
  gap: 8px;
}

.db-body {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 12px;
  flex: 1;
  min-height: 0;
}

.db-side {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  padding: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  background: var(--el-bg-color);
}

.db-side__list {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.db-side__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  margin-bottom: 4px;
  text-align: left;
  cursor: pointer;
  border: 0;
  border-radius: 8px;
  background: transparent;
}

.db-side__item:hover {
  background: var(--el-fill-color-lighter);
}

.db-side__item.is-active {
  background: color-mix(in srgb, var(--el-color-primary) 10%, transparent);
}

.db-side__name {
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.db-side__cols {
  flex: none;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.db-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  background: var(--el-bg-color);
}

.db-main__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.db-main__meta {
  display: flex;
  flex: 1 1 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  min-width: 0;
}

.db-main__bar strong {
  font-size: 14px;
}

.db-main__bar span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.db-main__time.el-date-editor {
  --el-date-editor-width: 178px;
  box-sizing: border-box;
  width: 178px;
  flex: none;
}

.db-main__actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 8px;
}

.db-main__pager {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: flex-end;
  margin-top: 10px;
}

.db-table {
  flex: 1;
  min-height: 0;
  width: 100%;
}

.db-table :deep(.el-table__cell) {
  padding: 5px 6px;
  text-align: center;
  vertical-align: middle;
}

.db-table :deep(.cell) {
  padding: 0 2px;
  line-height: 1.35;
  font-size: 12px;
  text-align: center;
}

.db-table :deep(th.el-table__cell .cell) {
  font-weight: 650;
  white-space: nowrap;
}

.db-empty {
  padding: 20px 8px;
  color: var(--el-text-color-placeholder);
  font-size: 12px;
  text-align: center;
}

.db-empty--main {
  display: grid;
  flex: 1;
  place-items: center;
}

@media (max-width: 960px) {
  .db-page {
    height: auto;
  }

  .db-body {
    grid-template-columns: 1fr;
  }

  .db-side {
    max-height: 220px;
  }

  .db-main {
    min-height: 420px;
  }
}
</style>
