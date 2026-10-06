<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { ElMessage } from "element-plus";
import type { UploadFile } from "element-plus";
import {
  createDefectScanBatch,
  getScanBootstrap,
  importDefectScans,
  listDefectScans,
  type DefectScanOp,
  type ScanDefectOption,
  type ScanProject
} from "@/api/modules/scan";
import { backendErrorHint } from "@/api/http";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";

defineOptions({
  name: "ScanDefect"
});

type ScanMode = "scan" | "file";

const loading = ref(false);
const scanning = ref(false);
const hint = ref("");
const mode = ref<ScanMode>("scan");
const projects = ref<ScanProject[]>([]);
const defects = ref<ScanDefectOption[]>([]);
const projectId = ref("");
const defectItem = ref("");
const snInput = ref("");
const ops = ref<DefectScanOp[]>([]);
const lastOp = ref<DefectScanOp | null>(null);
const scanBox = ref<{ focus: () => void } | null>(null);
let bootAbort: AbortController | null = null;
let listAbort: AbortController | null = null;

const canWrite = computed(
  () => Boolean(projectId.value && defectItem.value) && !scanning.value
);

const pendingSns = computed(() =>
  snInput.value
    .split(/[\n,;\t]+/)
    .map(item => item.trim())
    .filter(Boolean)
);

function labelOf(item: string) {
  return defects.value.find(row => row.key === item)?.label || item;
}

function pickDefect(key: string, on: boolean | string | number) {
  if (on) defectItem.value = key;
}

function focusScan() {
  if (mode.value !== "scan") return;
  nextTick(() => scanBox.value?.focus());
}

function ensureReady() {
  if (!projectId.value) {
    ElMessage.warning("请选择项目");
    return false;
  }
  if (!defectItem.value) {
    ElMessage.warning("请勾选次品项");
    return false;
  }
  return true;
}

function prependOp(op?: DefectScanOp | null) {
  if (!op) return;
  ops.value = [op, ...ops.value.filter(row => row.id !== op.id)];
  lastOp.value = op;
}

