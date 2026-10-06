<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { listConnections } from "@/api/modules/connections";
import {
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

const targetTabs = TARGETS.map(item => ({
  value: item.key,
  label: item.label,
  hint: item.hint
}));

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
let tablesAbort: AbortController | null = null;
let rowsAbort: AbortController | null = null;

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

const columnMetas = computed<ColMeta[]>(() => {
  const cols = columns.value;
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
        offset
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

function switchTarget(key: string) {
  const next = key as DbTarget;
  if (active.value === next) return;
  active.value = next;
  tableFilter.value = "";
  loadTables();
}

function openAdminer() {
  const base =
    adminerUrl.value ||
    String(import.meta.env.VITE_DBWEB_URL || "").replace(/\/$/, "") ||
    `${window.location.protocol}//${window.location.hostname}:18080`;
  window.open(base, "_blank", "noopener");
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

    <div v-if="info" class="db-status" :class="{ 'is-ok': info.ok }">
      <span>{{ info.label }}</span>
      <code>{{ info.endpoint }}</code>
      <el-tag size="small" :type="info.ok ? 'success' : 'danger'" effect="light">
        {{ info.ok ? "已连通" : "不可用" }}
      </el-tag>
    </div>

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
          <div>
            <strong>{{ selectedTable || "未选择表" }}</strong>
            <span v-if="selectedTable">共 {{ total.toLocaleString() }} 行</span>
          </div>
          <el-pagination
            v-if="selectedTable && total > 0"
            :current-page="page"
            :page-size="pageSize"
            :total="total"
            layout="prev, pager, next"
            small
            background
            @current-change="onPageChange"
          />
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
      </section>
    </div>
  </div>
</template>

<style scoped>
.db-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 96px);
  min-height: 560px;
  padding: 20px 24px 24px;
}

.db-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.db-head h2 {
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: 18px;
  font-weight: 700;
}

.db-head p {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.db-head__actions {
  display: flex;
  gap: 8px;
}

.db-status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--el-fill-color-lighter);
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.db-status.is-ok {
  background: color-mix(in srgb, var(--el-color-success) 8%, var(--el-bg-color));
}

.db-status code {
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--el-bg-color);
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

.db-main__bar strong {
  margin-right: 10px;
  font-size: 14px;
}

.db-main__bar span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.db-table {
  flex: 1;
  min-height: 0;
  width: 100%;
}

.db-table :deep(.el-table__cell) {
  padding: 5px 6px;
}

.db-table :deep(.cell) {
  padding: 0 2px;
  line-height: 1.35;
  font-size: 12px;
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