async function loadBootstrap(id = "") {
  bootAbort?.abort();
  bootAbort = new AbortController();
  loading.value = true;
  hint.value = "";
  try {
    const res = await getScanBootstrap(id || undefined, bootAbort.signal);
    const data = res?.data;
    projects.value = data?.projects || [];
    projectId.value = data?.current_id || "";
    defects.value = data?.defects || [];
    if (!defects.value.some(item => item.key === defectItem.value)) {
      defectItem.value = "";
    }
    if (!projects.value.length) hint.value = "还没有启用的项目";
    else if (!defects.value.length) {
      hint.value = "该项目还没有配置次品名称，请先到功能管理填写";
    }
  } catch (error) {
    hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

async function loadScans() {
  listAbort?.abort();
  listAbort = new AbortController();
  try {
    const res = await listDefectScans(
      {
        project_id: projectId.value || undefined,
        defect_item: defectItem.value || undefined
      },
      listAbort.signal
    );
    ops.value = res?.data?.ops || [];
  } catch (error) {
    hint.value = backendErrorHint(error);
  }
}

async function onProjectChange(id: string) {
  await loadBootstrap(id);
  await loadScans();
  focusScan();
}

async function submitScan() {
  if (!ensureReady()) return;
  const sns = pendingSns.value;
  if (!sns.length) {
    ElMessage.warning("请先扫码");
    return;
  }
  scanning.value = true;
  try {
    const res = await createDefectScanBatch({
      project_id: projectId.value,
      defect_item: defectItem.value,
      sns
    });
    const saved = res?.data;
    snInput.value = "";
    prependOp(saved?.op);
    ElMessage.success(`已上传 ${saved?.count || 0} 条`);
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    scanning.value = false;
    focusScan();
  }
}

async function onUploadFile(upload: UploadFile) {
  const file = upload.raw;
  if (!file || upload.status !== "ready" || !ensureReady()) return;
  scanning.value = true;
  try {
    const res = await importDefectScans(
      projectId.value,
      defectItem.value,
      file
    );
    const saved = res?.data;
    prependOp(saved?.op);
    ElMessage.success(`已从文件上传 ${saved?.count || 0} 条`);
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    scanning.value = false;
  }
}

watch(defectItem, () => {
  void loadScans();
});

onMounted(async () => {
  await loadBootstrap();
  await loadScans();
  focusScan();
});
onUnmounted(() => {
  bootAbort?.abort();
  listAbort?.abort();
});
</script>

<template>
  <div class="scan-page" v-loading="loading">
    <header class="scan-head">
      <div>
        <strong>次品扫码</strong>
        <span>连续扫码后批量写入，或把已经扫进文件的名单导进来</span>
      </div>
    </header>

    <p v-if="hint" class="scan-banner">
      {{ hint }}
      <RouterLink
        v-if="projectId && !defects.length"
        class="scan-link"
        to="/feature/scan-defects"
      >
        去配置
      </RouterLink>
    </p>

    <section class="scan-sheet">
      <div class="scan-filters">
        <label class="scan-field">
          <span>项目</span>
          <el-select
            v-model="projectId"
            filterable
            placeholder="选择项目"
            @change="onProjectChange"
          >
            <el-option
              v-for="item in projects"
              :key="item.project_id"
              :label="item.display_name"
              :value="item.project_id"
            />
          </el-select>
        </label>
        <div class="scan-field is-grow">
          <span>次品项</span>
          <div v-if="defects.length" class="scan-checks">
            <el-checkbox
              v-for="item in defects"
              :key="item.key"
              :model-value="defectItem === item.key"
              @change="on => pickDefect(item.key, on)"
            >
              {{ item.label }}
            </el-checkbox>
          </div>
          <p v-else class="scan-checks-empty">请先配置次品名称</p>
        </div>
      </div>

      <div class="scan-gun">
        <div class="scan-modes">
          <button
            type="button"
            :class="{ on: mode === 'scan' }"
            @click="mode = 'scan'"
          >
            <span class="scan-modes__icon">
              <component :is="useRenderIcon('ri/qr-scan-2-line')" />
            </span>
            <span class="scan-modes__text">
              <b>扫码上传</b>
              <small>连续扫码，批量写入</small>
            </span>
          </button>
          <button
            type="button"
            :class="{ on: mode === 'file' }"
            @click="mode = 'file'"
          >
            <span class="scan-modes__icon">
              <component :is="useRenderIcon('ri/file-text-line')" />
            </span>
            <span class="scan-modes__text">
              <b>文件上传</b>
              <small>先扫进文件再导入</small>
            </span>
          </button>
        </div>

        <template v-if="mode === 'scan'">
          <el-input
            ref="scanBox"
            v-model="snInput"
            type="textarea"
            :autosize="{ minRows: 6, maxRows: 14 }"
            :disabled="scanning"
            placeholder="光标放在这里连续扫码或粘贴，一码一行，扫完后点批量上传"
          />
          <div class="scan-actions">
            <span>已扫 {{ pendingSns.length }} 条</span>
            <el-button
              type="primary"
              :disabled="!canWrite || !pendingSns.length"
              :loading="scanning"
              @click="submitScan"
            >
              批量上传
            </el-button>
          </div>
        </template>

        <el-upload
          v-else
          drag
          :auto-upload="false"
          :show-file-list="false"
          accept=".txt,.csv,.xlsx,.xls"
          :disabled="!canWrite"
          :on-change="onUploadFile"
        >
          <div class="scan-drop">
            <span class="scan-drop__icon">
              <component :is="useRenderIcon('ri/upload-2-line')" />
            </span>
            <strong>上传已扫好的文件</strong>
            <p>支持 txt、csv、Excel</p>
          </div>
        </el-upload>

        <em v-if="lastOp">
          刚上传 {{ lastOp.count }} 条 · {{ lastOp.method_label }} ·
          {{ labelOf(lastOp.defect_item) }}
        </em>
      </div>
    </section>

    <section class="scan-sheet">
      <div class="scan-toolbar">
        <strong>操作记录</strong>
        <el-button @click="loadScans">刷新</el-button>
      </div>
      <el-table
        class="scan-table"
        :data="ops"
        border
        empty-text="还没有操作记录"
        :header-cell-style="{
          background: '#1e4e79',
          color: '#fff',
          fontWeight: 600,
          fontSize: '12px',
          borderColor: '#163c5c',
          textAlign: 'center'
        }"
      >
        <el-table-column
          prop="created_at"
          label="时间"
          width="168"
          align="center"
        />
        <el-table-column
          prop="project_name"
          label="项目"
          width="168"
          show-overflow-tooltip
        />
        <el-table-column
          prop="method_label"
          label="方式"
          width="100"
          align="center"
        />
        <el-table-column
          label="不良"
          width="168"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            {{ labelOf(row.defect_item) }}
          </template>
        </el-table-column>
        <el-table-column prop="count" label="数量" width="88" align="center" />
        <el-table-column class-name="scan-table__fill" min-width="1" />
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.scan-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-sizing: border-box;
  min-height: calc(100vh - 86px);
  margin: 0 !important;
  padding: 12px 16px 16px;
  background: #eef7fb;
}

.scan-head {
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #d5ddd8;
  border-radius: 10px;
}

.scan-head strong {
  display: block;
  color: #0c3f56;
  font-size: 16px;
  font-weight: 700;
}

.scan-head span {
  color: #5b6b63;
  font-size: 12px;
}

.scan-banner {
  margin: 0;
  padding: 8px 12px;
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #f0d48a;
  border-radius: 8px;
  font-size: 13px;
}

.scan-link {
  margin-left: 8px;
  color: #1e4e79;
  font-weight: 650;
}

.scan-sheet {
  background: #fff;
  border: 1px solid #d5ddd8;
  border-radius: 10px;
  overflow: hidden;
}

.scan-filters {
  display: grid;
  grid-template-columns: minmax(200px, 280px) minmax(0, 1fr);
  gap: 12px;
  padding: 16px 16px 0;
}

.scan-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #4d5d56;
  font-size: 12px;
}

.scan-checks {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 18px;
  min-height: 32px;
}

.scan-checks :deep(.el-checkbox) {
  margin-right: 0;
  height: 32px;
}

.scan-checks-empty {
  margin: 0;
  color: #8a9a93;
  font-size: 13px;
  line-height: 32px;
}

.scan-gun {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 16px 18px;
}

.scan-modes {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.scan-modes button {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 64px;
  padding: 10px 14px;
  border: 1px solid #d5ddd8;
  border-radius: 10px;
  background: #f6f8f6;
  color: #0c3f56;
  text-align: left;
  cursor: pointer;
}

.scan-modes button.on {
  background: #e0f4fc;
  border-color: #1e4e79;
  box-shadow: 0 0 0 1px #1e4e79 inset;
}

.scan-modes__icon {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: #fff;
  color: #1e4e79;
  font-size: 20px;
}

.scan-modes button.on .scan-modes__icon {
  background: #1e4e79;
  color: #fff;
}

.scan-modes__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.scan-modes__text b {
  font-size: 14px;
  font-weight: 700;
}

.scan-modes__text small {
  color: #6b7b74;
  font-size: 12px;
}

.scan-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #6b7b74;
  font-size: 13px;
}

.scan-gun :deep(.el-textarea__inner) {
  min-height: 140px;
  font-size: 16px;
  font-variant-numeric: tabular-nums;
  line-height: 1.6;
  letter-spacing: 0.03em;
}

.scan-drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 8px 0;
}

.scan-drop__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  color: #1e4e79;
  font-size: 28px;
}

.scan-drop strong {
  color: #0c3f56;
  font-size: 14px;
}

.scan-drop p {
  margin: 0;
  color: #6b7b74;
  font-size: 12px;
}

.scan-gun > em {
  color: #1e4e79;
  font-style: normal;
  font-size: 13px;
  font-weight: 650;
}

.scan-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
}

.scan-toolbar strong {
  flex: 1;
  color: #0c3f56;
  font-size: 14px;
}

.scan-table {
  --el-table-border-color: #c6c6c6;
  font-family: Calibri, "Microsoft YaHei", "Segoe UI", sans-serif;
  font-size: 12px;
}

.scan-table :deep(.el-table__cell) {
  padding: 6px 10px;
}

.scan-table :deep(.el-table__header-wrapper th.el-table__cell) {
  background: #1e4e79 !important;
  color: #fff;
  padding: 0 8px;
  height: 32px;
}

.scan-table :deep(th.scan-table__fill),
.scan-table :deep(td.scan-table__fill) {
  border-left-color: #c6c6c6;
  pointer-events: none;
}

.scan-table :deep(th.scan-table__fill .cell),
.scan-table :deep(td.scan-table__fill .cell) {
  padding: 0;
}

@media (max-width: 800px) {
  .scan-filters,
  .scan-modes {
    grid-template-columns: 1fr;
  }
}
</style>
